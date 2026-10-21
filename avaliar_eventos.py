"""Avalia alertas contra eventos independentes anotados; sem câmera ou SMTP."""

import argparse
import json
import math
from pathlib import Path
from statistics import mean


def avaliar(referencia, previsoes, tolerancia=3):
    duracao = referencia['duracao_segundos']
    if not math.isfinite(duracao) or duracao <= 0 or not math.isfinite(tolerancia) or tolerancia < 0:
        raise ValueError('Duração precisa ser positiva e tolerância não negativa.')
    eventos, alertas = referencia['eventos'], previsoes['eventos']
    if referencia['video_id'] != previsoes['video_id']:
        raise ValueError('Referência e previsões devem pertencer ao mesmo vídeo.')
    if abs(duracao - previsoes['duracao_segundos']) > max(.1, duracao * .01):
        raise ValueError('Durações incompatíveis: não compare recortes diferentes.')
    for e in eventos:
        if not (0 <= e['inicio'] <= e['fim'] <= duracao and 'pessoa_id' in e):
            raise ValueError('Evento de referência inválido.')
    for a in alertas:
        if not (math.isfinite(a['tempo']) and 0 <= a['tempo'] <= duracao and 'pessoa_id' in a):
            raise ValueError('Alerta inválido.')
    usados, latencias = set(), []
    falsos = []
    for a in sorted(alertas, key=lambda a: a['tempo']):
        candidatos = [i for i, e in enumerate(eventos) if i not in usados
                      and e['pessoa_id'] == a['pessoa_id']
                      and e['inicio'] <= a['tempo'] <= min(duracao, e['fim'] + tolerancia)]
        if candidatos:
            i = min(candidatos, key=lambda i: eventos[i]['inicio'])
            usados.add(i)
            latencias.append(a['tempo'] - eventos[i]['inicio'])
        else:
            falsos.append(a)
    return dict(eventos_reais=len(eventos), detectados=len(usados), perdidos=len(eventos) - len(usados),
                recall_por_evento=len(usados) / len(eventos) if eventos else None,
                falsos_alertas=len(falsos), falsos_alertas_por_hora=len(falsos) * 3600 / duracao,
                latencias_segundos=latencias, tempo_medio_ate_alerta=mean(latencias) if latencias else None,
                eventos_perdidos=[e for i, e in enumerate(eventos) if i not in usados],
                criterio='Associação um para um por pessoa e janela temporal; classificação clínica não avaliada.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('referencia')
    p.add_argument('previsoes')
    p.add_argument('--tolerancia', type=float, default=3)
    p.add_argument('--saida', required=True)
    a = p.parse_args()
    resultado = avaliar(*[json.loads(Path(f).read_text(encoding='utf-8')) for f in (a.referencia, a.previsoes)], a.tolerancia)
    Path(a.saida).write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding='utf-8')
