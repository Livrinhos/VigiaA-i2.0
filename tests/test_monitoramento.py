import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from epi_monitoramento import ConfirmadorAlertas, MotorAlertas, RastreadorPessoas, enriquecer_rosto, identificar_epi
from main import Monitor, criar_app, extrair_deteccoes_epi

CAIXA = (100, 60, 300, 460)
TAMANHO = (720, 1280, 3)


def corpo_visivel():
    return {
        0: (0.5, 0.12, 1), 2: (0.4, 0.1, 1), 5: (0.6, 0.1, 1),
        11: (0.3, 0.3, 1), 12: (0.7, 0.3, 1),
        23: (0.35, 0.65, 1), 24: (0.65, 0.65, 1),
        15: (0.15, 0.6, 1), 16: (0.85, 0.6, 1),
        19: (0.15, 0.65, 1), 20: (0.85, 0.65, 1),
    }


class TestConfirmacao(unittest.TestCase):
    def test_precisa_tempo_e_varios_quadros(self):
        c = ConfirmadorAlertas()
        chave = (1, "epi", "capacete")
        self.assertFalse(c.observar(chave, True, 0, 3))
        self.assertFalse(c.observar(chave, True, 1.5, 3))
        self.assertTrue(c.observar(chave, True, 3, 3))

    def test_sumiço_e_inconclusivo_reiniciam_contagem(self):
        for sinal in (False, None):
            c = ConfirmadorAlertas()
            chave = (1, "epi", "capacete")
            c.observar(chave, True, 0, 3)
            c.observar(chave, True, 1.5, 3)
            c.observar(chave, sinal, 2, 3)
            self.assertFalse(c.observar(chave, True, 3.5, 3))
        c = ConfirmadorAlertas()
        c.observar(chave, True, 0, 3)
        self.assertFalse(c.observar(chave, True, 10, 3))

    def test_intervalo_independente_por_pessoa_item_e_queda(self):
        c = ConfirmadorAlertas(intervalo=60)
        chave = (1, "epi", "capacete")
        c.marcar_alerta([chave], 10)
        self.assertFalse(c.pode_alertar(chave, 11))
        self.assertTrue(c.pode_alertar((2, "epi", "capacete"), 11))
        self.assertTrue(c.pode_alertar((1, "epi", "colete"), 11))
        self.assertTrue(c.pode_alertar((1, "queda", ""), 11))
        self.assertTrue(c.pode_alertar(chave, 70))

    def test_rastreamento_ordem_e_expiracao(self):
        r = RastreadorPessoas()
        direita = (500, 60, 700, 460)
        self.assertEqual(r.atualizar([CAIXA, direita], 0), [1, 2])
        self.assertEqual(r.atualizar([direita, CAIXA], 1), [2, 1])
        self.assertEqual(r.atualizar([CAIXA], 5), [3])


