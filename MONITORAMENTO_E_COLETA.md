> Atualização de 21/10/2026: as regras e comandos atuais estão em [Aprimoramento de IA](docs/APRIMORAMENTO_IA.md). O conteúdo datado abaixo preserva o histórico; métricas antigas não validam precisão industrial.

# Confirmação por pessoa e coleta de imagens

Implementação de 19/10/2026.

## Usar o painel

Reinicie o servidor:

    .\.venv\Scripts\python.exe main.py

Abra http://127.0.0.1:5000 e clique em Iniciar monitoramento.
Os campos de câmera e SMTP continuam sendo lidos do .env.

Selecione os EPIs obrigatórios, ajuste o tempo de confirmação e clique em
Salvar política. A política permanece em config_epi.json. Se você alterar
o tempo pelo painel, esse valor salvo tem prioridade sobre o valor inicial
EPI_CONFIRMACAO_SEGUNDOS do .env.

## Estados da verificação de EPI

- Detectado: o modelo encontrou um item associado à região da pessoa.
- Verificando ausência: o item ainda não foi detectado, e há imagem
  suficiente da região do corpo para continuar observando.
- Possível ausência: a condição persistiu por pelo menos 3 quadros e pelo
  tempo configurado, por padrão 3 segundos. Pode gerar ocorrência.
- Inconclusivo: modelo indisponível, classe sem suporte, região oculta,
  pessoa pequena/cortada ou associação ambígua. Não gera alerta de EPI.

As regras geométricas e a visibilidade da pose são filtros conservadores.
Não comprovam que uma região esteja livre de toda oclusão. Os IDs são
temporários, baseados na sobreposição das caixas; podem mudar em movimentos
rápidos, cruzamentos e oclusões. Não representam a identidade do funcionário.
Uma perda de detecção interrompe a confirmação. Por padrão, intervalos maiores
que 2 segundos entre observações reiniciam a contagem. Desde o ajuste de
20/10/2026, a duração medida do processamento pode ampliar essa tolerância,
com limite de 10 segundos; pausas arbitrárias e pessoas ausentes continuam
reiniciando a confirmação. Três observações continuam sendo obrigatórias.

Os alertas têm intervalo independente por pessoa, tipo e EPI. Uma nova
pessoa não fica bloqueada pelo alerta de outra. A postura deitada tem
confirmação própria de 2 segundos e 3 quadros; continua sendo um alerta
de possível queda, sem análise completa do movimento de queda.

Valores iniciais opcionais no .env:

    EPI_CONFIRMACAO_SEGUNDOS=3
    QUEDA_CONFIRMACAO_SEGUNDOS=2
    COOLDOWN_SEGUNDOS=60

## Coletar imagens para treinamento

Com a câmera transmitindo, clique em Coletar foto da câmera. Você pode
adicionar uma observação sobre EPIs e condições de iluminação.

Arquivos são salvos em amostras_epi/pendentes:

- JPG original, sem caixas e textos adicionados pelo monitoramento.
- JSON com data, resolução, observação e previsões apenas como referência.

As imagens coletadas não entram automaticamente no dataset, não são
rotuladas automaticamente, não disparam e-mail e não iniciam treinamento.
Revise e anote cada imagem antes de incluí-la no dataset. Separe cenas
relacionadas para evitar colocar quase a mesma foto em treino e avaliação.
A pasta de coleta está no .gitignore.

O botão fica indisponível sem uma imagem recente. A captura também é
recusada pelo servidor se a imagem estiver há mais de 3 segundos sem atualizar.

## Organização do código e testes

- main.py: câmera, inferência, rotas, coleta e notificações.
- epi_monitoramento.py: associação, IDs temporários e confirmação temporal.
- templates/index.html e static/: interface e controlador da página.
- tests/test_monitoramento.py: testes sem câmera ou SMTP reais.
- tests/servidor_demo.py: câmera simulada na porta 5001, com e-mail desativado.
- tests/test_painel.mjs: controlador JavaScript com DOM mínimo e HTTP real.

Executar testes Python:

    .\.venv\Scripts\python.exe -m unittest discover -s tests -v

Para o teste do controlador, inicie o servidor simulado em outro terminal:

    .\.venv\Scripts\python.exe tests/servidor_demo.py

Depois:

    node --test tests/test_painel.mjs

O teste do controlador usa fotos sintéticas temporárias. Ele não substitui
a conferência visual no navegador nem a avaliação com funcionários reais.
Nesta implementação passaram 20 testes Python e o teste do controlador
JavaScript. Uma passagem offline com YOLO e MediaPipe reais também gerou
um quadro, detectou uma pessoa e carregou as cinco classes de EPI, sem
usar a câmera ou enviar notificações.
A verificação visual desta implementação foi bloqueada pela ferramenta de
controle do computador, que não conseguiu confirmar a URL da janela.

## Backup e retorno

A versão anterior foi copiada antes das alterações para:

    backups/monitoramento_antes_confirmacao_20261019/

Essa pasta contém main.py, .env.example e .gitignore anteriores. Para voltar
ao comportamento anterior, pare o servidor e reponha o main.py desse backup
na raiz do projeto. Os novos módulos e arquivos de interface podem permanecer
na pasta, pois o main.py anterior usa a página embutida.

O .env com credenciais e os modelos treinados não foram alterados.

## Ajuste de óculos em 19/10/2026

