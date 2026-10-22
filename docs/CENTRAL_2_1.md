# VigiaAI 2.1 — Central de Monitoramento

Implementação na branch `vigiaai-2.1-interface`, derivada de `melhoria-ia`.
Flask, pesos YOLO, MediaPipe, motor temporal, treinamento, coleta e notificações anteriores foram mantidos.
`main.py` continua sendo o ponto de entrada. Não há outro detector nem banco de dados novo.

## Abrir no computador

Pare versões anteriores do servidor antes de iniciar. No PowerShell, dentro do clone:

```powershell
.\iniciar_vigiaai.ps1
# CPU: .\iniciar_vigiaai.ps1 -CPU
```

Alternativa sem executar o arquivo PowerShell, neste computador já preparado:

```powershell
$pythonVigia = (Get-Content .runtime-python -Raw).Trim()
& $pythonVigia main.py
```

Abra **http://127.0.0.1:5000** no navegador do mesmo computador. O servidor permanece vinculado a
`127.0.0.1`; não o exponha à internet. O ambiente Python existente precisa ficar em caminho sem acentos
por uma limitação observada do MediaPipe 0.10.21. Para instalar em outro computador, siga
[o guia de IA](APRIMORAMENTO_IA.md). `.runtime-python` é configuração privada, não está no GitHub.

O painel anterior continua em **http://127.0.0.1:5000/legado**, incluindo coleta de imagens e o sistema
de SMTP original. As duas telas compartilham o mesmo monitor; não executam análises concorrentes.

## Vídeo gravado — fluxo principal

1. Selecione ou arraste um arquivo no navegador. O envio é para o Flask local.
2. Aguarde a verificação do primeiro quadro, formato, duração, FPS e resolução.
3. Confira os EPIs selecionados e clique em **Iniciar análise**. Na primeira utilização, a central propõe
   capacete e óculos; uma política já salva tem prioridade. Iniciar também aplica a seleção mostrada.
4. Acompanhe os quadros anotados, pessoas, equipamentos, estados inconclusivos e possíveis ocorrências.
5. Use **Pausar**, **Retomar**, **Reiniciar**, a linha do tempo ou **Rever trecho** nas ocorrências.
6. **Encerrar** libera o processamento e remove o upload temporário; os registros da sessão permanecem.

MP4, AVI, MOV, MKV e WebM são extensões aceitas, mas o codec precisa ser decodificado pelo OpenCV/FFmpeg
instalado. Um arquivo renomeado para `.mp4` não passa pela validação. A análise mostra JPEGs processados,
portanto não exige que o navegador reproduza nativamente o codec original. Não há áudio nessa visualização.
Por padrão são aceitos vídeos até 512 MB, 4 horas, 240 fps e 4096×2160 pixels.

Vídeos não são espelhados; a câmera mantém o espelhamento anterior. A mesma execução de `Monitor.executar`
faz detecção de pessoas, recortes, pose, associação de EPI, motor temporal, caixas e alertas em ambos os modos.
Uma prévia sem IA é identificada como tal até o primeiro quadro processado. Não existem ocorrências roteirizadas.

## Tempo, pausa e busca

- **Tempo do vídeo:** posição do quadro / FPS original; é a referência do motor temporal e dos eventos.
- **IA acumulada:** soma do tempo medido de análise dos quadros. Não inclui envio e toda a inicialização,
  espera de pausa ou todas as etapas de exibição; não é a duração original da gravação.
- **FPS de processamento:** taxa medida da etapa de leitura/inferência por quadro, excluindo a espera
  intencional de apresentação. A prévia no navegador é consultada aproximadamente a cada 120 ms e pode
  mostrar menos quadros que o detector processa. O estado é consultado aproximadamente a cada 350 ms.
- A execução de vídeo respeita no máximo o ritmo original; em computadores lentos pode demorar mais.
  O replay usa os timestamps originais e não simula perdas de quadros de uma câmera ao vivo.
- Pausar congela o avanço do vídeo após um eventual quadro já em processamento. O intervalo de pausa
  de relógio não vira movimento ou imobilidade artificial no tempo do vídeo.
- Buscar muda a posição, reinicia rastreamento, confirmações de EPI e todo o histórico temporal antes do
  próximo quadro. Um quadro do trecho é analisado e a execução fica pausada. Retome para reconstruir contexto.
- Reiniciar volta ao começo com contexto temporal novo. O histórico de ocorrências é preservado, com
  supressão de repetições próximas da mesma fonte, pessoa, classificação e conjunto de EPIs.
- O progresso representa a posição percorrida na fonte. Buscar não analisa os trechos pulados; isso é
  indicado ao chegar ao final. Não confunda 100% da posição com cobertura de todos os quadros após buscas.

## Câmera ao vivo

Selecione **Câmera ao vivo**, clique em **Buscar câmeras**, escolha um dispositivo que respondeu com imagem
e inicie. A busca verifica índices do backend, não usa `getUserMedia` do navegador. Câmeras virtuais podem
aparecer; a lista não atesta que sejam câmeras físicas. O padrão verifica índices 0 a 2. O dispositivo pode
ficar indisponível depois da busca; o erro aparece no painel. Pausa e busca temporal ficam desativadas no ao vivo.

Trocar de modo encerra a fonte anterior. Enviar outro vídeo ou escolher dispositivo durante uma análise
é recusado pelo backend até o encerramento. Há somente uma thread de inferência por processo Flask.
Não execute vários processos/workers Flask para a mesma central; não há coordenador entre processos.
Não presuma que um ambiente Work tenha acesso à câmera física do computador do usuário.

