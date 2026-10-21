"""Inventário dos pesos e tempo de inferência com imagem sintética; sem webcam."""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from statistics import median


def diagnosticar(base, repeticoes=10):
    import numpy as np
    import torch
    import mediapipe as mp
    base = Path(base)
    config = base / 'diagnosticos' / 'ultralytics'
    config.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('YOLO_CONFIG_DIR', str(config))
    from ultralytics import YOLO
    torch.set_num_threads(4)
    quadro = np.random.default_rng(42).integers(0, 255, (720, 1280, 3), dtype=np.uint8)
    resultado = dict(torch=torch.__version__, cuda=torch.version.cuda, cuda_disponivel=torch.cuda.is_available(),
                     gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                     mediapipe=mp.__version__, modelos={},
                     protocolo=dict(imagem='ruído sintético 1280x720', imgsz=640, batch=1, repeticoes=repeticoes,
                                    aquecimentos=3, precisao='FP32', threads_cpu=4),
                     limitacao='Teste de carregamento e latência isolada. Não mede precisão, FPS de webcam ou pipeline com várias pessoas.')
    for nome in ['yolov8n.pt', 'epi.pt', 'runs/detect/treinamento_epi-2/weights/best.pt']:
        arquivo = base / nome
        modelo = YOLO(str(arquivo))
        registro = dict(sha256=hashlib.sha256(arquivo.read_bytes()).hexdigest(), bytes=arquivo.stat().st_size,
                        classes=modelo.names, parametros=sum(p.numel() for p in modelo.model.parameters()), tempos={})
        for dispositivo in (['cpu', 0] if torch.cuda.is_available() else ['cpu']):
            # Uma instância por dispositivo evita reutilizar o backend anterior.
            modelo = YOLO(str(arquivo))
            tempos = []
            for i in range(repeticoes + 3):
                if dispositivo == 0:
                    torch.cuda.synchronize()
                inicio = time.perf_counter()
                modelo(quadro, imgsz=640, device=dispositivo, quantize='fp32', verbose=False)
                if dispositivo == 0:
                    torch.cuda.synchronize()
                if i >= 3:
                    tempos.append((time.perf_counter() - inicio) * 1000)
            registro['tempos'][str(dispositivo)] = dict(dispositivo_real=str(modelo.predictor.device), mediana_ms=round(median(tempos), 2),
                                                       max_ms=round(max(tempos), 2))
        resultado['modelos'][nome] = registro
    with mp.solutions.pose.Pose(static_image_mode=True, model_complexity=1) as pose:
        tempos = []
        for i in range(repeticoes + 3):
            inicio = time.perf_counter()
            pose.process(quadro)
            if i >= 3:
                tempos.append((time.perf_counter() - inicio) * 1000)
        resultado['pose_recorte_sintetico_mediana_ms'] = round(median(tempos), 2)
    return resultado


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--saida', default='diagnosticos/inferencia.json')
    p.add_argument('--repeticoes', type=int, default=10)
    a = p.parse_args()
    if a.repeticoes < 1:
        p.error('Repetições devem ser positivas.')
    resultado = diagnosticar(Path(__file__).resolve().parent, a.repeticoes)
    saida = Path(a.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
