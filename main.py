"""Painel local de quedas, confirmação de EPI por pessoa e coleta de imagens."""

import copy
import json
import os
import smtplib
import ssl
import threading
import time
from collections import deque
from contextlib import ExitStack
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

from epi_monitoramento import (
    EPIS, MotorAlertas, classificar_postura, enriquecer_rosto, identificar_epi,
    mapear_pontos_pose, regiao_pose,
)

BASE = Path(__file__).resolve().parent


def carregar_env_local():
    arquivo = BASE / ".env"
    if arquivo.is_file():
        for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                chave, valor = linha.split("=", 1)
                os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


carregar_env_local()
CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "1"))
COOLDOWN = max(0, float(os.getenv("COOLDOWN_SEGUNDOS", "60")))
CONFIRMACAO_EPI = max(1, float(os.getenv("EPI_CONFIRMACAO_SEGUNDOS", "3")))
CONFIRMACAO_QUEDA = max(1, float(os.getenv("QUEDA_CONFIRMACAO_SEGUNDOS", "2")))


def localizar_modelo_epi():
    principal = Path(os.getenv("EPI_MODEL_PATH", "epi.pt"))
    principal = principal if principal.is_absolute() else BASE / principal
    if principal.is_file():
        return principal
    candidatos = sorted(
        (BASE / "runs" / "detect").glob("treinamento_epi*/weights/best.pt"),
        key=lambda caminho: caminho.stat().st_mtime, reverse=True,
    )
    return candidatos[0] if candidatos else None


MODELO_EPI = localizar_modelo_epi()


def localizar_modelo_oculos():
    # Modelo já comparado neste projeto; configurável sem substituir epi.pt.
    caminho = Path(os.getenv("OCULOS_MODEL_PATH", "runs/detect/treinamento_epi-2/weights/best.pt"))
    caminho = caminho if caminho.is_absolute() else BASE / caminho
    return caminho if caminho.is_file() else None


MODELO_OCULOS = localizar_modelo_oculos()


def extrair_deteccoes_epi(resultados, piso_oculos=0.5):
    deteccoes = []
    for resultado in resultados:
        for box, classe, conf in zip(resultado.boxes.xyxy, resultado.boxes.cls, resultado.boxes.conf):
            nome = resultado.names[int(classe)]
            minimo = piso_oculos if identificar_epi(nome) == "oculos" else 0.5
            if float(conf) >= minimo:
                deteccoes.append({"caixa": tuple(box.tolist()), "classe": nome, "confianca": float(conf)})
    return deteccoes


