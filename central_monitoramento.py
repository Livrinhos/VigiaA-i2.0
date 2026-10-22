"""Fontes e controles web em torno do Monitor existente; sem outra IA."""

import math
import os
import re
import hashlib
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from uuid import uuid4

from flask import Response, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from epi_monitoramento import MotorAlertas

EXTENSOES = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
TOKEN = re.compile(r'^[a-f0-9]{32}$')


class Ocupado(ValueError):
    pass


def inspecionar_video(caminho):
    import cv2
    cap = cv2.VideoCapture(str(caminho))
    try:
        fps, total = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
        w, h = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        if not cap.isOpened() or not all(math.isfinite(v) and v > 0 for v in (fps, total, w, h)):
            raise ValueError('Vídeo ilegível ou codec não disponível neste computador.')
        if fps > 240 or w * h > 4096 * 2160 or total / fps > float(os.getenv('VIGIAAI_MAX_VIDEO_SEGUNDOS', '14400')):
            raise ValueError('Vídeo excede os limites de resolução, FPS ou duração configurados.')
        ok, quadro = cap.read()
        if not ok or quadro is None:
            raise ValueError('Não foi possível decodificar o primeiro quadro do vídeo.')
        altura, largura = quadro.shape[:2]
        if largura > 1280:
            quadro = cv2.resize(quadro, (1280, round(altura * 1280 / largura)))
        ok, jpeg = cv2.imencode('.jpg', quadro)
        if not ok:
            raise ValueError('Não foi possível criar a prévia do vídeo.')
        return dict(fps_original=round(fps, 5), total_quadros=int(total),
                    duracao_segundos=total / fps, largura=int(w), altura=int(h)), jpeg.tobytes()
    finally:
        cap.release()


