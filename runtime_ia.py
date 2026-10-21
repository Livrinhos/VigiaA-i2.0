"""Seleção explícita de CUDA/CPU, sem exigir CUDA no computador de destino."""

import os


def opcoes_inferencia():
    import torch
    pedido = os.getenv('VIGIAAI_DEVICE', 'auto').lower()
    if pedido not in ('auto', 'cpu', '0', 'cuda', 'cuda:0'):
        raise ValueError('VIGIAAI_DEVICE deve ser auto, cpu ou 0/cuda:0.')
    usar_cuda = pedido != 'cpu' and torch.cuda.is_available()
    resolucao = int(os.getenv('VIGIAAI_IMGSZ', '640'))
    if resolucao < 320 or resolucao % 32:
        raise ValueError('VIGIAAI_IMGSZ deve ser múltiplo de 32, a partir de 320.')
    return dict(device=0 if usar_cuda else 'cpu',
                quantize='fp16' if usar_cuda and os.getenv('VIGIAAI_FP16', '0') == '1' else 'fp32',
                imgsz=resolucao)
