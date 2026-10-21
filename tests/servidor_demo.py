"""Servidor de teste visual, com câmera simulada e SMTP desativado."""

import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import Monitor, criar_app


class MonitorSimulado(Monitor):
    def email(self, evento, arquivo):
        with self.lock:
            evento["email"] = "simulação; sem envio"

    def executar(self):
        pontos = {
            0: (0.5, 0.12, 1), 2: (0.4, 0.1, 1), 5: (0.6, 0.1, 1),
            11: (0.3, 0.3, 1), 12: (0.7, 0.3, 1),
            23: (0.35, 0.65, 1), 24: (0.65, 0.65, 1),
            15: (0.15, 0.6, 1), 16: (0.85, 0.6, 1),
            19: (0.15, 0.65, 1), 20: (0.85, 0.65, 1),
        }
        with self.lock:
            self.status.update(estado="ativo", mensagem="Câmera simulada para testar a interface.",
                               epi_ativo=True, epis_suportados=["capacete", "colete", "oculos", "luvas", "mascara"])
        try:
            while not self.stop.is_set():
                original = np.full((480, 800, 3), (45, 32, 20), dtype=np.uint8)
                cv2.putText(original, "CAMERA SIMULADA - TESTE LOCAL", (25, 35), cv2.FONT_HERSHEY_SIMPLEX, .6, (200, 220, 235), 1)
                cv2.circle(original, (350, 125), 30, (140, 175, 200), -1)
                cv2.rectangle(original, (300, 160), (400, 320), (90, 130, 180), -1)
                cv2.rectangle(original, (310, 320), (340, 420), (120, 100, 80), -1)
                cv2.rectangle(original, (360, 320), (390, 420), (120, 100, 80), -1)
                agora = time.monotonic()
                pessoas, alertas = self.processar_deteccoes(original, [(250, 60, 450, 440)], [pontos], [], agora)
                anotado = original.copy()
                cv2.rectangle(anotado, (250, 60), (450, 440), (80, 200, 120), 2)
                self._publicar_frame(original, anotado, pessoas, 8)
                for evento in alertas:
                    self.alerta(anotado, evento, agora)
                self.stop.wait(.12)
        finally:
            with self.lock:
                self.status.update(executando=False, estado="parado", mensagem="Monitoramento parado.", epi_ativo=False)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="vigiaai-demo-") as pasta:
        app = criar_app(MonitorSimulado(base=pasta, modelo_epi=None))
        app.run(host="127.0.0.1", port=5001, threaded=True, debug=False, load_dotenv=False)