As capturas enviadas mostravam dois problemas: a confiança do epi.pt para
óculos ficava abaixo de 0,5 e a associação aceitava o item apenas na faixa
superior de 40% da pessoa. Em um close de rosto, os olhos podiam ficar fora
dessa faixa.

Agora a associação usa a posição dos olhos, obtida por detecção local do
rosto. Rosto cortado, quase de perfil ou evidência fraca não confirma
ausência. Uma indicação de óculos com confiança entre 0,15 e 0,5 deixa
a avaliação inconclusiva, sem comprovar que o item foi usado.
Para marcar presença, o limite continua em 0,5 e a caixa precisa coincidir
com a região dos olhos.

O modelo antigo treinamento_epi-2 é utilizado como uma segunda verificação
apenas da classe óculos. A seleção e o limite dos demais EPIs são mantidos.
O modelo principal epi.pt não foi substituído.

É possível configurar outro modelo adicional no .env:

    OCULOS_MODEL_PATH=runs/detect/treinamento_epi-2/weights/best.pt

Reinicie o servidor após uma alteração. Com óculos selecionado, o painel
informa quando a verificação adicional está ativa.

Validação offline com os recortes da câmera nas cinco capturas fornecidas:

| Imagem | Conteúdo observado | Resultado corrigido |
| --- | --- | --- |
| 1 | Com óculos | Detectado |
| 2 | Com óculos, de frente | Detectado |
| 3 | Com óculos, rosto virado/cortado | Inconclusivo, sem alerta |
| 4 | Sem óculos | Possível ausência |
| 5 | Com óculos | Detectado |

O fluxo foi exercitado em três observações por imagem com tempo de
confirmação acelerado para o diagnóstico; os testes unitários verificam
separadamente a confirmação normal de três segundos. Não houve acesso à
câmera nem envio de e-mail. Os recortes não foram usados para treinamento
e não constituem um conjunto independente de avaliação.

Diagnósticos locais estão em diagnosticos/oculos_20261019, fora do Git.
O código anterior a esse ajuste está em backups/antes_ajuste_oculos_20261019.
Para retornar, pare o servidor e reponha main.py e epi_monitoramento.py
desse backup. Nenhum peso de modelo nem credencial foi alterado.

## Correção da avaliação de quedas em 20/10/2026

A regra anterior classificava praticamente todo tronco com inclinação de até
60 graus como em pé, a menos que a caixa da pessoa fosse muito larga.
Inclinações intermediárias, pontos coincidentes e algumas leituras inválidas
podiam acabar rotuladas como em pé. Também eram exigidos os dois lados do
tronco, prejudicando a avaliação de pessoas deitadas de lado.

Agora:

- Os marcos precisam ser finitos, visíveis e separados por uma distância mínima.
  Um lado do tronco suficientemente visível permite a avaliação lateral; lados
  contraditórios deixam a postura inconclusiva.
- A inclinação é calculada em pixels, considerando largura e altura reais,
  inclusive quando a câmera entrega uma resolução diferente da solicitada.
- A faixa de até 30 graus pode indicar em pé. A partir de 55 graus pode indicar
  deitada; entre 45 e 55 graus também se exige caixa mais larga, com proporção
  de pelo menos 1,15. As demais situações ficam inconclusivas. Uma caixa larga
  sozinha não comprova queda. Pernas verticais visíveis em uma caixa alta podem
  indicar uma pessoa curvada, deixando a leitura inconclusiva.
- A pose recebe uma margem de 15% ao redor da pessoa. Os marcos retornam ao
  referencial da caixa original, preservando a associação dos EPIs.
- A confirmação usa o instante da obtenção do quadro. A tolerância entre
  observações acompanha o processamento medido, limitada a 10 segundos;
  não se confunde automaticamente uma pausa da câmera com processamento lento.
- O painel mostra inclinação estimada, motivo de leitura inconclusiva e
  progresso em quadros/segundos da confirmação. Há um aviso de processamento
  lento acima de 2 segundos por quadro.

Esses limiares são heurísticos, não uma calibração validada no ambiente do
outro computador. O sistema continua alertando **possível queda por postura
deitada persistente**, não comprovando um movimento de queda nem um acidente.
Não foi realizado treinamento novo e os modelos de EPI não foram substituídos.

Posicione a câmera aproximadamente nivelada e com o corpo inteiro visível.
Uma pessoa deitada em direção à câmera pode parecer vertical na imagem 2D;
vistas de cima, oclusões e enquadramentos cortados também exigem avaliação real
da instalação. Nesses casos, envie uma captura do painel e os valores de
inclinação/quadros por segundo para diagnosticar a cena. Não simule uma queda
perigosa: use imagens ou uma pessoa já deitada em uma posição segura.

Validação automatizada: 46 testes Python, incluindo geometrias sintéticas em
resoluções diferentes, pose ausente/contraditória, pessoa curvada e uma câmera
simulada com 3 segundos de inferência por quadro. Isso não constitui uma
avaliação de precisão com quedas reais. O controlador JavaScript também testa
a apresentação da postura inconclusiva e do progresso de confirmação.

Backup anterior ao ajuste:

    backups/antes_correcao_quedas_20261020/

Para retornar localmente, pare o servidor e restaure main.py,
epi_monitoramento.py e static/painel.js desse backup. As credenciais e os pesos
dos modelos permaneceram inalterados. No GitHub, o commit anterior ao ajuste
de quedas é b89b7e2, que preserva a versão publicada em 19/10/2026.