class TestMotor(unittest.TestCase):
    def observar(self, motor, agora, pontos=None, epis=None, suportados=None, caixas=None):
        caixas = [CAIXA] if caixas is None else caixas
        return motor.avaliar(
            caixas, [corpo_visivel() for _ in caixas] if pontos is None else pontos,
            epis or [], ["capacete"], {"capacete"} if suportados is None else suportados,
            TAMANHO, agora,
        )

    def test_presenca_positiva_e_classes_negativas(self):
        self.assertIsNone(identificar_epi("NO-Hardhat"))
        self.assertIsNone(identificar_epi("without_helmet"))
        motor = MotorAlertas()
        capacete = [{"classe": "hardhat", "caixa": (150, 65, 250, 115)}]
        pessoas, alertas = self.observar(motor, 0, epis=capacete)
        self.assertEqual(pessoas[0]["epis"]["capacete"], "presente")
        self.assertFalse(alertas)

    def test_item_na_mao_nao_conta_como_capacete_vestido(self):
        motor = MotorAlertas()
        na_mao = [{"classe": "capacete", "caixa": (150, 300, 250, 340)}]
        for instante in (0, 1.5, 3):
            pessoas, alertas = self.observar(motor, instante, epis=na_mao)
        self.assertEqual(pessoas[0]["epis"]["capacete"], "inconclusivo")
        self.assertFalse(alertas)

    def test_modelo_ausente_regiao_oculta_e_classe_nao_suportada(self):
        for extras in ({"suportados": set()}, {"pontos": [{}]}):
            motor = MotorAlertas()
            for instante in (0, 1.5, 3, 4.5):
                pessoas, alertas = self.observar(motor, instante, **extras)
                self.assertFalse(alertas)
                self.assertEqual(pessoas[0]["epis"]["capacete"], "inconclusivo")

    def test_duas_pessoas_confirmam_sem_compartilhar_intervalo(self):
        motor = MotorAlertas()
        caixas = [CAIXA, (500, 60, 700, 460)]
        negativos = [{'classe': 'no_helmet', 'caixa': (150, 65, 250, 115)},
                     {'classe': 'no_helmet', 'caixa': (550, 65, 650, 115)}]
        for instante in (0, 1.5, 3):
            _, alertas = self.observar(motor, instante, caixas=caixas, epis=negativos)
        self.assertEqual({a["pessoa_id"] for a in alertas}, {1, 2})
        motor.confirmador.marcar_alerta(alertas[0]["chaves"], 3)
        _, seguintes = self.observar(motor, 4, caixas=caixas, epis=negativos)
        self.assertEqual(len(seguintes), 1)
        self.assertNotEqual(seguintes[0]["pessoa_id"], alertas[0]["pessoa_id"])

    def test_capacete_ambiguo_nao_regulariza_duas_pessoas(self):
        motor = MotorAlertas()
        caixas = [CAIXA, (120, 60, 320, 460)]
        epis = [{"classe": "capacete", "caixa": (180, 65, 240, 110)}]
        for instante in (0, 1.5, 3):
            pessoas, alertas = self.observar(motor, instante, caixas=caixas, epis=epis)
        self.assertFalse(alertas)
        self.assertTrue(all(p["epis"]["capacete"] == "inconclusivo" for p in pessoas))

    def test_perder_pessoa_interrompe_confirmacao(self):
        motor = MotorAlertas()
        self.observar(motor, 0)
        self.observar(motor, 1)
        self.observar(motor, 1.5, caixas=[])
        _, alertas = self.observar(motor, 2)
        self.assertFalse(alertas)

    def test_queda_tem_confirmacao_independente_de_epi(self):
        motor = MotorAlertas()
        deitada = corpo_visivel()
        deitada.update({11: (0.2, 0.4, 1), 12: (0.3, 0.4, 1),
                        23: (0.7, 0.45, 1), 24: (0.8, 0.45, 1)})
        for instante in range(6):
            _, alertas = self.observar(motor, instante, pontos=[deitada], suportados=set())
        self.assertEqual([a["tipo"] for a in alertas], ["queda"])


