"""Integra anotações revisadas e fontes autorizadas; separa grupos conectados."""

import argparse
import hashlib
import json
import random
import shutil
from pathlib import Path

import yaml

from dataset_ia import CLASSES_ORIGINAIS, auditar_dataset


def preparar(manifesto, destino, seed=42):
    manifesto, destino = Path(manifesto).resolve(), Path(destino).resolve()
    dados = json.loads(manifesto.read_text(encoding='utf-8-sig'))
    classes, entradas = dados['classes'], dados['imagens']
    if classes[:5] != CLASSES_ORIGINAIS or len(classes) != len(set(classes)):
        raise ValueError('Preserve as classes originais, na mesma ordem, antes de novas classes.')
    if destino.exists():
        raise ValueError('Destino precisa ser novo; datasets existentes nunca são sobrescritos.')
    donos, pais = {}, list(range(len(entradas)))

    def raiz(i):
        while pais[i] != i:
            pais[i] = pais[pais[i]]
            i = pais[i]
        return i

    preparados = []
    for i, entrada in enumerate(entradas):
        if not (entrada.get('revisada') is True and entrada.get('autorizada') is True
                and entrada.get('licenca') and entrada.get('fonte') and entrada.get('grupos')):
            raise ValueError(f'Entrada {i}: exige revisão, autorização, fonte, licença e grupos.')
        if not isinstance(entrada['grupos'], list) or any(not isinstance(g, str) or not g.strip() for g in entrada['grupos']):
            raise ValueError(f'Entrada {i}: grupos precisam ser lista de identificadores não vazios.')
        imagem = (manifesto.parent / entrada['imagem']).resolve()
        label = (manifesto.parent / entrada['label']).resolve()
        if not imagem.is_file() or not label.is_file():
            raise ValueError(f'Entrada {i}: imagem ou label ausente.')
        assinatura = hashlib.sha256(imagem.read_bytes()).hexdigest()
        # Uma pessoa ou sequência compartilhada conecta os grupos inteiros.
        for grupo in entrada['grupos'] + ['sha256:' + assinatura]:
            if grupo in donos:
                pais[raiz(i)] = raiz(donos[grupo])
            donos[grupo] = i
        linhas = []
        mapa = entrada.get('mapa_classes')
        for linha in label.read_text(encoding='utf-8-sig').splitlines():
            if not linha.strip():
                continue
            valores = linha.split()
            if len(valores) != 5:
                raise ValueError(f'Label inválido: {label.name}')
            original = int(valores[0])
            if mapa is not None:
                if str(original) not in mapa:
                    raise ValueError(f'Classe {original} sem mapeamento explícito em {label.name}.')
                nome = mapa[str(original)]
                if nome is None:  # Descarte explícito e revisado (ex.: Person).
                    continue
                if nome not in classes:
                    raise ValueError(f'Classe de destino desconhecida: {nome}')
                valores[0] = str(classes.index(nome))
            linhas.append(' '.join(valores))
        preparados.append((entrada, imagem, linhas, assinatura))
    componentes = {}
    for i in range(len(entradas)):
        componentes.setdefault(raiz(i), []).append(i)
    if len(componentes) < 3:
        raise ValueError('São necessários ao menos três grupos independentes para train/val/test.')
    blocos = list(componentes.values())
    random.Random(seed).shuffle(blocos)
    # Alocação aproximada 70/15/15 por imagem; nunca quebra um componente.
    alocacao, totais = {}, dict(train=0, val=0, test=0)
    metas = dict(train=.7 * len(entradas), val=.15 * len(entradas), test=.15 * len(entradas))
    for j, bloco in enumerate(blocos):
        faltantes = [s for s in totais if totais[s] == 0]
        split = faltantes[0] if len(blocos) - j == len(faltantes) else max(totais, key=lambda s: metas[s] - totais[s])
        for i in bloco:
            alocacao[i] = split
        totais[split] += len(bloco)
    destino.mkdir(parents=True, exist_ok=False)
    registros = []
    for i, (entrada, imagem, linhas, assinatura) in enumerate(preparados):
        split = alocacao[i]
        nome = f'{i:06d}_{assinatura[:12]}'
        alvo = destino / 'images' / split / (nome + imagem.suffix.lower())
        label = destino / 'labels' / split / (nome + '.txt')
        alvo.parent.mkdir(parents=True, exist_ok=True)
        label.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(imagem, alvo)
        label.write_text('\n'.join(linhas) + ('\n' if linhas else ''), encoding='utf-8')
        registros.append({k: entrada[k] for k in ('grupos', 'revisada', 'autorizada', 'licenca', 'fonte')} |
                         dict(imagem=alvo.relative_to(destino).as_posix(), split=split, sha256=assinatura))
    (destino / 'manifesto.json').write_text(json.dumps(registros, ensure_ascii=False, indent=2), encoding='utf-8')
    config = dict(train='images/train', val='images/val', test='images/test',
                  names=classes, manifesto='manifesto.json')
    (destino / 'data.yaml').write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding='utf-8')
    auditoria = auditar_dataset(destino / 'data.yaml')
    (destino / 'auditoria.json').write_text(json.dumps(auditoria, ensure_ascii=False, indent=2), encoding='utf-8')
    return auditoria


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifesto')
    parser.add_argument('destino')
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    resultado = preparar(args.manifesto, args.destino, args.seed)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    raise SystemExit(bool(resultado['erros']))
