import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from main import Monitor, criar_app
from avaliar_video import MonitorVideo

H = {'X-VigiaAI': '1'}


def video_teste(pasta, quadros=40, fps=20):
    arquivo = Path(pasta) / 'teste.avi'
    writer = cv2.VideoWriter(str(arquivo), cv2.VideoWriter_fourcc(*'MJPG'), fps, (640, 480))
    if not writer.isOpened():
        raise RuntimeError('Codec MJPG indisponível no ambiente de teste.')
    q = np.zeros((480, 640, 3), np.uint8)
    q[:] = np.linspace(50, 200, 640, dtype=np.uint8)[None, :, None]
    for _ in range(quadros):
        writer.write(q)
    writer.release()
    return arquivo.read_bytes()


def aguardar(condicao, limite=6):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if condicao():
            return
        time.sleep(.01)
    raise AssertionError('A condição de processamento não foi atingida no prazo.')


class Contexto:
    def __enter__(self): return self
    def __exit__(self, *_): pass


class PoseTeste(Contexto):
    def process(self, imagem):
        pontos = [SimpleNamespace(x=0, y=0, visibility=0) for _ in range(33)]
        # O recorte expandido é 260x520, com origem (70,0), para caixa (100,50,300,450).
        for i, (x, y) in {0:(200,98), 2:(180,90), 5:(220,90), 11:(180,150), 12:(220,150), 23:(180,310), 24:(220,310)}.items():
            pontos[i] = SimpleNamespace(x=(x-70)/260, y=y/480, visibility=1)
        return SimpleNamespace(pose_landmarks=SimpleNamespace(landmark=pontos))


class FaceTeste(Contexto):
    def process(self, _imagem):
        pontos = [SimpleNamespace(x=x, y=y) for x,y in ((.4,.1),(.6,.1),(.5,.12))]
        caixa = SimpleNamespace(xmin=.2,ymin=.02,width=.6,height=.25)
        return SimpleNamespace(detections=[SimpleNamespace(score=[.95],location_data=SimpleNamespace(relative_keypoints=pontos,relative_bounding_box=caixa))])


class ModeloTeste:
    chamadas = []
    def __init__(self, caminho):
        self.pessoa = Path(caminho).name == 'yolov8n.pt'
        self.nome = Path(caminho).name
        self.names = {0:'capacete',1:'colete',2:'oculos',3:'luvas',4:'mascara'}
    def __call__(self, *_args, **opcoes):
        self.chamadas.append((self.nome,opcoes))
        if self.pessoa:
            return [SimpleNamespace(boxes=SimpleNamespace(xyxy=np.array([[100,50,300,450]])))]
        return [SimpleNamespace(names=self.names,boxes=SimpleNamespace(xyxy=np.array([[150,55,250,105],[170,82,230,102]]),cls=np.array([0,2]),conf=np.array([.95,.95])))]


