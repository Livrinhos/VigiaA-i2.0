"""Auditoria de dados locais, sem downloads nem alteração das anotações."""

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import yaml
from PIL import Image

EXTENSOES = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
CLASSES_ORIGINAIS = ['capacete', 'colete', 'oculos', 'luvas', 'mascara']


def auditar_dataset(arquivo):
    arquivo = Path(arquivo).resolve()
    dados = yaml.safe_load(arquivo.read_text(encoding='utf-8-sig'))
    if not isinstance(dados, dict) or 'names' not in dados:
        raise ValueError('YAML deve definir names, train, val e test.')
    raiz = Path(dados.get('path', arquivo.parent))
    if not raiz.is_absolute():
        raiz = arquivo.parent / raiz
    raiz = raiz.resolve()
    nomes = dados['names']
    nomes = dict(enumerate(nomes)) if isinstance(nomes, list) else {int(k): v for k, v in nomes.items()}
    if set(nomes) != set(range(len(nomes))) or len(set(nomes.values())) != len(nomes):
        raise ValueError('Classes precisam de IDs consecutivos e nomes únicos.')
    resumo = dict(classes=nomes, divisoes={}, avisos=[], erros=[], grupos_verificados=False)
    if [nomes.get(i) for i in range(5)] != CLASSES_ORIGINAIS:
        resumo['erros'].append('Preserve as cinco classes originais nos IDs 0 a 4; adicione classes ao final.')
    registros = {}
    manifesto = dados.get('manifesto')
    if manifesto:
        p = raiz / manifesto
        try:
            registros = {r['imagem']: r for r in json.loads(p.read_text(encoding='utf-8'))}
        except (OSError, ValueError, KeyError, TypeError) as erro:
            resumo['erros'].append(f'Manifesto inválido: {erro}')
    else:
        resumo['avisos'].append('Sem manifesto: não é possível verificar pessoas/sequências entre divisões.')
    hashes, grupos, encontrados = {}, {}, set()
    fingerprint = hashlib.sha256()
    for divisao in ('train', 'val', 'test'):
        valor = dados.get(divisao)
        pastas = valor if isinstance(valor, list) else [valor] if valor else []
        imagens = []
        for pasta in pastas:
            pasta = raiz / pasta
            if pasta.is_dir():
                imagens.extend(sorted(p for p in pasta.rglob('*') if p.suffix.lower() in EXTENSOES))
            elif pasta.is_file() and pasta.suffix == '.txt':
                imagens.extend((pasta.parent / l.strip()).resolve() for l in pasta.read_text(encoding='utf-8').splitlines() if l.strip())
            else:
                resumo['erros'].append(f'Caminho {divisao} não encontrado: {pasta}')
        contagem, negativos = Counter(), 0
        labels_usados = set()
        for imagem in imagens:
            try:
                with Image.open(imagem) as original:
                    original.verify()
                with Image.open(imagem) as original:
                    pixels = original.convert('RGB')
                    assinatura = hashlib.sha256(str(pixels.size).encode() + pixels.tobytes()).hexdigest()
                    if min(pixels.size) < 64:
                        resumo['avisos'].append(f'Imagem muito pequena: {imagem.name}')
            except (OSError, ValueError, SyntaxError) as erro:
                resumo['erros'].append(f'Imagem ilegível {imagem.name}: {erro}')
                continue
            if assinatura in hashes:
                anterior, anterior_split = hashes[assinatura]
                resumo['erros' if anterior_split != divisao else 'avisos'].append(f'Pixels duplicados: {imagem.name} e {anterior} ({anterior_split}/{divisao}).')
            hashes[assinatura] = imagem.name, divisao
            fingerprint.update((divisao + assinatura).encode())
            try:
                relativo = imagem.relative_to(raiz).as_posix()
            except ValueError:
                relativo = str(imagem)
            encontrados.add(relativo)
            registro = registros.get(relativo)
            if manifesto:
                if not registro or not registro.get('grupos') or registro.get('split') != divisao:
                    resumo['erros'].append(f'Metadados/grupos ausentes ou divisão divergente: {relativo}')
                elif not (registro.get('revisada') is True and registro.get('autorizada') is True and registro.get('licenca')):
                    resumo['erros'].append(f'Revisão ou permissão não comprovada: {relativo}')
                else:
                    for grupo in registro['grupos']:
                        if grupo in grupos and grupos[grupo] != divisao:
                            resumo['erros'].append(f'Vazamento do grupo {grupo}: {grupos[grupo]}/{divisao}')
                        grupos[grupo] = divisao
            partes = list(imagem.parts)
            if 'images' not in partes:
                resumo['erros'].append(f'Imagem fora da estrutura images/labels: {imagem}')
                continue
            partes[len(partes) - 1 - partes[::-1].index('images')] = 'labels'
            label = Path(*partes).with_suffix('.txt')
            labels_usados.add(label.resolve())
            if not label.is_file():
                resumo['erros'].append(f'Falta anotação: {label.name} (negativos precisam de arquivo vazio).')
                continue
            fingerprint.update(label.read_bytes())
            linhas = [l for l in label.read_text(encoding='utf-8-sig').splitlines() if l.strip()]
            negativos += not linhas
            for numero, linha in enumerate(linhas, 1):
                try:
                    valores = list(map(float, linha.split()))
                    if len(valores) != 5 or not all(map(math.isfinite, valores)):
                        raise ValueError('esperados classe e quatro valores finitos')
                    classe, x, y, w, h = valores
                    if classe != int(classe) or int(classe) not in nomes:
                        raise ValueError('classe inválida')
                    if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
                        raise ValueError('coordenadas fora de [0,1]')
                    if min(x - w / 2, y - h / 2) < -.001 or max(x + w / 2, y + h / 2) > 1.001:
                        raise ValueError('caixa ultrapassa a imagem')
                    contagem[nomes[int(classe)]] += 1
                except ValueError as erro:
                    resumo['erros'].append(f'{label.name}:{numero}: {erro}')
        resumo['divisoes'][divisao] = dict(imagens=len(imagens), negativos=negativos,
                                          anotacoes={nome: contagem[nome] for nome in nomes.values()})
        orfaos = {p.resolve() for p in (raiz / 'labels' / divisao).rglob('*.txt')} - labels_usados
        if orfaos:
            resumo['avisos'].append(f'{len(orfaos)} anotações sem imagem correspondente em {divisao}.')
        if not imagens:
            resumo['erros'].append(f'Nenhuma imagem em {divisao}.')
        for nome in nomes.values():
            if not contagem[nome]:
                resumo['avisos'].append(f'Classe {nome} sem anotações em {divisao}.')
        if not negativos:
            resumo['avisos'].append(f'Sem imagens negativas revisadas em {divisao}.')
    if set(registros) - encontrados:
        resumo['erros'].append('Manifesto contém imagens não encontradas nas divisões.')
    resumo['grupos_verificados'] = bool(manifesto and registros and not resumo['erros'])
    fingerprint.update(json.dumps(dict(classes=nomes, registros=registros), sort_keys=True).encode())
    resumo['fingerprint_sha256'] = fingerprint.hexdigest()
    if resumo['divisoes']['val']['imagens'] < 30 or resumo['divisoes']['test']['imagens'] < 30:
        resumo['avisos'].append('Validação/teste muito pequenos para alegar precisão industrial.')
    return resumo