class CentralMonitoramento:
    def __init__(self, sistema, abrir_camera, limite_bytes):
        self.sistema, self.abrir_camera = sistema, abrir_camera
        self.limite_bytes = limite_bytes
        identificador = hashlib.sha256(str(sistema.base.resolve()).encode()).hexdigest()[:12]
        raiz_media = Path(os.getenv('VIGIAAI_MEDIA_DIR', str(Path(tempfile.gettempdir()) / 'VigiaAI-2.1')))
        self.media = raiz_media / identificador / 'uploads'
        self.biblioteca = sistema.base / 'biblioteca_demo'
        self.acoes = threading.RLock()
        self.uploads = threading.Lock()
        self.condicao = threading.Condition(sistema.lock)
        self.fonte = None
        self.previa = None
        self.pausado = False
        self.busca = None
        self.passo = False
        self.limpar_ao_finalizar = False
        self.ultimo_tick = None
        self.revisao = 0
        self.segmento = 0
        self.quadros_processados = 0
        self.posicao = 0
        self.tempo_ia = 0
        self.houve_busca = False
        self.deteccoes_epi = []
        self.cameras = {}
        sistema.eventos = deque(sistema.eventos, maxlen=200)
        self.total_ocorrencias = len(sistema.eventos)
        sistema.controle = self
        self.limpar_expirados()

    def _ativo(self):
        return bool(self.sistema.thread and self.sistema.thread.is_alive())

    def _exigir_inativo(self):
        if self._ativo():
            raise Ocupado('Encerre a análise atual antes de trocar a fonte.')

    def _apagar_upload(self, fonte):
        if not fonte or fonte.get('origem') != 'upload':
            return
        p = fonte['caminho']
        if p.parent.resolve() == self.media.resolve() and TOKEN.fullmatch(p.stem) and not p.is_symlink():
            p.unlink(missing_ok=True)

    def limpar_expirados(self):
        limite = time.time() - max(60, int(os.getenv('VIGIAAI_UPLOAD_TTL_SEGUNDOS', '86400')))
        atual = self.fonte.get('caminho') if self.fonte else None
        for p in self.media.glob('*'):
            if (p != atual and p.is_file() and not p.is_symlink() and TOKEN.fullmatch(p.stem)
                    and p.suffix in EXTENSOES and p.stat().st_mtime < limite):
                p.unlink(missing_ok=True)

    def _instalar(self, fonte, previa=None):
        with self.condicao:
            anterior = self.fonte
            self.fonte, self.previa = fonte, previa
            self.sistema.fonte_video = fonte.get('caminho') if fonte['modo'] == 'video' else None
            if fonte['modo'] == 'camera':
                self.sistema.camera_indice = fonte['indice']
                self.sistema.status['camera'] = fonte['indice']
            self.sistema.frame = self.sistema.frame_original = None
            self.sistema.frame_instante = None
            self.sistema.status.update(estado='pronto', mensagem='Fonte pronta. Inicie a análise.', deteccoes=[], fps=0)
            self.pausado, self.busca = False, None
            self.posicao = self.quadros_processados = self.tempo_ia = 0
            self.houve_busca = False
            self.deteccoes_epi = []
            self.revisao += 1
        if anterior and anterior.get('caminho') != fonte.get('caminho'):
            self._apagar_upload(anterior)

    def enviar_video(self, arquivo):
        with self.acoes:
            self._exigir_inativo()
            if arquivo is None or not arquivo.filename:
                raise ValueError('Selecione um arquivo de vídeo.')
            nome = arquivo.filename.replace('\\', '/').rsplit('/', 1)[-1][:160]
            extensao = Path(nome).suffix.lower()
            if extensao not in EXTENSOES:
                raise ValueError('Use MP4, AVI, MOV, MKV ou WebM com codec disponível no backend.')
            self.media.mkdir(parents=True, exist_ok=True)
            self.limpar_expirados()
            token = uuid4().hex
            destino = self.media / (token + extensao)
            try:
                tamanho = 0
                with destino.open('xb') as saida:
                    while bloco := arquivo.stream.read(1024 * 1024):
                        tamanho += len(bloco)
                        if tamanho > self.limite_bytes:
                            raise RequestEntityTooLarge()
                        saida.write(bloco)
                if not tamanho:
                    raise ValueError('O arquivo enviado está vazio.')
                info, previa = inspecionar_video(destino)
                fonte = dict(id=token, modo='video', origem='upload', nome=nome,
                             caminho=destino, tamanho_bytes=tamanho, **info)
                self._instalar(fonte, previa)
                return self.fonte_publica()
            except Exception:
                destino.unlink(missing_ok=True)
                raise

    def fonte_publica(self):
        return {k: v for k, v in self.fonte.items() if k != 'caminho'} if self.fonte else None

    def listar_biblioteca(self):
        import json
        manifesto = self.biblioteca / 'biblioteca.json'
        if not manifesto.is_file():
            return []
        if manifesto.stat().st_size > 128 * 1024:
            raise ValueError('Manifesto da biblioteca é grande demais.')
        dados = json.loads(manifesto.read_text(encoding='utf-8-sig'))
        if not isinstance(dados, list):
            raise ValueError('A biblioteca deve conter uma lista de vídeos.')
        itens = []
        for item in dados[:50]:
            if not isinstance(item, dict) or item.get('autorizado') is not True or not item.get('licenca'):
                continue
            nome = str(item.get('arquivo', ''))
            p = (self.biblioteca / nome).resolve()
            if (not p.is_relative_to(self.biblioteca.resolve()) or not p.is_file()
                    or p.suffix.lower() not in EXTENSOES):
                continue
            chave = str(item.get('id', ''))
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,60}', chave):
                continue
            itens.append(dict(id=chave, titulo=str(item.get('titulo', p.stem))[:120],
                              descricao=str(item.get('descricao', ''))[:300], arquivo=nome))
        return itens

    def selecionar_biblioteca(self, chave):
        with self.acoes:
            self._exigir_inativo()
            item = next((v for v in self.listar_biblioteca() if v['id'] == chave), None)
            if item is None:
                raise ValueError('Vídeo autorizado não encontrado na biblioteca.')
            p = (self.biblioteca / item['arquivo']).resolve()
            info, previa = inspecionar_video(p)
            self._instalar(dict(id='biblioteca-' + chave, modo='video', origem='biblioteca',
                                nome=item['titulo'], caminho=p, tamanho_bytes=p.stat().st_size, **info), previa)

    def detectar_cameras(self):
        import cv2
        with self.acoes:
            self._exigir_inativo()
            cameras = {}
            for indice in range(max(1, min(8, int(os.getenv('VIGIAAI_MAX_CAMERAS', '3'))))):
                cap = self.abrir_camera(indice)
                try:
                    ok, quadro = cap.read() if cap.isOpened() else (False, None)
                    if ok and quadro is not None:
                        cameras[indice] = dict(indice=indice, nome=f'Câmera {indice}',
                                              largura=quadro.shape[1], altura=quadro.shape[0])
                finally:
                    cap.release()
            self.cameras = cameras
            return list(cameras.values())

    def selecionar_camera(self, indice):
        with self.acoes:
            self._exigir_inativo()
            if isinstance(indice, bool) or not isinstance(indice, int) or indice not in self.cameras:
                raise ValueError('Selecione uma câmera acessível encontrada na busca.')
            self._instalar(dict(id=f'camera-{indice}', modo='camera', nome=f'Câmera {indice}', indice=indice))

    def iniciar(self):
        with self.acoes, self.condicao:
            if not self.fonte:
                raise ValueError('Escolha um vídeo ou uma câmera antes de iniciar.')
            if self._ativo():
                if self.pausado:
                    self.pausado = False
                    self.ultimo_tick = None
                    self.sistema.status.update(estado='ativo', mensagem='Análise retomada.')
                    self.condicao.notify_all()
                    return
                raise Ocupado('A análise já está em execução.')
            self.pausado, self.busca, self.passo = False, None, False
            self.posicao = self.quadros_processados = self.tempo_ia = 0
            self.houve_busca = False
            self.ultimo_tick = None
            self.segmento += 1
            self.sistema.iniciar(demonstracao=True)

    def iniciar_legado(self):
        # A tela antiga participa da mesma exclusão de fontes que uploads e câmeras da central.
        with self.acoes:
            if self._ativo():
                return False, 'O monitoramento já está em execução ou parando.'
            indice = self.sistema.camera_indice
            self._instalar(dict(id=f'camera-{indice}', modo='camera', nome=f'Câmera {indice}', indice=indice))
            return self.sistema.iniciar()

    def pausar(self):
        with self.condicao:
            if not self._ativo() or not self.fonte or self.fonte['modo'] != 'video':
                raise ValueError('Pausa disponível durante a análise de vídeo.')
            self.pausado = True
            self.sistema.status.update(estado='pausado', mensagem='Análise pausada. O tempo do vídeo está congelado.')
            self.condicao.notify_all()

    def buscar(self, segundos, reiniciar=False):
        if isinstance(segundos, bool) or not isinstance(segundos, (int, float)) or not math.isfinite(segundos):
            raise ValueError('Informe um instante válido do vídeo.')
        with self.acoes, self.condicao:
            if not self.fonte or self.fonte['modo'] != 'video':
                raise ValueError('Escolha um vídeo antes de navegar na linha do tempo.')
            if not 0 <= segundos < self.fonte['duracao_segundos']:
                raise ValueError('Instante fora da duração do vídeo.')
            if not self._ativo():
                self.iniciar()
            self.busca = segundos
            self.pausado = not reiniciar
            self.passo = True
            self.sistema.status.update(estado='reposicionando', mensagem='Posicionando vídeo e reiniciando o histórico temporal.')
            self.condicao.notify_all()

    def encerrar(self):
        with self.acoes:
            with self.condicao:
                self.limpar_ao_finalizar = True
                self.sistema.parar()
                self.condicao.notify_all()
            if self.sistema.thread:
                self.sistema.thread.join(timeout=5)
            if self._ativo():
                raise Ocupado('Encerramento solicitado; aguarde a liberação da fonte.')
            self._limpar_fonte()

    def _limpar_fonte(self):
        with self.condicao:
            self._apagar_upload(self.fonte)
            self.fonte = self.previa = None
            self.sistema.fonte_video = None
            self.sistema.frame = self.sistema.frame_original = None
            self.sistema.frame_instante = None
            self.sistema.status.update(estado='parado', mensagem='Análise encerrada. Arquivo temporário removido.', deteccoes=[])
            self.pausado = self.limpar_ao_finalizar = False
            self.posicao = 0
            self.revisao += 1

    def antes_quadro(self, cap, indice, fps):
        import cv2
        with self.condicao:
            while not self.sistema.stop.is_set():
                if self.busca is not None:
                    alvo = int(self.busca * fps)
                    if not cap.set(cv2.CAP_PROP_POS_FRAMES, alvo):
                        raise ValueError('Este codec não permite navegar até o trecho solicitado.')
                    indice = alvo
                    self.houve_busca = alvo != 0
                    self.busca = None
                    motor = self.sistema.motor
                    self.sistema.motor = MotorAlertas(self.sistema.confirmacao_epi, motor.confirmacao_queda,
                                                     motor.confirmador.intervalo, chao_y=motor.chao_y)
                    self.sistema.status['deteccoes'] = []
                    self.deteccoes_epi = []
                    self.segmento += 1
                    self.ultimo_tick = None
                if self.pausado and not self.passo:
                    self.condicao.wait(.2)
                    continue
                if fps and self.ultimo_tick is not None:
                    restante = 1 / fps - (time.monotonic() - self.ultimo_tick)
                    if restante > 0:
                        self.condicao.wait(min(restante, .1))
                        continue
                self.passo = False
                self.ultimo_tick = time.monotonic()
                return indice
            return indice

    def apos_quadro(self, pessoas, epis, agora, processamento, indice):
        with self.condicao:
            self.quadros_processados += 1
            self.posicao = indice
            self.tempo_ia += processamento
            self.deteccoes_epi = epis
            self.revisao += 1
            self.sistema.status.update(estado='pausado' if self.pausado else 'ativo',
                                       mensagem='Análise pausada.' if self.pausado else 'Modelos reais em execução.')

    def finalizar(self, fim_video, indice):
        with self.condicao:
            if self.limpar_ao_finalizar:
                self._limpar_fonte()
            elif fim_video and self.sistema.status['estado'] != 'erro':
                total = self.fonte.get('total_quadros', 0) if self.fonte else 0
                if total and indice + 1 < total:
                    self.sistema.status.update(estado='erro', mensagem='A leitura terminou antes do final declarado. Verifique a integridade e o codec do vídeo.')
                else:
                    mensagem = ('Fim do vídeo atingido. Os trechos pulados pela busca não foram analisados.' if self.houve_busca
                                else 'Análise do vídeo concluída. Consulte as ocorrências ou reinicie.')
                    self.sistema.status.update(estado='concluido', mensagem=mensagem)
                self.posicao = indice
            self.condicao.notify_all()

    def aceitar_evento(self, registro, evento, agora):
        fonte = self.fonte_publica()
        fonte_id = fonte['id'] if fonte else 'camera-legado'
        tempo_video = agora if fonte and fonte['modo'] == 'video' else None
        if tempo_video is not None:
            for antigo in self.sistema.eventos:
                if (antigo.get('fonte_id') == fonte_id and antigo.get('tipo') == registro['tipo']
                        and antigo.get('classificacao') == registro['classificacao']
                        and antigo.get('pessoa_id') == registro['pessoa_id']
                        and set(antigo.get('epis', [])) == set(registro.get('epis', []))
                        and abs(antigo.get('tempo_video', -100) - tempo_video) <= 3):
                    return False
        registro.update(id=uuid4().hex, fonte_id=fonte_id, fonte_nome=fonte['nome'] if fonte else 'Câmera',
                        modo=fonte['modo'] if fonte else 'camera', tempo_video=tempo_video, segmento=self.segmento)
        self.total_ocorrencias += 1
        return True

    def snapshot(self):
        with self.sistema.lock:
            s = self.sistema.snapshot()
            pessoas = s['deteccoes']
            estados = [estado for p in pessoas for estado in p['epis'].values()]
            total = self.fonte.get('total_quadros', 0) if self.fonte else 0
            fps = self.fonte.get('fps_original', 0) if self.fonte else 0
            s.update(fonte=self.fonte_publica(), pausado=self.pausado, revisao_frame=self.revisao,
                     politica_configurada=self.sistema.config.is_file(),
                     imagem_disponivel=bool(self.sistema.frame or self.previa), segmento=self.segmento,
                     quadro_analisado=bool(self.sistema.frame),
                     houve_busca=self.houve_busca,
                     tempo_video=max(0, (self.posicao - 1) / fps) if fps else None,
                     progresso=min(1, self.posicao / total) if total else None,
                     quadros_processados=self.quadros_processados, tempo_ia_segundos=round(self.tempo_ia, 3),
                     deteccoes_epi=self.deteccoes_epi,
                     notificacoes_reais=bool(self._ativo() and not self.sistema.demonstracao and os.getenv('NOTIFICACOES_ATIVAS', '1') == '1'),
                     limite_upload_bytes=self.limite_bytes,
                     indicadores=dict(pessoas=len(pessoas), epis=estados.count('presente'),
                                      inconclusivos=estados.count('inconclusivo'), ausencias=estados.count('possivel_ausencia'),
                                      emergencias=sum(bool(p.get('emergencia')) for p in pessoas), ocorrencias=self.total_ocorrencias))
            return s


