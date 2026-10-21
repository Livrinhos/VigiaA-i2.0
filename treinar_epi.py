"""Audita, treina e compara um candidato de EPI sem substituir epi.pt."""

import argparse
import json
import os
import math
import shutil
from datetime import datetime
from pathlib import Path

from dataset_ia import auditar_dataset

BASE = Path(__file__).resolve().parent


def caminho_local(valor):
    caminho = Path(valor)
    return caminho if caminho.is_absolute() else BASE / caminho


def metricas_dict(resultado):
    return {
        "precision": float(resultado.box.mp),
        "recall": float(resultado.box.mr),
        "mAP50": float(resultado.box.map50),
        "mAP50_95": float(resultado.box.map),
        "por_classe": {
            resultado.names[int(classe)]: {
                'precision': float(resultado.box.p[indice]),
                'recall': float(resultado.box.r[indice]),
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
    parser.add_argument('--resolucao', type=int, default=960, help='Comparar 640 e 960 usando a validação; teste fica reservado.')
    parser.add_argument('--batch', type=int, default=4)
    parser.add_argument('--device', default='auto')
    parser.add_argument('--permitir-piloto', action='store_true', help='Permite amostra pequena; não comprova precisão industrial.')
    parser.add_argument('--avaliar-teste-final', action='store_true', help='Só usar após congelar configurações na validação.')
    args = parser.parse_args()
    if args.epocas < 1 or args.congelar < 0 or not math.isfinite(args.taxa) or args.taxa <= 0:
        parser.error("Épocas/taxa devem ser positivas; congelar deve ser >= 0.")
    dados = caminho_local(args.dados)
    auditoria = auditar_dataset(dados)
    print(json.dumps(auditoria, ensure_ascii=False, indent=2), flush=True)
    if args.somente_auditar:
        return 1 if auditoria['erros'] else 0
    if auditoria["erros"] or not auditoria['grupos_verificados']:
        raise ValueError("Corrija o dataset e informe manifesto revisado com grupos independentes antes de treinar.")
    if any(auditoria['divisoes']['train']['anotacoes'][nome] == 0 for nome in auditoria['classes'].values()):
        raise ValueError('Todas as classes preservadas precisam de exemplos no treino para evitar perda de funcionalidades.')
    if not args.permitir_piloto and any(auditoria['divisoes'][s]['imagens'] < n for s, n in [('train', 100), ('val', 30), ('test', 30)]):
        raise ValueError('Dados insuficientes para experimento padrão. --permitir-piloto identifica explicitamente um estudo pequeno.')
    if args.resolucao < 320 or args.resolucao % 32 or args.batch < 1:
        parser.error('Resolução deve ser múltiplo de 32 >= 320; batch deve ser positivo.')

    import torch
    os.environ.setdefault('YOLO_CONFIG_DIR', str(BASE / 'diagnosticos' / 'ultralytics'))
    from ultralytics import YOLO

    torch.set_num_threads(4)
    dispositivo = (0 if torch.cuda.is_available() else 'cpu') if args.device == 'auto' else args.device
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
        "limitacao": "Métricas de imagens não comprovam desempenho industrial; teste independente reservado, sem ajuste de limiares no teste.",
        "modelo_atual_substituido": False,
    }

    def validar(pesos, nome_avaliacao, split='val', classes_comuns=True):
        resultado = YOLO(str(pesos)).val(
            data=str(dados), imgsz=args.resolucao, batch=args.batch, device=dispositivo, split=split,
            workers=0, plots=True, save_json=False,
            classes=list(range(5)) if classes_comuns else None,
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
        data=str(dados), epochs=args.epocas, imgsz=args.resolucao, batch=args.batch,
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
    relatorio['criterio_comparacao'] = 'Mesma divisão, resolução e classes originais 0..4. Classes extras são avaliadas separadamente no candidato.'
    relatorio['candidato_todas_classes'] = validar(candidato, 'avaliacao_candidato_completa', classes_comuns=False)
    relatorio['teste_independente'] = None
    if args.avaliar_teste_final:
        relatorio['teste_independente'] = {'candidato': validar(candidato, 'teste_candidato', 'test')}
        relatorio['teste_candidato_todas_classes'] = validar(candidato, 'teste_candidato_completo', 'test', classes_comuns=False)
        for nome_modelo, pesos in [('epi_original', atual), ('best_original', BASE / 'runs/detect/treinamento_epi-2/weights/best.pt')]:
            if pesos.is_file():
                relatorio['teste_independente'][nome_modelo] = validar(pesos, f'teste_{nome_modelo}', 'test')
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
    raise SystemExit(main())
