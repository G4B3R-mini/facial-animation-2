# Do modelo a um personagem falante no Blender

Este fluxo usa seu próprio modelo e partes faciais posicionadas manualmente. Ele
não cria modelos 3D, compra créditos de geração nem fornece cabeças, dentes,
texturas, vozes ou animações licenciadas. Use a ferramenta de geração de modelo
ou o fluxo de modelagem que preferir. O rig e as etapas do Rhubarb são executados
localmente.

## 1. Criar e preparar a fonte

Mantenha downloads e arquivos de trabalho em `work/<character>/`, diretório
ignorado pelo Git. Crie um personagem com rosto legível e geometria suficiente
ao redor dos lábios e das pálpebras para permitir deformação. Uma abertura
visível da boca facilita a inspeção. Preserve a exportação em quads, se o
gerador fornecer uma; uma prévia GLB pode estar triangulada. A triangulação,
sozinha, não prova que o modelo não funcionará.

Importe o modelo no Blender e preserve o download original. Oriente o personagem
com **Z para cima e o rosto voltado para -Y**. `--align` desloca a linha média
para x=0; não gira um modelo orientado com Y para cima nem normaliza seu
tamanho. Confira as transformações aplicadas.

| Parte | Nome sugerido | Preparação / comportamento |
| --- | --- | --- |
| Pele facial, cabeça e pescoço | `head` | Alvo explícito do rig; preserve a aparência neutra |
| Cabelo / roupas | `hair` e nomes distintos | Mantenha separados; não recebem skinning facial automaticamente |
| Dentes/gengiva superiores | `upper_jaw` | Ajuste dentro do lábio superior; ficam rígidos na cabeça |
| Dentes/gengiva inferiores | `lower_jaw` | Ajuste abaixo dos dentes superiores; ficam rígidos na mandíbula |
| Língua | `tongue` | Posicione dentro da arcada inferior; acompanha o osso da língua |
| Olhos | `eye_L`, `eye_R` durante a preparação | Para detecção automática, inclua-os como shells desconectadas na cabeça |
| Sobrancelhas / cílios | Nomes descritivos | Prepare explicitamente; objetos separados não são animados automaticamente |

Posicione os dentes e a língua nas **vistas frontal e lateral**. Confira a
profundidade além da largura: arcadas que parecem corretas de frente podem
atravessar os lábios de perfil. Não parentar as partes dentárias aos ossos de um
esqueleto temporário.

Para detecção automática de olhos/sobrancelhas, selecione essas malhas, selecione
`head` por último e use **Object > Join** (`Ctrl+J`) em uma cópia de trabalho.
Isso cria um único objeto com shells desconectadas; não una nem solde os globos
oculares à pele. Mantenha cabelo e roupas separados. A classificação continua
sendo heurística: confira o relatório e os ossos de olhos/sobrancelhas
resultantes. Shells pequenas de cílios podem precisar do auxiliar opcional para
cílios. Se precisar manter os objetos separados, faça o bind ou transfira os
pesos deliberadamente; a CLI básica não faz essa integração.

Salve como `work/<character>/source.blend`, com as texturas incorporadas ou
disponíveis em caminhos acessíveis. Audite essa cópia:

```powershell
blender -b work/character/source.blend --python-exit-code 1 `
  --python scripts/face_pipeline/audit_scene.py -- work/character/audit.json --obj head
```

Use o caminho do executável do Blender se `blender` não estiver no `PATH`. O
auxiliar informa inventário, sombreamento, fragmentação e possíveis problemas
de boca/orientação. Estimativas de borda e caixa delimitadora são indicações
para inspeção, não verdades anatômicas. Corrija problemas reais de
posicionamento; não gere outro modelo apenas por causa de um aviso.

## 2. Criar um rig para revisão

Na raiz do clone:

```powershell
.\rig.ps1 .\work\character\source.blend
```

O comando grava `source_rig.blend` e `source_rig.json` ao lado da fonte. Por
padrão, usa `head`, `upper_jaw,lower_jaw` e `tongue`, mantém a costura intacta e
solicita expressões de rascunho ARKit/VRChat. Use `-Object`, `-Teeth` e
`-Tongue` para nomes diferentes; `-NoTongue` omite a língua gerada/vinculada;
`-Basic` omite o conjunto expandido de expressões. `-Align` e
`-WeldCoincident` são opcionais.

Se uma boca visivelmente aberta for classificada incorretamente como
invaginada, esta é uma **opção candidata para comparação**, não uma configuração
universal:

```powershell
.\rig.ps1 .\work\character\source.blend -MouthMode aperture -SealRest 0.5
```

O padrão do wrapper é `-SeamMode Keep`. `Split` habilita explicitamente um
corte; `Auto` usa a heurística antiga da CLI. Só divida a costura se a inspeção
indicar que isso é adequado. Uma cavidade real pode não ter um loop de borda e
ainda assim estar aberta. Ajuste a vedação dos lábios em repouso entre 0 e 1
para cada modelo. Mantenha separadamente a melhor opção aprovada.

Equivalente direto e portátil do Blender (funciona sem PowerShell):

```sh
blender -b work/character/source.blend --python-exit-code 1 \
  --python autorig.py -- --obj head --teeth upper_jaw,lower_jaw \
  --tongue-object tongue --no-split-seam --arkit \
  --out work/character/source_rig.blend --json work/character/source_rig.json
