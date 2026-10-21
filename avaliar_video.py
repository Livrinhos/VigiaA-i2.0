"""Reproduz vídeo local no pipeline existente; não envia SMTP nem grava imagens."""

import argparse
import hashlib
import json
from pathlib import Path

from main import Monitor


class MonitorVideo(Monitor):
    def __init__(self, video, **kwargs):
        super().__init__(fonte_video=video, **kwargs)
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


def analisar(video):
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
    monitor = MonitorVideo(video)
    # Avaliação de emergências independe da política privada de EPI do painel.
    monitor.epi_obrigatorio = []
    monitor.executar()
    if monitor.status['estado'] == 'erro':
        raise RuntimeError(monitor.status['mensagem'])
    if len(monitor.leituras) != int(quadros):
        raise RuntimeError('Leitura incompleta do vídeo; confira decodificação antes de calcular métricas.')
    return dict(video_id=hashlib.sha256(video.read_bytes()).hexdigest(), duracao_segundos=quadros / fps,
                eventos=monitor.resultados, leituras=monitor.leituras,
                limitacao='Reprodução offline; não mede desempenho em tempo real. Anotar eventos independentemente.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('video')
    p.add_argument('--saida', required=True)
    a = p.parse_args()
    Path(a.saida).write_text(json.dumps(analisar(a.video), ensure_ascii=False, indent=2), encoding='utf-8')
