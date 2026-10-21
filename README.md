# VigiaAI

Painel local em Flask para monitoramento por câmera, indicação de possíveis
quedas, verificação de EPIs selecionados e notificações por e-mail.

Esta versão inclui o código atual e os três modelos necessários. Não inclui
`.venv`, senhas, imagens de pessoas, dataset de treinamento ou backups locais.
O repositório é público: não adicione esses arquivos em commits futuros.

## Instalar em outro computador Windows

Use **Python 3.12 de 64 bits**, Git e uma conexão com a internet. Não copie
a `.venv` do computador antigo. Extraia ou clone o projeto no SSD do novo PC.

No PowerShell:

```powershell
git clone --depth 1 https://github.com/susuque-samuel/VigiaAi.git
cd VigiaAi
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-cpu.txt
.\.venv\Scripts\python.exe -m pip check
Copy-Item .env.example .env
notepad .env
```

A cópia do `.env` acima é apenas para uma instalação nova. Se o arquivo já
existir, não o sobrescreva. Complete os dados de câmera e e-mail antes de usar.
Também pode transferir o `.env` antigo por um meio privado, sem publicá-lo.

Inicie o sistema:

```powershell
.\.venv\Scripts\python.exe main.py
```

Abra <http://127.0.0.1:5000> e clique em iniciar. Para escolher a câmera,
ajuste `CAMERA_INDEX` no `.env` e reinicie o servidor. Os índices podem mudar
entre computadores. Não é necessário ativar
a `.venv` nem alterar a política de execução do PowerShell.

Os comandos acima instalam PyTorch para **CPU**. Uma placa NVIDIA só será
usada com uma instalação de PyTorch/CUDA compatível com a placa e seu driver;
não basta transferir o código. Consulte o [instalador oficial do PyTorch](https://pytorch.org/get-started/locally/)
antes de alterar as versões de `torch` e `torchvision` deste projeto.

## Atualizar o sistema em outro computador

Pare o servidor com `Ctrl+C` antes de atualizar. Dentro de um clone deste
repositório, sem alterações locais pendentes:

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe main.py
```

Depois atualize a página com `Ctrl+F5`. O `.env` e `config_epi.json` privados
permanecem no computador. Se você alterou arquivos de código manualmente,
preserve suas alterações antes de atualizar; não use comandos de descarte.
Para instalações baixadas em ZIP, extraia a versão nova em outra pasta e
transfira apenas o `.env` e a configuração privada, recriando a `.venv` nela.

O ajuste de 20/10/2026 corrige a classificação de posturas ambíguas, melhora
o enquadramento da pose e considera a duração do processamento na confirmação.
O painel mostra a inclinação estimada e o progresso de confirmação da possível
queda. Não houve mudança das dependências nem dos pesos nesta correção.
Leia os limites e testes em [Monitoramento e coleta](MONITORAMENTO_E_COLETA.md#correção-da-avaliação-de-quedas-em-20102026).

## Configurar o `.env`

| Variável | Conteúdo |
| --- | --- |
| `CAMERA_INDEX` | Índice da câmera, como `0`, `1` ou `2`. Reinicie o servidor após alterar. |
| `COOLDOWN_SEGUNDOS` | Intervalo mínimo entre alertas da mesma pessoa, tipo e EPI. |
| `EPI_CONFIRMACAO_SEGUNDOS` | Tempo inicial para confirmar uma possível ausência. A política salva no painel tem prioridade. |
| `QUEDA_CONFIRMACAO_SEGUNDOS` | Tempo para confirmar a postura deitada antes do alerta de possível queda. |
| `EPI_MODEL_PATH` | Opcional: caminho do modelo principal; padrão `epi.pt`. |
| `OCULOS_MODEL_PATH` | Modelo adicional dos óculos, incluído em `runs/detect/treinamento_epi-2/weights/best.pt`. |
| `SMTP_HOST` | Servidor SMTP, por exemplo `smtp.gmail.com`. |
| `SMTP_PORTA` | Porta SMTP com SSL, normalmente `465`. |
| `EMAIL_REMETENTE` | Endereço da conta que enviará os alertas. |
| `EMAIL_DESTINATARIO` | Endereço que receberá os alertas. |
| `SMTP_SENHA` | Senha de aplicativo da conta remetente, não a senha comum da conta. |

Para preservar a seleção dos EPIs e o tempo configurado no painel, copie
`config_epi.json` do computador antigo por um meio privado. Sem esse arquivo,
selecione novamente os itens e clique em salvar política. Reinicie o servidor
após alterar o `.env`.

## Modelos incluídos

| Arquivo | Função |
| --- | --- |
| `yolov8n.pt` | Detecção de pessoas. |
| `epi.pt` | Modelo principal de capacete, colete, óculos, luvas e máscara. |
| `runs/detect/treinamento_epi-2/weights/best.pt` | Segunda verificação, apenas para óculos. |

Mantenha esses caminhos ao copiar manualmente. A instalação não depende das
demais pastas de treinamento. Os modelos podem falhar conforme distância,
iluminação, posição e oclusões. Uma indicação inconclusiva não comprova ausência
de EPI e não gera alerta de EPI. A postura deitada é apenas um indício de
possível queda, não uma confirmação de acidente.

## Testes e treinamento

Os testes não usam câmera nem enviam e-mail:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Para o teste opcional do controlador JavaScript, instale Node.js e execute
`.\.venv\Scripts\python.exe tests/servidor_demo.py` em outro terminal.
Depois rode `node --test tests/test_painel.mjs`. O servidor simulado usa a porta
5001 e deve ser encerrado ao final.

O script `treinar_epi.py` e `dataset_epi/data.yaml` estão incluídos, mas fotos
e anotações não são publicadas. Para treinar, transfira privadamente
`dataset_epi/images/` e `dataset_epi/labels/`, preservando `train` e `val`:

```powershell
.\.venv\Scripts\python.exe treinar_epi.py --somente-auditar
```

Leia [Monitoramento e coleta](MONITORAMENTO_E_COLETA.md) e
[Treinamento de EPI](TREINAMENTO_EPI.md). Os backups e resultados antigos
mencionados nesses documentos permanecem apenas no computador de origem.
A [documentação anterior](docs/README_ORIGINAL.md) foi preservada como histórico;
para instalar e usar a versão atual, siga este README.

## Uso local e dados privados

O aplicativo inicia somente em `127.0.0.1:5000`. Não exponha esse servidor
diretamente à internet: o painel atual não implementa autenticação de usuários.
As capturas e fotos coletadas ficam no computador e estão ignoradas pelo Git;
ocorrências podem enviar imagens ao destinatário configurado no `.env`.

Para futuras alterações neste clone, revise `git status` e o conteúdo dos
arquivos antes de fazer commit. Não reutilize o histórico Git antigo que
incluía a `.venv` e não use `git add -f` para arquivos privados.
