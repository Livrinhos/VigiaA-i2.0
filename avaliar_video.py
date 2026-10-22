"""Reproduz vídeo local no pipeline existente; não envia SMTP nem grava imagens."""

import argparse
import hashlib
import json
from pathlib import Path

from main import Monitor
from epi_monitoramento import EPIS


class MonitorVideo(Monitor):
    def __init__(self, video, epis=None, **kwargs):
        super().__init__(fonte_video=video, **kwargs)
        if epis is not None:
            if any(item not in EPIS for item in epis):
                raise ValueError('Política de EPI inválida.')
            self.epi_obrigatorio = list(dict.fromkeys(epis))
        self.resultados = []
        self.leituras = []

    def alerta(self, quadro, evento, agora):
        self.resultados.append(dict(tempo=agora, pessoa_id=evento['pessoa_id'],
                                    tipo=evento['tipo'], classificacao=evento.get('classificacao'),
                                    confirmacao=evento.get('confirmacao')))
        self.motor.confirmador.marcar_alerta(evento['chaves'], agora)

    def _publicar_frame(self, original, anotado, pessoas, fps):
        # Apenas características e IDs temporários; sem frames ou biometria.
        self.leituras.append(dict(tempo=self.video_tempo, pessoas=pessoas))


def analisar(video, epis=None):
    import cv2
    video = Path(video)
    if not video.is_file():
        raise ValueError('Vídeo local não encontrado.')
    cap = cv2.VideoCapture(str(video))
    try:
        fps, quadros = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not cap.isOpened() or fps <= 0 or quadros <= 0:
            raise ValueError('Vídeo sem duração válida.')
    finally:
        cap.release()
    monitor = MonitorVideo(video, epis=epis)
    monitor.executar()
    if monitor.status['estado'] == 'erro':
        raise RuntimeError(monitor.status['mensagem'])
    if len(monitor.leituras) != int(quadros):
        raise RuntimeError('Leitura incompleta do vídeo; confira decodificação antes de calcular métricas.')
    return dict(video_id=hashlib.sha256(video.read_bytes()).hexdigest(), duracao_segundos=quadros / fps,
                eventos=monitor.resultados, leituras=monitor.leituras, politica_epi=monitor.epi_obrigatorio,
                limitacao='Reprodução offline; não mede desempenho em tempo real. Anotar eventos independentemente.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('video')
    p.add_argument('--saida', required=True)
    p.add_argument('--epis', nargs='*', choices=list(EPIS), default=None)
    a = p.parse_args()
    Path(a.saida).write_text(json.dumps(analisar(a.video, epis=a.epis), ensure_ascii=False, indent=2), encoding='utf-8')
