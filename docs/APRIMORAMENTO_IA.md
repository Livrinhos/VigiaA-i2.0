# Aprimoramento de IA — 21/10/2026

## Escopo e evidência

Flask, YOLOv8, OpenCV, MediaPipe, painel, seleção dos cinco EPIs, coleta e SMTP foram preservados.
Pesos originais não foram substituídos. Nenhum treinamento foi executado: neste clone existe somente
`dataset_epi/data.yaml`, sem imagens/labels. As antigas 36/5 imagens documentadas não estão aqui.
Não foi possível revisar visualmente essas anotações. Não existem métricas atuais de precisão industrial.

`epi.pt` e `best.pt` têm capacete, colete, oculos, luvas e mascara, nessa ordem. Não têm classes de ausência.
`yolov8n.pt` tem as 80 classes COCO; 0 é pessoa. Com os pesos atuais, falta de detecção resulta em
**inconclusivo**, preservando detecção positiva. `glasses` genérico não comprova proteção.
A classe histórica `oculos` continua compatível, mas distinguir óculos comuns/protetores exige dados revisados.

## Executar neste computador

Na pasta do clone, execute `./iniciar_vigiaai.ps1`, ou `./iniciar_vigiaai.ps1 -CPU`.
Abra `http://127.0.0.1:5000`. O arquivo privado `.runtime-python`, ignorado pelo Git, aponta para
o ambiente preparado nesta sessão. Para outros comandos:

```powershell
$pythonVigia = (Get-Content .runtime-python -Raw).Trim()
& $pythonVigia -m unittest discover -s tests -p 'test_*.py'
& $pythonVigia -m pip check
& $pythonVigia diagnosticar_ia.py --saida diagnosticos/inferencia.json
& $pythonVigia treinar_epi.py --somente-auditar
$env:VIGIAAI_PYTHON = $pythonVigia
node --test tests/test_painel.mjs
```

A auditoria deve retornar erro enquanto faltarem os dados. O teste do painel usa JavaScript real e
rotas Flask por `test_client` e ponte JSONL, sem porta de rede, com câmera simulada e SMTP bloqueado.

Configure `CAMERA_INDEX` no `.env`. O índice 1 não abriu no teste de acesso. O índice 0 forneceu
um quadro via dispositivo virtual com avisos do driver. Isso não confirma acesso a webcam física
nem valida pessoas/EPIs. Nenhum quadro desse teste foi salvo. A configuração padrão foi preservada.

## Instalar em outro computador

Requer Python 3.12 x64. Instale o ambiente em caminho **sem acentos**: MediaPipe 0.10.21 falhou ao abrir
seus recursos nativos quando a `.venv` ficava sob `Área de Trabalho`. O clone pode permanecer no lugar.
Exemplo para um perfil Windows que também não tenha acentos:

```powershell
py -3.12 -m venv "$env:USERPROFILE\Documents\VigiaAI-venv"
$pythonVigia = "$env:USERPROFILE\Documents\VigiaAI-venv\Scripts\python.exe"
& $pythonVigia -m pip install -r requirements-cuda.txt
# Alternativa sem CUDA: -r requirements-cpu.txt
$env:VIGIAAI_PYTHON = $pythonVigia
./iniciar_vigiaai.ps1
```

JAX/JAXLIB 0.4.38 foram testados com NumPy 1.26.4 e MediaPipe 0.10.21. PyTorch 2.6.0+cu124 e
torchvision 0.21.0+cu124 reconheceram a RTX 3060 de 12 GB. O toolkit CUDA completo não é necessário
para esse pacote PyTorch. `VIGIAAI_DEVICE=auto` seleciona GPU/CPU e `cpu` força CPU. A inferência
padrão é FP32/640; `VIGIAAI_FP16=1` é opção experimental ainda sem validação de precisão.

## Regras e limites

EPI é associado a no máximo uma pessoa, respeitando a região corporal. Ausência exige classe explícita
(`no_helmet`, `no_goggle` e aliases), confiança >=0,5, região verificável e três quadros distintos durante
o período configurado. Contradição, baixa luz/contraste, oclusão, rosto inadequado, cruzamento ambíguo
ou classe sem suporte ficam inconclusivos. A triagem de luz é inicial, não calibrada. Limiares 0,15/0,5
de óculos continuam sujeitos a calibração independente.