def registrar_central(app, sistema, abrir_camera):
    limite = max(1, int(os.getenv('VIGIAAI_UPLOAD_MAX_MB', '512'))) * 1024 * 1024
    central = CentralMonitoramento(sistema, abrir_camera, limite)
    app.extensions['central'] = central
    app.config['MAX_CONTENT_LENGTH'] = limite
    app.config['TRUSTED_HOSTS'] = ['localhost', '127.0.0.1', '[::1]']

    @app.after_request
    def proteger_respostas(resposta):
        resposta.headers['X-Content-Type-Options'] = 'nosniff'
        resposta.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        return resposta

    @app.before_request
    def proteger_mutacoes():
        if request.method != 'GET':
            if ((request.path.startswith('/api/central/') and request.headers.get('X-VigiaAI') != '1')
                    or request.headers.get('Sec-Fetch-Site') == 'cross-site'):
                return jsonify(ok=False, mensagem='Requisição local inválida.'), 403
            origem = request.headers.get('Origin')
            if origem and origem.rstrip('/') != request.host_url.rstrip('/'):
                return jsonify(ok=False, mensagem='Origem não permitida.'), 403

    @app.errorhandler(RequestEntityTooLarge)
    def upload_grande(_erro):
        return jsonify(ok=False, mensagem=f'Arquivo excede o limite de {limite // (1024 * 1024)} MB.'), 413

    def executar(funcao):
        try:
            resultado = funcao()
            return jsonify(ok=True, resultado=resultado)
        except Ocupado as erro:
            return jsonify(ok=False, mensagem=str(erro)), 409
        except (ValueError, TypeError) as erro:
            return jsonify(ok=False, mensagem=str(erro)), 400
        except OSError:
            return jsonify(ok=False, mensagem='Falha ao ler ou gravar o arquivo local.'), 500

    def dados():
        d = request.get_json(silent=True)
        if not isinstance(d, dict):
            raise ValueError('Envie um objeto JSON válido.')
        return d

    @app.get('/api/central/estado')
    def estado():
        return jsonify(central.snapshot()), 200, {'Cache-Control': 'no-store'}

    @app.get('/api/central/quadro.jpg')
    def quadro():
        with sistema.lock:
            jpeg = sistema.frame or central.previa
            versao = str(central.revisao)
        if not jpeg:
            return Response(status=204)
        if request.headers.get('If-None-Match') == versao:
            return Response(status=304)
        return Response(jpeg, mimetype='image/jpeg', headers={'Cache-Control': 'no-store', 'ETag': versao})

    @app.post('/api/central/videos')
    def video():
        if not central.uploads.acquire(blocking=False):
            return jsonify(ok=False, mensagem='Já existe um upload em andamento.'), 409
        try:
            return executar(lambda: central.enviar_video(request.files.get('video')))
        finally:
            central.uploads.release()

    @app.post('/api/central/cameras/buscar')
    def cameras():
        return executar(central.detectar_cameras)

    @app.post('/api/central/camera')
    def camera():
        return executar(lambda: central.selecionar_camera(dados().get('indice')))

    @app.get('/api/central/biblioteca')
    def biblioteca():
        return executar(lambda: [{k: v for k, v in item.items() if k != 'arquivo'} for item in central.listar_biblioteca()])

    @app.post('/api/central/biblioteca/selecionar')
    def selecionar():
        return executar(lambda: central.selecionar_biblioteca(dados().get('id')))

    @app.post('/api/central/acao/<acao>')
    def controle(acao):
        funcoes = dict(iniciar=central.iniciar, pausar=central.pausar, retomar=central.iniciar,
                       reiniciar=lambda: central.buscar(0, reiniciar=True), encerrar=central.encerrar,
                       buscar=lambda: central.buscar(dados().get('segundos')))
        if acao not in funcoes:
            return jsonify(ok=False, mensagem='Ação desconhecida.'), 404
        return executar(funcoes[acao])