## Resultados e histórico

Contadores vêm do backend: pessoas no quadro, EPIs associados como presentes, verificações inconclusivas,
possíveis ausências, emergências visuais suspeitas e total de ocorrências registradas na sessão.
Uma caixa de EPI no quadro representa uma detecção; a associação ao trabalhador e sua condição são
mostradas no painel lateral. A cor de atenção também cobre estados inconclusivos; não significa confirmação.

Os pesos atuais têm cinco classes positivas e não comprovam ausência só por não detectar um item.
Possível ausência continua exigindo evidência explícita, região verificável e confirmação temporal.
Óculos comuns/protetores e condições industriais ainda dependem de revisão de dados e validação.
Queda/colapso e pessoa imóvel são suspeitas visuais para verificação humana, nunca diagnóstico de desmaio.

O histórico mantém as 200 ocorrências mais recentes em memória, com um contador total de registros aceitos.
É perdido ao reiniciar o servidor, como o histórico em memória anterior. **Exportar JSON** permite guardar
os registros localmente. Após remover o upload, o evento permanece, mas seu vídeo não pode ser reaberto
pela central. **Rever trecho** funciona com a fonte correspondente ainda selecionada, iniciando alguns
segundos antes do evento para permitir reconstrução de contexto; não reutiliza observações antigas.
Deduplicação por ID e janela temporal não substitui validação de identidade em cruzamentos.

Na central, e-mails reais e fotos de ocorrências são desativados por execução, mesmo que o `.env` tenha SMTP.
O painel clássico conserva o comportamento configurado do sistema anterior. Não há envio de detecções a
serviços de IA externos. CUDA e fallback CPU continuam sendo definidos pelo runtime existente.

## Arquivos privados e biblioteca

Uploads ficam em `%TEMP%/VigiaAI-2.1/<identificador-do-clone>/uploads`, fora do clone por padrão.
Os nomes em disco são UUIDs; nomes enviados são usados apenas como texto. O arquivo anterior é removido
ao substituir a fonte, trocar de modo ou encerrar. Arquivos gerenciados com mais de 24 h são limpos na
próxima inicialização ou envio, preservando a fonte ativa desta instância. Após fechamento abrupto pode
haver resíduos até essa limpeza; não há remoção garantida se o computador não voltar a executar o app.

Variáveis opcionais no `.env`:

| Variável | Padrão / função |
|---|---|
| `VIGIAAI_UPLOAD_MAX_MB` | 512; limite da requisição de upload. |
| `VIGIAAI_MAX_VIDEO_SEGUNDOS` | 14400; duração máxima. |
| `VIGIAAI_UPLOAD_TTL_SEGUNDOS` | 86400; retenção de resíduos, mínimo de 60 s. |
| `VIGIAAI_MAX_CAMERAS` | 3; quantidade de índices examinados, limitada a 8. |
| `VIGIAAI_MEDIA_DIR` | Opcional: raiz privada de arquivos temporários, configurada pelo responsável local. |

Não é possível escolher caminhos arbitrários por uma rota HTTP. A biblioteca opcional permite somente
arquivos dentro de `biblioteca_demo/`, cadastrados em `biblioteca.json` com autorização e licença declaradas.
Consulte [as instruções da biblioteca](../biblioteca_demo/README.md). Nenhum vídeo de terceiros foi incluído.
O manifesto e os vídeos são ignorados pelo Git. Os testes usam gravações sintéticas próprias, não dados de funcionários.

Mutações da central verificam origem, host local e cabeçalho próprio. Uploads simultâneos são recusados,
e controles de fonte são serializados. O aplicativo continua destinado ao uso local; não implementa
autenticação para exposição externa.

## Avaliação offline e testes

`avaliar_video.py` agora preserva a política salva e aceita seleção explícita de EPIs:

```powershell
& $pythonVigia avaliar_video.py caminho-autorizado/video.mp4 --epis capacete oculos --saida avaliacoes_privadas/previsoes.json
```

Use `--epis` sem itens para desativar EPIs intencionalmente em uma avaliação só de emergências.
Os arquivos de saída continuam sem imagens e sem SMTP. Crie previamente a pasta de saída.

```powershell
& $pythonVigia -m unittest discover -s tests -p 'test_*.py'
$env:VIGIAAI_PYTHON = $pythonVigia
node --test tests/test_painel.mjs tests/test_central.mjs
```

As novas suítes validam rotas, uploads, codec inválido, limites, nomes, prévia, controlador JavaScript,
pausa, busca, reinício, múltiplas fontes, EPI e pose integrados, histórico, limpeza, origem e notificações.
Os testes de controles usam fixtures explicitamente simuladas de modelos/câmera; não comprovam precisão.
Foi executado também upload/decodificação e pipeline com modelos reais em AVI sintético sem pessoas,
com política de capacete/óculos e CUDA. MP4 de três quadros também foi executado com os modelos reais em CPU. Esses testes não validam reconhecimento em trabalhadores.

O navegador automatizado deste ambiente não conseguiu acessar localhost e sua política bloqueou
arquivos locais `file:`. Não foi contornada essa restrição. A verificação visual e de usabilidade em um
navegador real continua necessária no computador de execução; testes DOM/Flask não equivalem a ela.
Ainda são necessários vídeos autorizados com pessoas/EPIs/atividades e eventos para medir acurácia,
falsos alertas, trocas de IDs e desempenho com múltiplas pessoas. Não houve treinamento novo nesta etapa.