class TestOculos(unittest.TestCase):
    def avaliar(self, deteccoes=None, pontos=None, caixa=CAIXA):
        pontos = corpo_visivel() if pontos is None else pontos
        motor = MotorAlertas()
        for agora in (0, 1.5, 3):
            pessoas, alertas = motor.avaliar(
                [caixa], [pontos], deteccoes or [], ["oculos"], {"oculos"}, TAMANHO, agora
            )
        return pessoas[0], alertas

    def test_close_do_rosto_aceita_oculos_abaixo_dos_40_porcento(self):
        pontos = corpo_visivel()
        pontos.update({2: (0.35, 0.55, 1), 5: (0.65, 0.55, 1), 0: (0.5, 0.65, 1)})
        deteccao = {"classe": "oculos", "confianca": 0.8, "caixa": (130, 255, 270, 305)}
        pessoa, alertas = self.avaliar([deteccao], pontos)
        self.assertEqual(pessoa["epis"]["oculos"], "presente")
        self.assertFalse(alertas)

    def test_indicio_fraco_nao_comprova_presenca_nem_ausencia(self):
        deteccao = {"classe": "oculos", "confianca": 0.3, "caixa": (150, 85, 250, 120)}
        pessoa, alertas = self.avaliar([deteccao])
        self.assertEqual(pessoa["epis"]["oculos"], "inconclusivo")
        self.assertFalse(alertas)

    def test_sem_deteccao_e_olhos_visiveis_nao_prova_ausencia(self):
        pessoa, alertas = self.avaliar()
        self.assertEqual(pessoa["epis"]["oculos"], "inconclusivo")
        self.assertFalse(alertas)

    def test_oculos_na_mao_ou_na_testa_nao_contam_como_uso(self):
        for caixa in ((150, 300, 250, 350), (150, 61, 250, 72)):
            pessoa, _ = self.avaliar([{"classe": "oculos", "confianca": 0.9, "caixa": caixa}])
            self.assertNotEqual(pessoa["epis"]["oculos"], "presente")

    def test_perfil_ou_mais_de_um_rosto_ficam_inconclusivos(self):
        perfil = corpo_visivel()
        perfil[0] = (0.9, 0.2, 1)
        for pontos in (perfil, enriquecer_rosto(corpo_visivel(), []),
                       enriquecer_rosto(corpo_visivel(), [{}, {}])):
            pessoa, alertas = self.avaliar(pontos=pontos)
            self.assertEqual(pessoa["epis"]["oculos"], "inconclusivo")
            self.assertFalse(alertas)

    def test_tronco_cortado_nao_invalida_olhos_inteiros(self):
        caixa = (100, 60, 300, 720)
        pessoa, _ = self.avaliar([{'classe': 'no_goggle', 'caixa': (150, 110, 250, 145)}], pontos=corpo_visivel(), caixa=caixa)
        self.assertEqual(pessoa["epis"]["oculos"], "possivel_ausencia")

    def test_rosto_cortado_nao_confirma_ausencia_com_olhos_estimados(self):
        pontos = corpo_visivel()
        pontos["_rosto_caixa"] = (0.1, 0.01, 0.9, 1.2)
        pessoa, alertas = self.avaliar(pontos=pontos)
        self.assertEqual(pessoa["epis"]["oculos"], "inconclusivo")
        self.assertFalse(alertas)

    def test_piso_reduzido_so_gera_indicios_de_oculos(self):
        resultado = SimpleNamespace(
            names={0: "capacete", 1: "oculos"},
            boxes=SimpleNamespace(
                xyxy=np.array([[1, 2, 3, 4]] * 3),
                cls=np.array([0, 1, 0]), conf=np.array([0.3, 0.3, 0.8])
            ),
        )
        deteccoes = extrair_deteccoes_epi([resultado], piso_oculos=0.15)
        self.assertEqual([d["classe"] for d in deteccoes], ["oculos", "capacete"])
        self.assertEqual(deteccoes[0]["confianca"], 0.3)


