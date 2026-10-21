# Treinamento de EPI

O script audita as imagens e anotações, cria um backup do epi.pt,
treina um candidato e compara os modelos na mesma validação. O arquivo
epi.pt usado pelo painel não é substituído durante o treinamento.

## Rodadas concluídas em 07/10/2026

Todos os modelos foram avaliados com as mesmas 5 imagens, resolução 640
e batch 4. As métricas abaixo são mAP50–95 e não porcentagens de acerto
em funcionários pela câmera.

| Modelo | mAP50–95 |
| --- | ---: |
| epi.pt atual | 23,1% |
| treino antigo treinamento_epi-2/weights/best.pt | 68,8% |
| novo ajuste com 10 camadas congeladas | 67,7% |
| novo ajuste de todas as camadas, taxa menor | 62,6% |

O modelo antigo -2 continuou sendo o melhor nessa validação.
As duas rodadas executaram 13 épocas cada: o encerramento antecipado
ocorreu após 12 épocas sem melhora. O melhor checkpoint de cada rodada
foi preservado, mesmo quando épocas posteriores pioraram.

Uma checagem adicional com confiança mínima de 0,5, como no painel,
retornou a classe esperada em 1 das 5 imagens com epi.pt; em 4 com o primeiro
candidato; e em todas as 5 com o antigo -2 e o segundo candidato.
Essa contagem verifica a presença da classe prevista, não a exatidão das
caixas. Houve detecções duplicadas de luvas e, no antigo -2, também de colete.

Candidatos e relatórios:

- [Primeiro candidato](runs/detect/treinamento_epi_20261007_142808/ajuste/weights/best.pt)
- [Primeira comparação](runs/detect/treinamento_epi_20261007_142808/comparacao.json)
- [Segundo candidato](runs/detect/treinamento_epi_20261007_143226/ajuste/weights/best.pt)
- [Segunda comparação](runs/detect/treinamento_epi_20261007_143226/comparacao.json)

Cada uma dessas pastas contém backup_epi.pt. O epi.pt original mantém
o SHA256 1f9fdde980c2e56c22c8857b778b5213fb07fc21fbcdb05fe71ef9c1fb50ce0e.

## Auditar antes de treinar

    .\.venv\Scripts\python.exe treinar_epi.py --somente-auditar

## Fazer uma nova rodada

    .\.venv\Scripts\python.exe treinar_epi.py --modelo runs/detect/treinamento_epi-2/weights/best.pt --epocas 40 --congelar 10

Para atualizar todas as camadas, use --congelar 0. A opção --taxa
controla a taxa de aprendizado. O programa utiliza CUDA se disponível,
ou CPU com quatro threads; usa workers=0 e a proteção __main__
para evitar a criação recursiva de processos no Windows.

Cada rodada fica em uma nova pasta runs/detect/treinamento_epi_DATA_HORA/:

- backup_epi.pt: cópia do modelo usado pelo painel no início da rodada.
- comparacao.json: auditoria, configuração e métricas por classe.
- ajuste/weights/best.pt: melhor candidato da rodada.
- ajuste/weights/last.pt: último estado do treinamento.
- avaliacao_candidato/: imagens de validação com as previsões.

Compare mAP50_95 dos modelos no relatório. Essa medida avalia classes
e localização das caixas; não é uma porcentagem de acertos de funcionários.
Uma melhoria nessa base pequena não comprova desempenho na câmera real.

## Testar um candidato no painel

Defina no .env o caminho do candidato, relativo à pasta do projeto:

    EPI_MODEL_PATH=runs/detect/treinamento_epi_DATA_HORA/ajuste/weights/best.pt

Substitua DATA_HORA pelo nome real da rodada e reinicie o servidor.
Para retornar ao modelo anterior, use EPI_MODEL_PATH=epi.pt e reinicie.
Se a variável já estiver definida no ambiente do terminal, esse valor tem
prioridade sobre o .env.

Para testar o melhor modelo desta comparação (o antigo -2):

    EPI_MODEL_PATH=runs/detect/treinamento_epi-2/weights/best.pt

## Dados disponíveis

A auditoria de 07/10/2026 encontrou 36 imagens de treino e 5 imagens de
validação, com uma anotação de cada classe na validação. As classes são:
capacete, colete, óculos, luvas e máscara.

As imagens de validação mostram EPIs isolados, enquanto o sistema precisa
avaliar itens vestidos por pessoas. Para medir esse uso, adicione um conjunto
independente de imagens reais da câmera, com pessoas diferentes, variação
de distância, iluminação e oclusão. Inclua também pessoas sem os itens e
revise as caixas aproximadas. Fotos relacionadas de uma mesma cena/pessoa
devem ficar juntas, para evitar que treino e avaliação compartilhem a cena.

Referências: [treinamento](https://docs.ultralytics.com/modes/train/) e
[validação](https://docs.ultralytics.com/modes/val/) do Ultralytics.
