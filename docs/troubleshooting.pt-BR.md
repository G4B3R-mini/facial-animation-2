# Solução de problemas do pipeline facial do Blender

| Sintoma | O que inspecionar primeiro | Resposta recomendada |
| --- | --- | --- |
| O rig aparece no cabelo / na região facial errada | Malha selecionada, dentes nomeados, boca medida e pivô | Passe `--obj` e nomes explícitos para as partes dentárias. Não confie na quantidade de vértices da cabeça. |
| Lábio inferior irregular ao girar a mandíbula | Corte automático da costura e medição da boca interna em relação à abertura visível | Compare uma nova construção da fonte com `--no-split-seam`; para bocas visivelmente abertas, compare também `--mouth-mode aperture`. |
| A mandíbula para de abrir após um ângulo pequeno | Restrição Limit Rotation do osso da mandíbula em `face_rig` | Informe a amplitude efetivamente avaliada; corrija a medição antes de ampliar um limite de proteção. |
| Os lábios se esticam como uma membrana | Faces que conectam os lábios superior/inferior, pesos da mandíbula e cavidade | Diagnostique a malha avaliada; cortar a costura nem sempre é a solução. |
| Os cantos se rasgam | Variação de peso por face **e** alteração da área avaliada | Use o auxiliar de comissura somente em faces de pele confirmadas que conectam as bordas; exclua os dentes. |
| Os dentes aparecem através da pele | Posicionamento dos dentes de frente e de lado e vedação dos lábios | Corrija a posição na fonte, teste diferentes forças de vedação e reconstrua uma cópia. |
| A boca vira um bloco cinza no QA | Cor de exibição na viewport do material sem textura | Faça-a corresponder à Base Color do shader e diferencie problema de sombreamento de problema de geometria. |
| Canais de olhos/sobrancelhas existem, mas não funcionam | Objetos separados, papéis das shells e deltas reais das keys | Prepare ou vincule essas partes explicitamente. A quantidade de keys não comprova funcionalidade. |
| Cílios flutuam ao piscar | Shells dos cílios e deltas de piscada gerados | Inspecione `attach_lashes.py` e transfira apenas o movimento pretendido das pálpebras. |
| O Rhubarb falha | Formato WAV, caminho do executável e saída de erro | Exporte um WAV válido e use o executável instalado; não prossiga após uma falha. |
| O rosto errado aparece após reanimação | Malha selecionada e perfil de construção correspondente | Use `--obj`; não meça novamente uma geometria já cortada nem reutilize o perfil de outro personagem. |
| Sem áudio | Faixa de som, caminho absoluto do WAV, dispositivo de áudio e configurações de mudo | Mantenha o arquivo acessível e confira a reprodução real. |
| O arquivo de referência não corresponde ao inspecionado | Janela do Blender, caminho do arquivo, estado não salvo e porta MCP | Capture um snapshot do arquivo ao vivo correto; verifique o endpoint de execução, não apenas o de status. |

## Regras de geometria

Os pesos usam as coordenadas de Basis. Vedar os lábios primeiro pode colocar as
duas bordas na mesma altura e eliminar a distinção entre a borda superior e a
inferior. Depois de dividir a topologia, recalcule os IDs dos componentes e
todos os dados indexados por vértice. Vértices coincidentes na costura podem
ser intencionais; soldá-los pode fechar uma boca que deveria animar.

Mantenha os dentes superiores rígidos em `head` e os inferiores rígidos em
`jaw`. Use um modificador Armature e um grupo de vértices com peso total para a
língua. Evite parentar aos ossos enquanto edita o rig em repouso. Qualquer
edição de geometria em uma malha com shape keys deve levar em conta todas as
keys afetadas, não apenas Basis.

Não use subdivisão da cabeça inteira como reparo rotineiro de deformação: ela
pode encolher a cabeça ao redor dos dentes ajustados ou alterar o interior da
boca. Primeiro diagnostique os pontos de referência, os pesos, as costuras e as
interações dos drivers. A falta de topologia para deformação pode ser relevante,
mas um resultado ruim não prova que a topologia seja a causa.

## Escopo e aprovação

As verificações numéricas podem passar mesmo que o rosto pareça errado. Também
podem sinalizar uma expressão neutra que mostra os dentes intencionalmente.
Preserve o relatório de falhas, mostre o resultado e diferencie aprovação visual
de aprovação em todas as verificações. As configurações aceitas de boca e
vedação de um personagem não são padrões para todas as cabeças. Se várias
tentativas deixarem de melhorar o resultado, explique o problema restante e
combine um ajuste manual específico ou uma mudança de escopo.

O caminho arquivado de ajuste canônico e o assistente antigo de marcadores não
são o fluxo de trabalho principal. O código Unity é um ponto de partida
opcional de integração, com requisitos adicionais de projeto/pacote; uma prévia
no Blender não certifica um Avatar do Unity.