class TestPainel(unittest.TestCase):
    def setUp(self):
        self.temporario = tempfile.TemporaryDirectory()
        self.base = Path(self.temporario.name)
        self.monitor = Monitor(base=self.base, modelo_epi=None)
        self.app = criar_app(self.monitor)
        self.cliente = self.app.test_client()

    def tearDown(self):
        self.monitor.stop.set()
        if self.monitor.thread:
            self.monitor.thread.join(timeout=3)
        self.temporario.cleanup()

    def test_pagina_e_js_estaticos(self):
        html = self.cliente.get("/legado")
        self.assertEqual(html.status_code, 200)
        self.assertIn(b"painel.js", html.data)
        self.assertNotIn(b'src="/stream"', html.data)
        with self.cliente.get("/static/painel.js") as script:
            self.assertEqual(script.status_code, 200)
        self.assertEqual(self.cliente.get("/frame.jpg").status_code, 204)
        self.assertEqual(self.cliente.get("/stream").data, b"")

    def test_salva_politica_e_valida_entrada(self):
        for corpo in ([], {"obrigatorios": "capacete"}, {"obrigatorios": ["invalido"]},
                      {"obrigatorios": [], "confirmacao_segundos": 0}):
            self.assertEqual(self.cliente.post("/configurar-epi", json=corpo).status_code, 400)
        resposta = self.cliente.post("/configurar-epi", json={"obrigatorios": ["capacete"], "confirmacao_segundos": 4})
        self.assertEqual(resposta.status_code, 200)
        restaurado = Monitor(base=self.base, modelo_epi=None)
        self.assertEqual(restaurado.epi_obrigatorio, ["capacete"])
        self.assertEqual(restaurado.confirmacao_epi, 4)

    def test_troca_de_politica_apaga_confirmacao_anterior(self):
        self.monitor.motor.confirmador.observar((1, "epi", "capacete"), True, 0, 3)
        self.monitor.configurar_epi(["colete"])
        self.assertFalse(self.monitor.motor.confirmador.observacoes)

    def test_iniciar_duplicado_e_parar_sem_camera_real(self):
        pronto = __import__("threading").Event()
        def executar_fake():
            pronto.set()
            self.monitor.stop.wait(2)
            with self.monitor.lock:
                self.monitor.status.update(executando=False, estado="parado")
        with patch.object(self.monitor, "executar", side_effect=executar_fake):
            self.assertEqual(self.cliente.post("/start").status_code, 200)
            self.assertTrue(pronto.wait(1))
            self.assertEqual(self.cliente.post("/start").status_code, 409)
            self.assertEqual(self.cliente.post("/stop").status_code, 200)

    def test_coleta_original_com_metadados_sem_email_ou_treino(self):
        self.assertEqual(self.cliente.post("/coletar-amostra", json={}).status_code, 409)
        original = np.full((80, 120, 3), (40, 100, 160), dtype=np.uint8)
        anotado = original.copy()
        cv2.rectangle(anotado, (0, 0), (119, 79), (0, 0, 255), 20)
        self.monitor.status["executando"] = True
        self.monitor._publicar_frame(original, anotado, [], 10)
        with patch.object(self.monitor, "email") as email:
            resposta = self.cliente.post("/coletar-amostra", json={"observacao": "Sem capacete; luz lateral"} )
            self.assertEqual(resposta.status_code, 201)
            email.assert_not_called()
        arquivo = self.monitor.coleta / resposta.json["arquivo"]
        imagem = cv2.imread(str(arquivo))
        self.assertLess(float(np.abs(imagem.astype(float) - original).mean()), 3)
        metadados = json.loads(arquivo.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertFalse(metadados["revisada"])
        self.assertEqual(metadados["observacao"], "Sem capacete; luz lateral")
        with self.cliente.get(resposta.json["url"]) as imagem_salva:
            self.assertEqual(imagem_salva.status_code, 200)
        self.assertEqual(self.cliente.get("/amostras").json["total"], 1)
        self.assertEqual(self.cliente.get("/amostras/../main.py").status_code, 404)
        self.assertEqual(self.cliente.get("/amostras/" + arquivo.with_suffix(".json").name).status_code, 404)
        self.monitor.frame_instante = time.monotonic() - 10
        self.assertEqual(self.cliente.post("/coletar-amostra", json={}).status_code, 409)

    def test_indisponibilidade_epi_continua_inconclusiva(self):
        self.monitor.epi_obrigatorio = ["capacete"]
        self.monitor._desativar_epi("modelo inválido")
        for agora in (0, 1.5, 3):
            pessoas, alertas = self.monitor.processar_deteccoes(
                np.zeros(TAMANHO, dtype=np.uint8), [CAIXA], [corpo_visivel()], [], agora
            )
            self.assertFalse(alertas)
            self.assertEqual(pessoas[0]["epis"]["capacete"], "inconclusivo")

    def test_cooldown_so_e_marcado_se_a_imagem_for_salva(self):
        evento = {"tipo": "epi", "pessoa_id": 1, "chaves": [(1, "epi", "capacete")], "motivo": "teste"}
        with patch("main.salvar_jpeg", side_effect=OSError('Disco indisponível')):
            self.monitor.alerta(np.zeros((20, 20, 3), dtype=np.uint8), evento, 1)
        self.assertFalse(self.monitor.eventos)
        self.assertTrue(self.monitor.motor.confirmador.pode_alertar(evento["chaves"][0], 2))

    def test_falha_de_carga_ou_inferencia_epi_nao_interrompe_video(self):
        for falha_carga in (True, False):
            monitor = Monitor(base=self.base, modelo_epi=self.base / "modelo_epi_teste.pt")
            monitor.epi_obrigatorio = ["capacete"]
            monitor.status.update(executando=True, estado="iniciando")
            original = np.full(TAMANHO, 60, dtype=np.uint8)

            class CameraFake:
                leituras = 0
                liberada = False

                def isOpened(self):
                    return True

                def read(self):
                    self.leituras += 1
                    if self.leituras <= 2:
                        return True, original.copy()
                    monitor.stop.set()
                    return False, None

                def release(self):
                    self.liberada = True

            class PoseFake:
                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    pass

                def process(self, _):
                    return SimpleNamespace(pose_landmarks=None)

            class ModeloFake:
                def __init__(self, epi=False):
                    self.epi = epi
                    self.names = {0: "capacete"}

                def __call__(self, *_args, **_kwargs):
                    if self.epi:
                        raise RuntimeError("falha simulada de inferência")
                    return [SimpleNamespace(boxes=SimpleNamespace(xyxy=np.array([CAIXA])))]

            def carregar_modelo(caminho):
                if Path(caminho).name == "modelo_epi_teste.pt":
                    if falha_carga:
                        raise RuntimeError("falha simulada de carga")
                    return ModeloFake(epi=True)
                return ModeloFake()

            camera = CameraFake()
            mp_fake = SimpleNamespace(solutions=SimpleNamespace(pose=SimpleNamespace(Pose=lambda **_: PoseFake())))
            with patch('runtime_ia.opcoes_inferencia', return_value={'device': 'cpu', 'half': False, 'imgsz': 640}), patch("main.abrir_camera", return_value=camera), patch.dict(
                "sys.modules", {"mediapipe": mp_fake, "ultralytics": SimpleNamespace(YOLO=carregar_modelo)}
            ), patch.object(monitor, "email") as email:
                monitor.executar()
                email.assert_not_called()
            self.assertTrue(camera.liberada)
            self.assertIsNotNone(monitor.frame)
            self.assertFalse(monitor.status["executando"])
            self.assertEqual(monitor.status["estado"], "parado")
            self.assertIsNotNone(monitor.status["epi_erro"])
            self.assertEqual(monitor.status["deteccoes"][0]["epis"]["capacete"], "inconclusivo")

    def test_email_com_smtp_simulado_e_tempo_limite(self):
        arquivo = self.base / "evento.jpg"
        arquivo.write_bytes(b"imagem de teste")
        evento = {"motivo": "Pessoa 1: possível ausência de capacete.", "data": "19/10/2026 10:00:00"}
        ambiente = {"SMTP_HOST": "smtp.example.test", "SMTP_PORTA": "465",
                    "EMAIL_REMETENTE": "origem@example.test", "EMAIL_DESTINATARIO": "destino@example.test",
                    "SMTP_SENHA": "segredo-apenas-para-teste"}
        with patch.dict("os.environ", ambiente), patch("main.smtplib.SMTP_SSL") as smtp:
            self.monitor.email(evento, arquivo)
            self.assertEqual(evento["email"], "enviado")
            self.assertEqual(smtp.call_args.kwargs["timeout"], 15)
            smtp.return_value.__enter__.return_value.send_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()