def abrir_camera(indice):
    import cv2
    camera = cv2.VideoCapture(indice, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(indice)
    if not camera.isOpened():
        camera.release()
        camera = cv2.VideoCapture(indice)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return camera


class Monitor:
    def __init__(self, base=BASE, modelo_epi=MODELO_EPI, modelo_oculos=MODELO_OCULOS):
        self.base = Path(base)
        self.capturas = self.base / "capturas"
        self.coleta = self.base / "amostras_epi" / "pendentes"
        self.config = self.base / "config_epi.json"
        self.modelo_epi = Path(modelo_epi) if modelo_epi else None
        self.modelo_oculos = Path(modelo_oculos) if modelo_oculos else None
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.frame = None
        self.frame_original = None
        self.frame_instante = None
        self.eventos = deque(maxlen=30)
        self.epi_obrigatorio = []
        self.confirmacao_epi = CONFIRMACAO_EPI
        self._config_extra = {}
        try:
            dados = json.loads(self.config.read_text(encoding="utf-8"))
            if isinstance(dados, dict):
                self._config_extra = dados
                itens = dados.get("obrigatorios", [])
                if isinstance(itens, list):
                    self.epi_obrigatorio = list(dict.fromkeys(item for item in itens if isinstance(item, str) and item in EPIS))
                segundos = float(dados.get("confirmacao_segundos", self.confirmacao_epi))
                if 1 <= segundos <= 30:
                    self.confirmacao_epi = segundos
        except (OSError, ValueError, TypeError):
            pass
        self.motor = MotorAlertas(self.confirmacao_epi, CONFIRMACAO_QUEDA, COOLDOWN)
        self.status = {
            "executando": False, "estado": "parado", "mensagem": "Monitoramento parado.",
            "camera": CAMERA_INDEX, "deteccoes": [], "fps": 0,
            "epi_obrigatorio": list(self.epi_obrigatorio),
            "confirmacao_segundos": self.confirmacao_epi,
            "queda_confirmacao_segundos": CONFIRMACAO_QUEDA,
            "modelo_epi_disponivel": self.modelo_epi is not None and self.modelo_epi.is_file(),
            "modelo_epi": self.modelo_epi.name if self.modelo_epi else None,
            "epi_ativo": False, "epi_erro": None, "epis_suportados": [],
            "oculos_ativo": False, "oculos_erro": None,
            "modelo_oculos": str(self.modelo_oculos.relative_to(BASE)) if self.modelo_oculos and self.modelo_oculos.is_relative_to(BASE) else (self.modelo_oculos.name if self.modelo_oculos else None),
            "aviso": None, "aviso_desempenho": None, "processamento_segundos": 0,
        }

    def configurar_epi(self, itens, segundos=None):
        if not isinstance(itens, list) or any(not isinstance(item, str) or item not in EPIS for item in itens):
            raise ValueError("Selecione apenas os EPIs disponíveis.")
        segundos = self.confirmacao_epi if segundos is None else segundos
        if isinstance(segundos, bool) or not isinstance(segundos, (int, float)) or not 1 <= segundos <= 30:
            raise ValueError("O tempo de confirmação deve ficar entre 1 e 30 segundos.")
        itens = list(dict.fromkeys(itens))
        with self.lock:
            dados = {**self._config_extra, "obrigatorios": itens, "confirmacao_segundos": segundos}
            temporario = self.config.with_suffix(".tmp")
            temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporario, self.config)
            self._config_extra = dados
            self.epi_obrigatorio = itens
            self.confirmacao_epi = segundos
            self.motor.confirmacao_epi = segundos
            # Política alterada: nenhuma observação antiga confirma a política nova.
            confirmador = self.motor.confirmador
            confirmador.observacoes = {k: v for k, v in confirmador.observacoes.items() if k[1] != "epi"}
            confirmador.alertados = {k: v for k, v in confirmador.alertados.items() if k[1] != "epi"}
            self.status.update(epi_obrigatorio=list(itens), confirmacao_segundos=segundos)

    def iniciar(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return False, "O monitoramento já está em execução ou parando."
            self.stop.clear()
            self.motor = MotorAlertas(self.confirmacao_epi, CONFIRMACAO_QUEDA, COOLDOWN)
            self.frame = self.frame_original = self.frame_instante = None
            self.status.update(executando=True, estado="iniciando", mensagem="Abrindo câmera e carregando modelos.",
                               deteccoes=[], epi_ativo=False, epi_erro=None, epis_suportados=[],
                               oculos_ativo=False, oculos_erro=None, aviso=None,
                               aviso_desempenho=None, processamento_segundos=0, fps=0)
            self.thread = threading.Thread(target=self.executar, daemon=True)
            self.thread.start()
        return True, "Inicialização solicitada."

    def parar(self):
        with self.lock:
            self.stop.set()
            if self.status["executando"]:
                self.status.update(estado="parando", mensagem="Encerrando o monitoramento.")
            else:
                self.status.update(estado="parado", mensagem="Monitoramento parado.")
        return True, "Solicitação para parar recebida."

    def snapshot(self):
        with self.lock:
            resultado = copy.deepcopy({**self.status, "eventos": list(self.eventos)})
            idade = time.monotonic() - self.frame_instante if self.frame_instante is not None else None
            resultado["imagem_disponivel"] = bool(self.frame)
            resultado["coleta_disponivel"] = bool(self.status["executando"] and idade is not None and idade <= 3)
            return resultado

    def _desativar_epi(self, mensagem):
        with self.lock:
            auxiliar_ativo = self.status["oculos_ativo"]
            self.status.update(epi_ativo=auxiliar_ativo, epi_erro=mensagem,
                               epis_suportados=["oculos"] if auxiliar_ativo else [])

    def processar_deteccoes(self, quadro, caixas, pontos, deteccoes_epi, agora=None,
                           processamento_segundos=None):
        """Ponto de integração testável, sem acessar câmera ou enviar e-mail."""
        agora = time.monotonic() if agora is None else agora
        with self.lock:
            suportados = set(self.status["epis_suportados"]) if self.status["epi_ativo"] else set()
            if processamento_segundos is not None:
                self.status["processamento_segundos"] = round(processamento_segundos, 2)
                self.status["aviso_desempenho"] = (
                    f"Processamento lento ({processamento_segundos:.1f} s/quadro). "
                    "A confirmação exige três observações e pode demorar mais; "
                    "intervalos acima de 10 s interrompem a confirmação."
                    if processamento_segundos > 2 else None
                )
            return self.motor.avaliar(
                caixas, pontos, deteccoes_epi, self.epi_obrigatorio, suportados, quadro.shape, agora,
                processamento_segundos=processamento_segundos,
            )

    def _publicar_frame(self, original, anotado, pessoas, fps):
        import cv2
        ok, buffer = cv2.imencode(".jpg", anotado, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return
        with self.lock:
            self.frame = buffer.tobytes()
            self.frame_original = original.copy()
            self.frame_instante = time.monotonic()
            self.status.update(deteccoes=pessoas, fps=round(fps, 1))

    def alerta(self, quadro, evento, agora):
        import cv2
        try:
            self.capturas.mkdir(parents=True, exist_ok=True)
            instante = datetime.now()
            arquivo = self.capturas / f"{evento['tipo']}_{instante:%Y%m%d_%H%M%S_%f}_{uuid4().hex[:6]}.jpg"
            if not cv2.imwrite(str(arquivo), quadro):
                raise OSError("Não foi possível salvar a imagem da ocorrência.")
            registro = {
                "data": instante.strftime("%d/%m/%Y %H:%M:%S"), "arquivo": arquivo.name,
                "motivo": evento["motivo"], "tipo": evento["tipo"],
                "pessoa_id": evento["pessoa_id"], "email": "aguardando envio",
            }
            with self.lock:
                self.eventos.appendleft(registro)
                self.motor.confirmador.marcar_alerta(evento["chaves"], agora)
            threading.Thread(target=self.email, args=(registro, arquivo), daemon=True).start()
        except OSError as erro:
            with self.lock:
                self.status["aviso"] = str(erro)

    def email(self, evento, arquivo):
        host, remetente, destino, senha = (
            os.getenv(chave) for chave in ("SMTP_HOST", "EMAIL_REMETENTE", "EMAIL_DESTINATARIO", "SMTP_SENHA")
        )
        if not all((host, remetente, destino, senha)):
            with self.lock:
                evento["email"] = "não configurado"
            return
        try:
            mensagem = EmailMessage()
            mensagem["Subject"] = "Alerta VigiaAI"
            mensagem["From"] = remetente
            mensagem["To"] = destino
            mensagem.set_content(f"{evento['motivo']}\nData: {evento['data']}\nImagem anexada.")
            mensagem.add_attachment(arquivo.read_bytes(), maintype="image", subtype="jpeg", filename=arquivo.name)
            with smtplib.SMTP_SSL(host, int(os.getenv("SMTP_PORTA", "465")),
                                  timeout=15, context=ssl.create_default_context()) as smtp:
                smtp.login(remetente, senha)
                smtp.send_message(mensagem)
            resultado = "enviado"
        except smtplib.SMTPAuthenticationError:
            resultado = "falhou: autenticação SMTP; confira a senha de app"
        except Exception as erro:
            resultado = f"falhou: {type(erro).__name__}"
        with self.lock:
            evento["email"] = resultado

    def coletar_amostra(self, observacao=""):
        import cv2
        if not isinstance(observacao, str) or len(observacao) > 300:
            raise ValueError("A observação deve ter no máximo 300 caracteres.")
        with self.lock:
            if not self.status["executando"] or self.frame_original is None or self.frame_instante is None:
                raise ValueError("Inicie a câmera e aguarde a primeira imagem.")
            if time.monotonic() - self.frame_instante > 3:
                raise ValueError("A imagem está desatualizada. Aguarde a câmera voltar a transmitir.")
            quadro = self.frame_original.copy()
            deteccoes = copy.deepcopy(self.status["deteccoes"])
        self.coleta.mkdir(parents=True, exist_ok=True)
        instante = datetime.now()
        nome = f"amostra_{instante:%Y%m%d_%H%M%S_%f}_{uuid4().hex[:6]}"
        arquivo = self.coleta / f"{nome}.jpg"
        if not cv2.imwrite(str(arquivo), quadro):
            raise OSError("Não foi possível salvar a amostra.")
        metadados = {
            "data": instante.isoformat(timespec="seconds"), "camera": CAMERA_INDEX,
            "imagem": arquivo.name, "largura": quadro.shape[1], "altura": quadro.shape[0],
            "observacao": observacao, "revisada": False,
            "deteccoes_apenas_referencia": deteccoes,
            "instrucao": "Revisar e anotar manualmente antes de incluir em treino, validação ou teste.",
        }
        arquivo.with_suffix(".json").write_text(json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"arquivo": arquivo.name, "url": f"/amostras/{arquivo.name}"}

    def listar_amostras(self):
        arquivos = sorted(self.coleta.glob("*.jpg"), reverse=True)
        return {
            "total": len(arquivos),
            "amostras": [{"arquivo": p.name, "url": f"/amostras/{p.name}"} for p in arquivos[:12]],
        }

    def executar(self):
        camera = None
        try:
            import cv2
            import mediapipe as mp
            from ultralytics import YOLO

            camera = abrir_camera(CAMERA_INDEX)
            if not camera.isOpened():
                raise RuntimeError(f"Não foi possível abrir a câmera {CAMERA_INDEX}.")
            modelo = YOLO(str(BASE / "yolov8n.pt"))
            modelo_epi = None
            modelo_oculos = None
            tentou_oculos = False
            suportados_principais = []
            if self.modelo_epi:
                try:
                    modelo_epi = YOLO(str(self.modelo_epi))
                    suportados_principais = sorted({item for nome in modelo_epi.names.values() if (item := identificar_epi(nome))})
                    if not suportados_principais:
                        raise ValueError("O modelo não contém classes de EPI reconhecidas.")
                    with self.lock:
                        self.status.update(epi_ativo=True, epis_suportados=suportados_principais)
                except Exception as erro:
                    modelo_epi = None
                    self._desativar_epi(f"Não foi possível carregar o detector de EPI ({type(erro).__name__}).")
            else:
                self._desativar_epi("Modelo de EPI não encontrado.")
            # Cada recorte é uma imagem independente; não mistura rastreamento de pose entre pessoas.
            with ExitStack() as recursos:
                pose = recursos.enter_context(mp.solutions.pose.Pose(
                    static_image_mode=True, model_complexity=1,
                    min_detection_confidence=0.5, min_tracking_confidence=0.5,
                ))
                try:
                    detector_rosto = recursos.enter_context(mp.solutions.face_detection.FaceDetection(
                        model_selection=0, min_detection_confidence=0.7
                    ))
                except Exception:
                    detector_rosto = None
                with self.lock:
                    if not self.stop.is_set():
                        self.status.update(estado="ativo", mensagem="Monitoramento ativo.")
                falhas = 0
                while not self.stop.is_set():
                    inicio = time.monotonic()
                    ok, quadro = camera.read()
                    if not ok:
                        falhas += 1
                        if falhas >= 5:
                            raise RuntimeError("A câmera não está fornecendo imagens. Confira conexão e aplicativos usando a câmera.")
                        self.stop.wait(0.2)
                        continue
                    falhas = 0
                    capturado_em = time.monotonic()
                    original = cv2.flip(quadro, 1)
                    caixas = []
                    pontos = []
                    with self.lock:
                        obrigatorios = list(self.epi_obrigatorio)
                    for resultado in modelo(original, classes=[0], conf=0.5, verbose=False):
                        for box in resultado.boxes.xyxy:
                            x1, y1, x2, y2 = map(int, box.tolist())
                            caixa = (max(0, x1), max(0, y1), min(original.shape[1], x2), min(original.shape[0], y2))
                            x1, y1, x2, y2 = caixa
                            if x2 <= x1 or y2 <= y1:
                                continue
                            caixas.append(caixa)
                            recorte = original[y1:y2, x1:x2]
                            rgb = cv2.cvtColor(recorte, cv2.COLOR_BGR2RGB)
                            recorte_pose = regiao_pose(caixa, original.shape)
                            px1, py1, px2, py2 = recorte_pose
                            rgb_pose = cv2.cvtColor(original[py1:py2, px1:px2], cv2.COLOR_BGR2RGB)
                            resultado_pose = pose.process(rgb_pose)
                            landmarks = (
                                mapear_pontos_pose(resultado_pose.pose_landmarks.landmark, recorte_pose, caixa)
                                if resultado_pose.pose_landmarks else {}
                            )
                            if "oculos" in obrigatorios:
                                faces = []
                                if detector_rosto is not None:
                                    try:
                                        resultado_rosto = detector_rosto.process(rgb)
                                        for face in resultado_rosto.detections or []:
                                            keypoints = face.location_data.relative_keypoints
                                            caixa_rosto = face.location_data.relative_bounding_box
                                            faces.append({
                                                "olho_direito": (keypoints[0].x, keypoints[0].y),
                                                "olho_esquerdo": (keypoints[1].x, keypoints[1].y),
                                                "nariz": (keypoints[2].x, keypoints[2].y),
                                                "confianca": float(face.score[0]),
                                                "caixa": (caixa_rosto.xmin, caixa_rosto.ymin,
                                                          caixa_rosto.xmin + caixa_rosto.width,
                                                          caixa_rosto.ymin + caixa_rosto.height),
                                            })
                                    except Exception:
                                        faces = []
                                landmarks = enriquecer_rosto(landmarks, faces)
                            pontos.append(landmarks)
                    deteccoes_epi = []
                    verificar = bool(obrigatorios)
                    if modelo_epi is not None and verificar:
                        try:
                            piso = 0.15 if "oculos" in obrigatorios else 0.5
                            deteccoes_epi.extend(extrair_deteccoes_epi(
                                modelo_epi(original, conf=piso, verbose=False), piso_oculos=piso
                            ))
                        except Exception as erro:
                            modelo_epi = None
                            self._desativar_epi(f"Detector de EPI interrompido ({type(erro).__name__}); quedas continuam ativas.")
                    if "oculos" in obrigatorios and not tentou_oculos:
                        tentou_oculos = True
                        if self.modelo_oculos and self.modelo_oculos != self.modelo_epi:
                            try:
                                modelo_oculos = YOLO(str(self.modelo_oculos))
                                if not any(identificar_epi(nome) == "oculos" for nome in modelo_oculos.names.values()):
                                    raise ValueError("O modelo auxiliar não contém a classe óculos.")
                            except Exception as erro:
                                modelo_oculos = None
                                with self.lock:
                                    self.status["oculos_erro"] = f"Verificação adicional indisponível ({type(erro).__name__})."
                    if modelo_oculos is not None and "oculos" in obrigatorios:
                        try:
                            classes = [indice for indice, nome in modelo_oculos.names.items() if identificar_epi(nome) == "oculos"]
                            deteccoes_epi.extend(extrair_deteccoes_epi(
                                modelo_oculos(original, classes=classes, conf=0.15, verbose=False), piso_oculos=0.15
                            ))
                        except Exception as erro:
                            modelo_oculos = None
                            with self.lock:
                                self.status["oculos_erro"] = f"Verificação adicional interrompida ({type(erro).__name__})."
                    with self.lock:
                        suportados = set(suportados_principais) if modelo_epi is not None else set()
                        if modelo_oculos is not None:
                            suportados.add("oculos")
                        self.status.update(epi_ativo=bool(suportados), epis_suportados=sorted(suportados),
                                           oculos_ativo=modelo_oculos is not None)
                    processamento = time.monotonic() - capturado_em
                    agora = capturado_em
                    pessoas, alertas = self.processar_deteccoes(
                        original, caixas, pontos, deteccoes_epi, agora,
                        processamento_segundos=processamento,
                    )
                    anotado = original.copy()
                    for pessoa in pessoas:
                        alerta = pessoa["queda_confirmada"] or pessoa["epi_faltando"]
                        cor = (50, 70, 230) if alerta else (70, 190, 100)
                        x1, y1, x2, y2 = pessoa["caixa"]
                        cv2.rectangle(anotado, (x1, y1), (x2, y2), cor, 2)
                        texto = f"Pessoa {pessoa['id']} | {pessoa['postura'] or 'Postura inconclusiva'}"
                        if pessoa["epi_faltando"]:
                            texto += " | Possivel ausencia: " + ", ".join(pessoa["epi_faltando"])
                        cv2.putText(anotado, texto, (x1, max(24, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, cor, 2)
                    self._publicar_frame(original, anotado, pessoas, 1 / max(time.monotonic() - inicio, 0.001))
                    for evento in alertas:
                        self.alerta(anotado, evento, agora)
        except Exception as erro:
            with self.lock:
                self.status.update(estado="erro", mensagem=f"Erro no monitoramento: {erro}")
        finally:
            if camera is not None:
                camera.release()
            with self.lock:
                self.status.update(executando=False, epi_ativo=False, oculos_ativo=False,
                                   aviso_desempenho=None, fps=0)
                if self.status["estado"] != "erro":
                    self.status.update(estado="parado", mensagem="Monitoramento parado.")


def criar_app(instancia=None):
    app = Flask(__name__)
    sistema = instancia if instancia is not None else Monitor()
    app.extensions["monitor"] = sistema

    def dados_json():
        dados = request.get_json(silent=True)
        if not isinstance(dados, dict):
            raise ValueError("Envie um objeto JSON válido.")
        return dados

    @app.get("/")
    def inicio():
        return render_template("index.html")

    @app.get("/status")
    def status():
        resposta = jsonify(sistema.snapshot())
        resposta.headers["Cache-Control"] = "no-store"
        return resposta

    @app.post("/configurar-epi")
    def configurar_epi():
        try:
            dados = dados_json()
            sistema.configurar_epi(dados.get("obrigatorios", []), dados.get("confirmacao_segundos"))
            return jsonify(ok=True, mensagem="Política de EPI salva.", obrigatorios=sistema.epi_obrigatorio)
        except ValueError as erro:
            return jsonify(ok=False, mensagem=str(erro)), 400
        except OSError:
            return jsonify(ok=False, mensagem="Não foi possível salvar a configuração."), 500

    @app.post("/start")
    def iniciar():
        ok, mensagem = sistema.iniciar()
        return jsonify(ok=ok, mensagem=mensagem), 200 if ok else 409

    @app.post("/stop")
    def parar():
        ok, mensagem = sistema.parar()
        return jsonify(ok=ok, mensagem=mensagem)

    @app.get("/capturas/<path:nome>")
    def captura(nome):
        return send_from_directory(sistema.capturas, nome)

    @app.get("/frame.jpg")
    def imagem():
        with sistema.lock:
            quadro = sistema.frame
        return Response(quadro, mimetype="image/jpeg", headers={"Cache-Control": "no-store"}) if quadro else Response(status=204)

    @app.get("/stream")
    def stream():
        def gerar():
            while True:
                with sistema.lock:
                    quadro = sistema.frame
                    executando = sistema.status["executando"]
                if quadro:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + quadro + b"\r\n"
                if not executando:
                    break
                time.sleep(0.1)
        return Response(gerar(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.get("/amostras")
    def amostras():
        return jsonify(sistema.listar_amostras())

    @app.post("/coletar-amostra")
    def coletar():
        try:
            dados = dados_json()
            amostra = sistema.coletar_amostra(dados.get("observacao", ""))
            return jsonify(ok=True, mensagem="Foto original salva para revisão e anotação.", **amostra), 201
        except ValueError as erro:
            return jsonify(ok=False, mensagem=str(erro)), 409
        except OSError:
            return jsonify(ok=False, mensagem="Não foi possível salvar a amostra."), 500

    @app.get("/amostras/<path:nome>")
    def amostra(nome):
        if Path(nome).suffix.lower() != ".jpg":
            return jsonify(mensagem="Imagem não encontrada."), 404
        return send_from_directory(sistema.coleta, nome)

    return app


app = criar_app()
monitor = app.extensions["monitor"]

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True, load_dotenv=False)
