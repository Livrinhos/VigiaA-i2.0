"""Ponte de testes: controlador JS real + Flask real; modelos/câmeras como fixtures explícitas."""

import base64
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import Monitor, criar_app
from test_central import video_teste, PoseTeste, FaceTeste, ModeloTeste


class CameraTeste:
    def __init__(self, indice): self.indice = indice
    def isOpened(self): return self.indice == 0
    def read(self):
        time.sleep(.02)
        q = np.zeros((480,640,3),np.uint8)
        q[:] = np.linspace(50,200,640,dtype=np.uint8)[None,:,None]
        return True,q
    def release(self): pass
    def set(self,*_): return True


os.environ['VIGIAAI_TESTE'] = '1'
mp = SimpleNamespace(solutions=SimpleNamespace(pose=SimpleNamespace(Pose=lambda **_:PoseTeste()),face_detection=SimpleNamespace(FaceDetection=lambda **_:FaceTeste())))
with tempfile.TemporaryDirectory(prefix='vigiaai-central-js-') as pasta, patch.dict('sys.modules',{'mediapipe':mp,'ultralytics':SimpleNamespace(YOLO=ModeloTeste)}), patch('runtime_ia.opcoes_inferencia',return_value={'device':'cpu'}), patch('main.abrir_camera',side_effect=CameraTeste):
    monitor = Monitor(base=pasta)
    app = criar_app(monitor)
    cliente = app.test_client()
    fixture = video_teste(pasta,100)
    try:
        for linha in sys.stdin:
            p = json.loads(linha)
            if p['url'] == '/fixture-video':
                r = dict(id=p['id'],status=200,headers={'Content-Type':'video/x-msvideo'},body=base64.b64encode(fixture).decode())
            else:
                dados = p.get('body')
                if p.get('arquivo'):
                    a=p['arquivo'];dados={'video':(io.BytesIO(base64.b64decode(a['base64'])),a['nome'])}
                with cliente.open(p['url'],method=p.get('method','GET'),data=dados,headers=p.get('headers',{})) as resposta:
                    r = dict(id=p['id'],status=resposta.status_code,headers=dict(resposta.headers),body=base64.b64encode(resposta.get_data()).decode())
            print(json.dumps(r),flush=True)
    finally:
        app.extensions['central'].encerrar()