O rastreador original ganhou predição de velocidade e sinalização de associação ambígua. Perda de
pessoa interrompe confirmação/histórico. Trocas de IDs ainda podem acontecer. Não há reconhecimento facial.
[ByteTrack é compatível](https://docs.ultralytics.com/modes/track/), mas não foi adotado sem comparação
em vídeos independentes que demonstre benefício. Medir trocas e fragmentações antes dessa decisão.

`queda_temporal.py` considera cabeça, ombros, quadris, joelhos/tornozelos visíveis, inclinação,
velocidade normalizada por altura, persistência, imobilidade e recuperação. Três leituras eretas anteriores,
descida rápida de cabeça/quadris e postura deitada persistente sustentam transição compatível com queda.
Pouco deslocamento horizontal do quadril recebe hipótese de possível colapso, sem identificar causa.

- Queda observada e possível colapso exigem transição e persistência; não são diagnósticos.
- Encontrada deitada e imóvel exige >=5 s de imobilidade contínua; não afirma queda/desmaio.
- Deitada sem transição observada não é automaticamente queda.
- Transição gradual observada não gera acidente só por permanecer deitada; intenção não é inferida.
- Recuperação exige sequência ereta antes de permitir outro episódio.
- Sentada/agachada e abaixando/inclinada são exibidas como ambíguas quando não distinguíveis.
- Movimento ereto pode ser caminhada, mas não é classificado com certeza como tal.

Imobilidade pode sinalizar alguém dormindo/deitado: exige verificação humana. Câmera móvel, perspectiva,
queda em direção à câmera, oclusão e pessoa não detectada continuam limitações. Intervalos >1,25 s,
timestamps repetidos/regressivos e perda de pose interrompem a trajetória; emergências podem ser perdidas
em baixo FPS. `QUEDA_CHAO_Y` é uma linha opcional y/altura calibrada na mesma câmera fixa.
Sem calibração a proximidade do chão não é confirmada. A linha não resolve perspectiva.

Ocorrências incluem tipo, data/hora com fuso, ID temporário, classificação, EPIs e verificação humana pendente.
Uma ausência persistente já avisada não repete a cada cooldown. `NOTIFICACOES_ATIVAS=0` desativa SMTP,
`SALVAR_IMAGEM_OCORRENCIA=0` mantém registro sem foto, e `VIGIAAI_TESTE=1` impede SMTP mesmo com credenciais.
JPEGs usam codificação seguida de `pathlib`, suportando o caminho Windows com acentos.
Dados, vídeos, capturas, configurações e diagnósticos permanecem privados/ignorados pelo Git.

## Dados e fine-tuning

Consulte [fontes e condições](DATASETS_IA.md). Nenhum dataset público foi baixado/usado nesta sessão.
Use `dados_privados/` e um manifesto como este exemplo de formato (não é dataset completo):

```json
{
  "classes": ["capacete", "colete", "oculos", "luvas", "mascara", "no_helmet", "no_goggle"],
  "imagens": [{
    "imagem": "origem/cena001.jpg", "label": "origem/cena001.txt",
    "grupos": ["pessoa:p01", "sequencia:camA-turno01"],
    "fonte": "URL ou registro da origem", "licenca": "termos/registro de autorização",
    "autorizada": true, "revisada": true,
    "mapa_classes": {"0": "capacete", "1": "oculos"}
  }]
}
```

Mapeie todos os IDs da fonte. `null` significa descarte intencional/revisado de classe fora do escopo,
como Person. Preserve os cinco IDs originais e adicione novos ao final. Reanote itens de classes que a
fonte não anotou, evitando ensinar que são fundo. Use equipamentos vestidos por trabalhadores, negativos
difíceis e situações inconclusivas. Anote todos os itens visíveis; label vazio só após revisão humana.

Grupos identificam pessoas, sequências e eventos compartilhados entre câmeras, sem nomes reais.
Componentes conectados são mantidos juntos na divisão aproximada 70/15/15. O destino deve ser novo.
Três grupos independentes são o mínimo estrutural, não volume estatístico suficiente. A auditoria verifica
imagens legíveis, classes, caixas, negativos, duplicatas de pixels e vazamento de grupos. Ela não comprova
correção semântica nem encontra toda imagem quase duplicada: a revisão humana continua necessária.

```powershell
& $pythonVigia preparar_dataset.py dados_privados/manifesto.json dados_privados/preparado_v1
& $pythonVigia treinar_epi.py --dados dados_privados/preparado_v1/data.yaml --somente-auditar
& $pythonVigia treinar_epi.py --dados dados_privados/preparado_v1/data.yaml --modelo epi.pt --epocas 60 --resolucao 960 --taxa 0.0005 --congelar 10
```

Treino exige manifesto revisado/grupos e exemplos de todas as classes preservadas. O limite operacional
inicial é 100 imagens de treino, 30 de validação e 30 de teste, sem garantia de precisão. `--permitir-piloto`
identifica estudo pequeno, sem dispensar integridade/classes. Compare 640/960, freeze 10/0 e taxas
0,0005/0,0001 na validação, usando as mesmas divisões/sementes. Augmentations moderadas preservam óculos
pequenos. Medir erros por distância, luz, cor/vista de capacete, bonés, óculos comuns/escuros/protetores e oclusão.

Cada execução tem pasta própria, auditoria, configuração, backup e comparação; `epi.pt` não é substituído.
Pesos antigos/candidato são comparados nas mesmas cinco classes originais, resolução e split. Classes extras
são medidas separadamente no candidato. Precision, recall, mAP50 e mAP50-95 só aparecem após avaliação real.
O teste fica reservado por padrão. Use `--avaliar-teste-final` somente na execução final com parâmetros
congelados; escolher configurações repetidamente pelo teste contamina a avaliação.

## Vídeos independentes e métricas

Separe pessoas/eventos/câmeras/sequências entre desenvolvimento/teste e anote eventos antes de olhar a saída.
Inclua horas sem acidentes: caminhar, agachar, sentar/deitar com segurança, cruzamentos, baixa luz, falhas
e FPS baixo. Use vídeos autorizados ou simulações seguras; não provoque quedas perigosas.

```powershell
New-Item -ItemType Directory -Force avaliacoes_privadas
& $pythonVigia avaliar_video.py dados_privados/video_teste.mp4 --saida avaliacoes_privadas/previsoes.json
& $pythonVigia avaliar_eventos.py avaliacoes_privadas/referencia.json avaliacoes_privadas/previsoes.json --saida avaliacoes_privadas/metricas.json
```

O replay reutiliza o monitor, usa tempo do vídeo, não abre webcam, não grava fotos e substitui notificações.
A saída tem SHA256 do vídeo, duração, IDs temporários e leituras por quadro. É offline, sem reproduzir
todos os drops de tempo real. Meça adicionalmente na câmera alvo captura→aviso e quadros perdidos,
com uma e várias pessoas.

Referência: `{"video_id":"SHA256 do mesmo arquivo","duracao_segundos":60,
"eventos":[{"inicio":10,"fim":12,"pessoa_id":1}]}`. Associe manualmente as pessoas anotadas aos IDs
temporários e confira as trocas. O avaliador faz associação um para um por pessoa e janela início..fim+3 s;
duplicatas contam como falsos. Calcula recall/evento, perdidos, falsos/hora e latência. Não mede causa clínica
nem acerto entre subclasses. Agregar vídeos pelo tempo total, evitando duplicar eventos multicâmera.

Testes unitários usam dados sintéticos e não validam precisão no mundo real. Ainda dependem de dados:
mAP/precision/recall de EPI, recall de acidentes, falsos/hora e latência reais. Não houve treinamento de
sequências nem prova de benefício de um rastreador externo. Antes de produção, revisar permissões,
reunir dados representativos, congelar teste, calibrar limiares, comparar pesos e medir no local.
