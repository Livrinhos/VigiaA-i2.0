"""Ponte JSONL para testar Flask e o controlador JS sem abrir porta de rede."""

import base64
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from servidor_demo import MonitorSimulado
from main import criar_app


with tempfile.TemporaryDirectory(prefix='vigiaai-painel-') as pasta:
    monitor = MonitorSimulado(base=pasta, modelo_epi=None, modelo_oculos=None)
    cliente = criar_app(monitor).test_client()
    try:
        for linha in sys.stdin:
            pedido = json.loads(linha)
            with cliente.open(pedido['url'], method=pedido.get('method', 'GET'),
                              data=pedido.get('body'), headers=pedido.get('headers', {})) as resposta:
                print(json.dumps(dict(id=pedido['id'], status=resposta.status_code,
                                      headers=dict(resposta.headers),
                                      body=base64.b64encode(resposta.get_data()).decode())), flush=True)
    finally:
        monitor.parar()
        if monitor.thread:
            monitor.thread.join(timeout=5)
