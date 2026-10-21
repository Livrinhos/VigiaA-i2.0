# Fontes e permissões — consulta em 21/10/2026

Nenhuma imagem/vídeo/anotação destas fontes foi baixada ou incluída. Não houve inspeção local de sua
qualidade. O quadro descreve o escopo declarado pelos publicadores e a revisão ainda necessária.

| Fonte primária | Adequação e limites | Condições encontradas | Uso efetivo |
|---|---|---|---|
| [Construction-PPE / Ultralytics](https://docs.ultralytics.com/datasets/detect/construction-ppe) | 1.416 imagens, helmet/goggles/person e ausências explícitas. Construção, com domínio distinto da fábrica; revisar pequenos óculos e itens vestidos. | Publicador declara AGPL-3.0; conferir obrigações e proveniência. | Nenhum; integração preparada. |
| [SH17 / autores](https://github.com/ahmadmughees/SH17dataset) | 8.099 imagens/17 classes, manufatura. Glasses exige revisão para separar proteção/óculos comuns. Ler IDs do YAML da versão. | CC BY-NC-SA 4.0; autores descrevem uso educacional/pesquisa/análise e imagens Pexels com termos adicionais. Não presumir implantação comercial autorizada. | Não integrado. |
| [UR Fall Detection / Universidade de Rzeszow](https://fenix.ur.edu.pl/~mkepski/ds/uf.html) | 70 sequências: 30 quedas e 40 atividades diárias. Usar RGB, sem vantagem de sensores indisponíveis na webcam. Quedas encenadas, domínio diferente. | CC BY-NC-SA 4.0 e uso acadêmico não comercial; autores pedem contato para uso comercial. | Não usado em treino/validação. |
| [NTU RGB+D / ROSE Lab](https://rose1.ntu.edu.sg/dataset/actionRecognition/) | Atividades como sentar/levantar/cair; Kinect e esqueleto diferente de MediaPipe exigem adaptação. | Restrições a uso comercial, redistribuição e derivados sem permissão expressa. | Não integrado. |

Mapeamento candidato de Construction-PPE, sujeito à conferência da versão: helmet→capacete,
vest→colete, goggles→oculos, gloves→luvas e ausências explícitas correspondentes. Não converter
`none` em ausência de todos os EPIs. Máscara deve continuar no esquema com dados anotados de fonte
autorizada. Boots/no_boots e outras classes exigem decisão explícita: adicionar ao final ou excluir com revisão.

Priorizar dados locais autorizados: capacetes de diferentes cores/vistas; bonés; óculos comuns, escuros e
protetores transparentes; sem óculos; diferentes pessoas, distâncias, baixa luz, oclusões e várias pessoas.
Manter negativos difíceis e inconclusivos. Não separar a mesma pessoa/sequência entre treino e teste.
Revisar imagens quase iguais e fotografias de banco repetidas entre fontes.

## Código original e dependências

Não foi localizado LICENSE no clone nem nas árvores GitHub inspecionadas. Em 21/10/2026 o usuário
confirmou que o autor é seu amigo e pediu melhorias, com escopo em Livrinhos/VigiaA-i2.0.
Esse relato autoriza esta contribuição específica; não estabelece licença geral nem comprova direitos
dos dados que produziram os pesos existentes. Não foi acrescentada uma licença fictícia.
Registrar termos com o autor antes de distribuição comercial.

[GitHub explica as limitações de repositórios sem licença](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).
[Ultralytics descreve AGPL-3.0 e alternativa Enterprise](https://docs.ultralytics.com/help/contributing/).
A autorização do amigo não substitui os termos de bibliotecas, pesos de base ou datasets de terceiros.
Pesos existentes foram preservados byte a byte; esta contribuição não adiciona pesos ou dados públicos.