```

Código de saída 0 significa que todas as verificações numéricas passaram.
Código 1 ainda pode produzir um arquivo para revisão e um relatório JSON;
inspecione `verify.failed` em vez de considerar o resultado aprovado.
Não há garantia de que o rig tenha 52 expressões úteis; canais sem anatomia ou
componentes compatíveis são informados como vazios. As cabeças de exemplo e os
testes locais anteriores não fazem parte do repositório público.

## 3. Inspecionar antes de testar a voz

Compare a fonte neutra, o rig neutro, a mandíbula em 9/18 graus, uma piscada e
alguns visemas a uma distância de conversa. Confira o **limite da restrição** da
mandíbula: algumas medições automáticas limitam o movimento abaixo da rotação
solicitada. `--open-deg` define o ângulo de verificação, não o limite da
mandíbula.

```powershell
blender -b work/character/source_rig.blend --python-exit-code 1 `
  --python scripts/face_pipeline/diagnose_rig.py -- work/character/diagnosis.json --obj head
blender -b work/character/source_rig.blend --python-exit-code 1 `
  --python scripts/face_pipeline/qa_render.py -- work/character/qa --obj head --closeup
python scripts/face_pipeline/make_sheet.py work/character/qa --kind bust
```

O auxiliar de montagem de folhas usa Pillow no Python comum. Os outros dois
scripts são executados pelo Python incorporado ao Blender. Consulte
[Diagnósticos](diagnostics.pt-BR.md). Inspecione as imagens, não apenas as
pontuações. Os metadados de QA registram a cabeça, as poses geradas e o limite da
mandíbula. Execute essas ferramentas em cópias no modo de fundo; câmera, cores
de exibição dos materiais e poses temporárias fazem parte do estado de QA.

Se o usuário forneceu um rig existente como referência, compare o estado real
salvo ou capturado em snapshot. Não reduza a amplitude da mandíbula para
esconder deformações.

## 4. Fornecer uma voz de amostra e animar

Use um clipe WAV da voz que deseja testar. Passe o **rig aprovado**, não a fonte
bruta, para preservar a geometria, os pesos e os corretivos aceitos:

```powershell
.\lipsync.ps1 .\work\character\voice.wav -Rig .\work\character\source_rig.blend
```

O comando executa o Rhubarb e grava `source_rig_voice_lipsync.blend` e
`source_rig_voice_lipsync.rhubarb.json` ao lado do rig. Ele reutiliza o perfil
incorporado por `autorig.py`; em arquivos antigos, passe o perfil correspondente
com `-Profile rig.json`. Use `-Output path.blend` para outro destino e
`-Fps 30` para definir os quadros por segundo (FPS). Para fala em outros
idiomas, use `-Recognizer phonetic`. O reconhecedor padrão PocketSphinx do
Rhubarb é destinado ao inglês.

Para uso repetido, copie `pipeline.example.json` para o arquivo ignorado
`pipeline.local.json` e configure nele o `rig` aprovado e os caminhos dos
executáveis. Depois, basta fornecer o áudio:

```powershell
.\lipsync.ps1 .\work\character\voice.wav
```

Os argumentos da linha de comando têm prioridade sobre a configuração local.
Os executáveis também podem ser encontrados por `BLENDER_PATH` / `RHUBARB_PATH`
ou pelo `PATH`. Caminhos na configuração local são relativos à raiz do clone;
caminhos explícitos na linha de comando são relativos ao diretório atual.
Alterar `-Rig` não reutiliza um perfil configurado para outro rig.

Em outros shells, execute as mesmas etapas diretamente:

```sh
rhubarb -f json -o work/character/voice.rhubarb.json work/character/voice.wav
blender -b work/character/source_rig.blend --python-exit-code 1 \
  --python scripts/face_pipeline/reanimate.py -- work/character/talking.blend \
  --cues work/character/voice.rhubarb.json --audio work/character/voice.wav --fps 30
```

## 5. Revisar o arquivo animado

Abra o `.blend` de saída, vá ao quadro 1 e reproduza. Ele inclui a faixa de som
e as ações geradas para mandíbula, língua e visemas, além de piscadas/olhar/
sobrancelhas quando esses ossos e formas existem. Isso cria uma cena do Blender,
não um vídeo codificado.

Confira o fechamento dos lábios (M/B/P), vogais abertas, F/V, vogais
arredondadas e pausas. Confirme que a faixa de som existe, que o áudio do Blender
está habilitado e que o FPS está correto. Atrasos na reprodução não indicam
necessariamente um erro nas marcações; use reprodução sincronizada com áudio ou
renderize um vídeo curto para distinguir desempenho da viewport de erro de
sincronização. Mantenha o WAV acessível: ele é referenciado pelo caminho e não
há garantia de que esteja incorporado ao arquivo blend.

Se a fala precisar de ajustes, o auxiliar direto de animação aceita
`--jaw-scale` e `--viseme-scale`. Ele substitui ações de animação, não a
geometria. Não execute `autorig.py` em um rig aprovado apenas para trocar o
clipe de voz.

Registre a fonte aprovada, as opções, o relatório, o rig, o áudio, as marcações
e os resultados no diretório de trabalho ignorado do personagem. Consulte
[Publicação](publishing.pt-BR.md) antes de compartilhar o repositório; o código
e os recursos do usuário têm proprietários distintos.

## 6. Continuar com um corpo e Unity

Depois de aprovar a prévia, prenda manualmente a cabeça ao corpo rigado.
Entregue o arquivo montado ao agente para combinar os esqueletos e exportar FBX;
em seguida, solicite a configuração da cena Unity. Siga o
[assistente de etapas](agent-wizard.pt-BR.md) e a
[integração com Unity](unity.pt-BR.md).
