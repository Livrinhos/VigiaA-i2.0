"""Audita, treina e compara um candidato de EPI sem substituir epi.pt."""

import argparse
import hashlib
import json
import math
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml
from PIL import Image

BASE = Path(__file__).resolve().parent
EXTENSOES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def caminho_local(valor):
    caminho = Path(valor)
    return caminho if caminho.is_absolute() else BASE / caminho


def auditar_dataset(arquivo):
    """Valida imagens, pares de labels, classes e coordenadas YOLO."""
    dados = yaml.safe_load(arquivo.read_text(encoding="utf-8"))
    raiz = Path(dados.get("path", arquivo.parent))
    if not raiz.is_absolute():
        raiz = arquivo.parent / raiz
    names = dados["names"]
    nomes = dict(enumerate(names)) if isinstance(names, list) else names
    nomes = {int(chave): valor for chave, valor in nomes.items()}
    if set(nomes) != set(range(len(nomes))):
        raise ValueError("Os IDs de classes devem começar em 0 e ser consecutivos.")
    resumo = {"classes": nomes, "divisoes": {}, "avisos": [], "erros": []}
    hashes = {}
    for divisao in ("train", "val"):
        pasta = raiz / dados[divisao]
        if not pasta.is_dir():
            raise ValueError(f"Pasta {divisao} não encontrada: {pasta}")
        imagens = sorted(p for p in pasta.iterdir() if p.suffix.lower() in EXTENSOES)
        labels = raiz / "labels" / divisao
        contagem = Counter()
        for imagem in imagens:
            with Image.open(imagem) as original:
                pixels = original.convert("RGB")
                assinatura = hashlib.sha256(
                    str(pixels.size).encode() + pixels.tobytes()
                ).hexdigest()
                pixels.verify()
            if assinatura in hashes:
                anterior, divisao_anterior = hashes[assinatura]
                texto = f"Imagem duplicada: {imagem.name} e {anterior.name}."
                destino = "erros" if divisao_anterior != divisao else "avisos"
                resumo[destino].append(texto)
            hashes[assinatura] = imagem, divisao
            label = labels / f"{imagem.stem}.txt"
            if not label.is_file():
                resumo["erros"].append(f"Falta anotação de {imagem.name}.")
                continue
            for numero, linha in enumerate(label.read_text(encoding="utf-8").splitlines(), 1):
                if not linha.strip():
                    continue
                try:
                    valores = list(map(float, linha.split()))
                    if len(valores) != 5 or not all(map(math.isfinite, valores)):
                        raise ValueError("esperadas cinco coordenadas finitas")
                    classe, x, y, w, h = valores
                    if classe != int(classe) or int(classe) not in nomes:
                        raise ValueError("classe inválida")
                    if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
                        raise ValueError("coordenadas fora de [0, 1]")
                    if min(x - w / 2, y - h / 2) < -0.001 or max(x + w / 2, y + h / 2) > 1.001:
                        raise ValueError("caixa ultrapassa a imagem")
                    contagem[nomes[int(classe)]] += 1
                except ValueError as erro:
                    resumo["erros"].append(f"{label.name}:{numero}: {erro}")
        resumo["divisoes"][divisao] = {
            "imagens": len(imagens),
            "anotacoes": {nome: contagem[nome] for nome in nomes.values()},
        }
        if not imagens:
            resumo["erros"].append(f"Nenhuma imagem em {divisao}.")
        for nome in nomes.values():
            if contagem[nome] == 0:
                resumo["erros"].append(f"A classe {nome} não tem anotações em {divisao}.")
    if resumo["divisoes"]["val"]["imagens"] < 30:
        resumo["avisos"].append(
            "Validação muito pequena. As métricas servem para comparação local, "
            "não comprovam desempenho no monitoramento por câmera."
        )
    return resumo