class TestCentral(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.temp.name)
        self.monitor = Monitor(base=self.raiz)
        self.app = criar_app(self.monitor)
        self.app.testing = True
        self.cliente = self.app.test_client()
        self.central = self.app.extensions['central']
        self.conteudo = video_teste(self.raiz,80)

    def tearDown(self):
        self.central.encerrar()
        self.temp.cleanup()

    def post(self, url, dados=None):
        return self.cliente.post(url, json=dados or {}, headers=H)

    def enviar(self, conteudo=None, nome='teste.avi'):
        return self.cliente.post('/api/central/videos',data={'video':(io.BytesIO(self.conteudo if conteudo is None else conteudo),nome)},headers=H)

    def stubs(self):
        ModeloTeste.chamadas = []
        mp = SimpleNamespace(solutions=SimpleNamespace(pose=SimpleNamespace(Pose=lambda **_:PoseTeste()),face_detection=SimpleNamespace(FaceDetection=lambda **_:FaceTeste())))
        return patch.dict('sys.modules',{'mediapipe':mp,'ultralytics':SimpleNamespace(YOLO=ModeloTeste)})

    def test_pagina_central_e_painel_anterior_preservados(self):
        html = self.cliente.get('/')
        self.assertIn(b'demonstracao.js',html.data)
        self.assertIn(b'Central de monitoramento',html.data)
        self.assertIn(b'painel.js',self.cliente.get('/legado').data)
        with self.cliente.get('/static/demonstracao.css') as css:
            self.assertEqual(css.status_code,200)

    def test_upload_real_decodificacao_previa_e_nome_seguro(self):
        r = self.enviar(nome='../../fora.avi')
        self.assertEqual(r.status_code,200,r.json)
        fonte = r.json['resultado']
        self.assertEqual(fonte['nome'],'fora.avi')
        self.assertNotIn('caminho',fonte)
        self.assertEqual(fonte['total_quadros'],80)
        self.assertEqual(self.monitor.fonte_video.parent,self.central.media)
        self.assertEqual(self.cliente.get('/api/central/quadro.jpg').status_code,200)
        quadro = self.cliente.get('/api/central/quadro.jpg')
        self.assertEqual(self.cliente.get('/api/central/quadro.jpg',headers={'If-None-Match':quadro.headers['ETag']}).status_code,304)
        self.assertFalse(self.cliente.get('/api/central/estado').json['quadro_analisado'])

    def test_arquivo_vazio_extensao_invalida_e_codec_invalido(self):
        for conteudo,nome in ((b'','vazio.mp4'),(b'executavel','arquivo.exe'),(b'nao e video','falso.mp4')):
            with self.subTest(nome=nome):
                self.assertEqual(self.enviar(conteudo,nome).status_code,400)
        self.assertFalse(list(self.central.media.glob('*')))

    def test_limite_upload_e_sem_arquivo(self):
        self.app.config['MAX_CONTENT_LENGTH'] = 100
        self.assertEqual(self.enviar().status_code,413)
        self.app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024
        self.assertEqual(self.post('/api/central/videos').status_code,400)

    def test_origem_externa_e_sem_cabecalho_sao_recusados(self):
        self.assertEqual(self.cliente.post('/api/central/acao/iniciar',json={}).status_code,403)
        self.assertEqual(self.cliente.post('/api/central/acao/iniciar',json={},headers=H | {'Origin':'https://externo.test'}).status_code,403)
        self.assertEqual(self.cliente.post('/start',headers={'Sec-Fetch-Site':'cross-site'}).status_code,403)

    def test_controles_sem_fonte_e_busca_fora_do_video(self):
        self.assertEqual(self.post('/api/central/acao/iniciar').status_code,400)
        self.assertEqual(self.post('/api/central/acao/pausar').status_code,400)
        self.enviar()
        for t in (-1,4,'arquivo',True):
            self.assertEqual(self.post('/api/central/acao/buscar',{'segundos':t}).status_code,400)

    def test_legado_seleciona_camera_e_preserva_exclusao_de_fontes(self):
        self.enviar()
        anterior=self.monitor.fonte_video
        with patch.object(self.monitor,'iniciar',return_value=(True,'Teste')) as iniciar:
            self.assertEqual(self.cliente.post('/start').status_code,200)
            self.assertEqual(self.central.fonte['modo'],'camera')
            self.assertIsNone(self.monitor.fonte_video)
            self.assertFalse(anterior.exists())
            iniciar.assert_called_once_with()

    def test_legado_nao_troca_fonte_quando_existe_worker(self):
        self.enviar()
        antes=self.central.fonte['id']
        with patch.object(self.central,'_ativo',return_value=True),patch.object(self.monitor,'iniciar') as iniciar:
            self.assertEqual(self.cliente.post('/start').status_code,409)
            self.assertEqual(self.central.fonte['id'],antes)
            iniciar.assert_not_called()

    def test_processo_pausa_busca_reinicio_epi_e_termino(self):
        self.enviar()
        self.monitor.configurar_epi(['capacete','oculos'])
        with self.stubs(), patch('runtime_ia.opcoes_inferencia',return_value={'device':'cpu'}), patch('main.smtplib.SMTP_SSL') as smtp:
            self.assertEqual(self.post('/api/central/acao/iniciar').status_code,200)
            aguardar(lambda:self.central.quadros_processados>=3)
            s = self.central.snapshot()
            self.assertEqual(s['indicadores']['pessoas'],1)
            self.assertEqual(s['indicadores']['epis'],2)
            self.assertTrue(any(nome=='epi.pt' for nome,_ in ModeloTeste.chamadas))
            self.assertTrue(any(nome=='best.pt' for nome,_ in ModeloTeste.chamadas))
            self.assertEqual(s['deteccoes'][0]['situacao'],'em_pe')
            self.assertTrue(self.monitor.frame.startswith(b'\xff\xd8'))
            self.assertEqual(self.enviar().status_code,409)
            self.assertEqual(self.post('/api/central/acao/pausar').status_code,200)
            time.sleep(.1)
            numero = self.central.quadros_processados
            time.sleep(.15)
            self.assertEqual(self.central.quadros_processados,numero)
            segmento = self.central.segmento
            self.assertEqual(self.post('/api/central/acao/buscar',{'segundos':1}).status_code,200)
            aguardar(lambda:self.central.segmento>segmento and self.central.posicao==21)
            self.assertEqual(self.central.snapshot()['tempo_video'],1)
            self.assertEqual(len(self.monitor.motor.temporais[1].historico),1)
            self.assertEqual(self.post('/api/central/acao/retomar').status_code,200)
            aguardar(lambda:self.central.posicao>=23)
            segmento = self.central.segmento
            self.post('/api/central/acao/reiniciar')
            aguardar(lambda:self.central.segmento>segmento and self.central.posicao<=3)
            self.assertEqual(self.post('/api/central/acao/encerrar').status_code,200)
            self.assertFalse(list(self.central.media.glob('*')))
            self.assertIsNone(self.central.fonte)
            smtp.assert_not_called()

    def test_fim_de_video_nao_necessita_webcam(self):
        self.enviar(video_teste(self.raiz,3))
        with self.stubs(), patch('runtime_ia.opcoes_inferencia',return_value={'device':'cpu'}), patch('main.abrir_camera') as camera:
            self.post('/api/central/acao/iniciar')
            aguardar(lambda:self.monitor.status['estado']=='concluido')
            self.assertEqual(self.central.snapshot()['progresso'],1)
            self.assertEqual(self.central.quadros_processados,3)
            camera.assert_not_called()

    def test_historico_sem_smtp_fotos_e_duplicatas(self):
        self.enviar()
        self.monitor.demonstracao = True
        e = dict(tipo='queda',pessoa_id=1,motivo='Evento sintético de teste',classificacao='queda_observada',chaves=[(1,'queda','')])
        with patch('main.smtplib.SMTP_SSL') as smtp,patch('main.salvar_jpeg') as foto:
            for t in (2,2.5):
                self.monitor.alerta(np.zeros((20,20,3),np.uint8),e,t)
            self.assertEqual(len(self.monitor.eventos),1)
            self.assertEqual(self.monitor.eventos[0]['tempo_video'],2)
            self.assertEqual(self.monitor.eventos[0]['fonte_id'],self.central.fonte['id'])
            self.assertEqual(self.monitor.eventos[0]['email'],'desativado na demonstração')
            self.monitor.email(self.monitor.eventos[0],None)
            smtp.assert_not_called();foto.assert_not_called()

    def test_cameras_disponiveis_indisponiveis_e_alternancia(self):
        caps=[]
        def abrir(i):
            c=Mock();c.isOpened.return_value=i==0
            c.read.return_value=(True,np.zeros((480,640,3),np.uint8));caps.append(c);return c
        self.central.abrir_camera=abrir
        with patch.dict(os.environ,{'VIGIAAI_MAX_CAMERAS':'2'}):
            r=self.post('/api/central/cameras/buscar')
        self.assertEqual([c['indice'] for c in r.json['resultado']],[0])
        self.assertTrue(all(c.release.call_count==1 for c in caps))
        self.assertEqual(self.post('/api/central/camera',{'indice':99}).status_code,400)
        self.enviar()
        antigo=self.monitor.fonte_video
        self.assertEqual(self.post('/api/central/camera',{'indice':0}).status_code,200)
        self.assertFalse(antigo.exists())
        self.assertEqual(self.monitor.camera_indice,0)
        self.assertIsNone(self.monitor.fonte_video)
        self.assertEqual(self.post('/api/central/acao/buscar',{'segundos':0}).status_code,400)
        self.enviar()
        self.assertEqual(self.central.fonte['modo'],'video')

    def test_cameras_ausentes_lista_vazia(self):
        cap=Mock();cap.isOpened.return_value=False
        self.central.abrir_camera=lambda _:cap
        self.assertEqual(self.post('/api/central/cameras/buscar').json['resultado'],[])

    def test_camera_desconectada_ao_iniciar_informa_erro(self):
        self.central.cameras={0:dict(indice=0,nome='Câmera 0')}
        self.central.selecionar_camera(0)
        cap=Mock();cap.isOpened.return_value=False
        with self.stubs(),patch('runtime_ia.opcoes_inferencia',return_value={'device':'cpu'}),patch('main.abrir_camera',return_value=cap):
            self.post('/api/central/acao/iniciar')
            aguardar(lambda:self.monitor.status['estado']=='erro')
            self.assertIn('câmera 0',self.monitor.status['mensagem'])
            cap.release.assert_called_once()

    def test_epis_diferentes_nao_sao_descartados_como_duplicata(self):
        self.enviar();self.monitor.demonstracao=True
        q=np.zeros((20,20,3),np.uint8)
        for item in ('capacete','oculos'):
            self.monitor.alerta(q,dict(tipo='epi',pessoa_id=1,motivo='Teste de itens distintos',epis=[item],chaves=[(1,'epi',item)]),2)
        self.assertEqual(len(self.monitor.eventos),2)
        self.assertEqual(self.central.total_ocorrencias,2)

    def test_biblioteca_sem_videos_e_traversal(self):
        self.assertEqual(self.cliente.get('/api/central/biblioteca').json['resultado'],[])
        self.central.biblioteca.mkdir()
        (self.central.biblioteca/'biblioteca.json').write_text(json.dumps([dict(id='fora',arquivo='../teste.avi',autorizado=True,licenca='teste')]))
        self.assertEqual(self.cliente.get('/api/central/biblioteca').json['resultado'],[])
        self.assertEqual(self.post('/api/central/biblioteca/selecionar',{'id':'../teste.avi'}).status_code,400)

    def test_biblioteca_autorizada_e_limpeza_por_ttl(self):
        self.central.biblioteca.mkdir()
        (self.central.biblioteca/'local.avi').write_bytes(self.conteudo)
        (self.central.biblioteca/'biblioteca.json').write_text(json.dumps([dict(id='local',arquivo='local.avi',autorizado=True,licenca='criação sintética de teste')]))
        self.assertEqual(self.post('/api/central/biblioteca/selecionar',{'id':'local'}).status_code,200)
        self.central.encerrar()
        self.assertTrue((self.central.biblioteca/'local.avi').exists())
        self.central.media.mkdir(parents=True)
        p=self.central.media/('a'*32+'.avi');p.write_bytes(b'expirado');os.utime(p,(0,0))
        protegido=self.central.media/'nao-gerenciado.avi';protegido.write_bytes(b'preservar');os.utime(protegido,(0,0))
        self.central.limpar_expirados()
        self.assertFalse(p.exists());self.assertTrue(protegido.exists())
        protegido.unlink()

    def test_avaliacao_offline_preserva_politica_selecionada(self):
        m=MonitorVideo(self.raiz/'teste.avi',epis=['capacete','oculos'],base=self.raiz)
        self.assertEqual(m.epi_obrigatorio,['capacete','oculos'])


if __name__=='__main__':
    unittest.main()