def metricas_dict(resultado):
    return {
        "precision": float(resultado.box.mp),
        "recall": float(resultado.box.mr),
        "mAP50": float(resultado.box.map50),
        "mAP50_95": float(resultado.box.map),
        "por_classe": {
            resultado.names[int(classe)]: {
                "mAP50": float(resultado.box.ap50[indice]),
                "mAP50_95": float(resultado.box.ap[indice]),
            }
            for indice, classe in enumerate(resultado.box.ap_class_index)
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modelo", default="epi.pt", help="Pesos iniciais.")
    parser.add_argument("--dados", default="dataset_epi/data.yaml")
    parser.add_argument("--epocas", type=int, default=40)
    parser.add_argument("--congelar", type=int, default=10, help="Camadas iniciais congeladas; 0 para todas treináveis.")
    parser.add_argument("--taxa", type=float, default=0.0005)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--somente-auditar", action="store_true")
    args = parser.parse_args()
    if args.epocas < 1 or args.congelar < 0 or args.taxa <= 0:
        parser.error("Épocas/taxa devem ser positivas; congelar deve ser >= 0.")
    dados = caminho_local(args.dados)
    auditoria = auditar_dataset(dados)
    print(json.dumps(auditoria, ensure_ascii=False, indent=2), flush=True)
    if auditoria["erros"]:
        raise ValueError("Corrija os erros do dataset antes de treinar.")
    if args.somente_auditar:
        return

    import torch
    from ultralytics import YOLO

    torch.set_num_threads(4)
    dispositivo = 0 if torch.cuda.is_available() else "cpu"
    modelo_inicial = caminho_local(args.modelo)
    if not modelo_inicial.is_file():
        raise FileNotFoundError(f"Modelo inicial não encontrado: {modelo_inicial}")
    nome = f"treinamento_epi_{datetime.now():%Y%m%d_%H%M%S}"
    pasta = BASE / "runs" / "detect" / nome
    pasta.mkdir(parents=True, exist_ok=False)
    atual = BASE / "epi.pt"
    if atual.is_file():
        shutil.copy2(atual, pasta / "backup_epi.pt")
    relatorio = {
        "dataset": auditoria,
        "modelo_inicial": str(modelo_inicial),
        "configuracao": vars(args),
        "limitacao": "A validação existente contém apenas cinco imagens de objetos isolados. Não é um teste independente de funcionários pela câmera.",
        "modelo_atual_substituido": False,
    }

    def validar(pesos, nome_avaliacao):
        resultado = YOLO(str(pesos)).val(
            data=str(dados), imgsz=640, batch=4, device=dispositivo,
            workers=0, plots=True, save_json=False,
            project=str(pasta), name=nome_avaliacao, verbose=False,
        )
        return metricas_dict(resultado)

    if atual.is_file():
        relatorio["atual"] = validar(pasta / "backup_epi.pt", "avaliacao_atual")
    relatorio["inicial"] = validar(modelo_inicial, "avaliacao_inicial")
    (pasta / "comparacao.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Iniciando nova rodada:", pasta, flush=True)
    YOLO(str(modelo_inicial)).train(
        data=str(dados), epochs=args.epocas, imgsz=640, batch=4,
        device=dispositivo, workers=0, optimizer="AdamW", lr0=args.taxa,
        lrf=0.1, weight_decay=0.0005, warmup_epochs=2, warmup_bias_lr=args.taxa,
        freeze=args.congelar, patience=12, seed=args.seed,
        deterministic=True, mosaic=0.2, close_mosaic=min(8, args.epocas),
        degrees=8.0, translate=0.05, scale=0.15,
        fliplr=0.5, hsv_h=0.01, hsv_s=0.3, hsv_v=0.2,
        cache=False, plots=True,
        project=str(pasta), name="ajuste", exist_ok=False,
    )
    candidato = pasta / "ajuste" / "weights" / "best.pt"
    relatorio["candidato"] = validar(candidato, "avaliacao_candidato")
    relatorio["caminho_candidato"] = str(candidato)
    baseline = relatorio.get("atual", relatorio["inicial"])
    relatorio["melhorou_na_validacao"] = (
        relatorio["candidato"]["mAP50_95"] > baseline["mAP50_95"]
    )
    relatorio["melhorou_sobre_inicial"] = (
        relatorio["candidato"]["mAP50_95"] > relatorio["inicial"]["mAP50_95"]
    )
    (pasta / "comparacao.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Treinamento concluído. epi.pt foi preservado.", flush=True)
    print(json.dumps(relatorio, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
