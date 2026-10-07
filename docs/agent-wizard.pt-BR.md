# Pipeline de personagem guiado por prompts

Use a mesma habilidade `$tripo-face-rig` para cada tarefa. O agente identifica
a etapa atual a partir dos arquivos e do pedido; não é necessário memorizar os
comandos. Ele registra entradas, configurações, saídas e estado da revisão em
`work/<character>/handoff.md` — um caminho ignorado pelo Git — para que outra
sessão possa continuar o trabalho.

## Tarefa 1: da cabeça preparada à prévia falante

> Faça o rig da cabeça preparada em `work/character/source.blend` e anime-a com
> `work/character/voice.wav`. Verifique os pré-requisitos, diagnostique as
> deformações e me entregue um arquivo Blender com a fala para revisão.

O agente executa `doctor.ps1 -Stage Head`, que informa se faltam os executáveis
do Blender ou do Rhubarb, além de fornecer endereços para download e instruções
de configuração. O Blender está disponível na [página oficial de download](https://www.blender.org/download/).
Extraia o arquivo completo da [versão do Rhubarb](https://github.com/DanielSWolf/rhubarb-lip-sync/releases),
incluindo os recursos do reconhecedor. Configure os caminhos dos executáveis
na configuração local ou use `-Blender` / `-Rhubarb`. Não é necessário instalar
Python globalmente para criar o rig: o Blender fornece o próprio Python.
As folhas de contato opcionais precisam do Pillow.

O agente inspeciona as partes do modelo, cria o rig, verifica a deformação da
mandíbula, das pálpebras e dos dentes, gera as marcações do Rhubarb e cria um
arquivo `.blend` animado separado. Um único pedido autoriza as etapas de rig e
áudio; não é obrigatório pedir aprovação entre cada comando. Se uma verificação
de deformação falhar, o agente deve diagnosticar e registrar o problema, não
ocultá-lo para concluir o assistente. Após inspecionar o resultado, ele pode
produzir uma prévia de revisão claramente identificada com as limitações
conhecidas.

Abra a prévia, vá ao quadro 1 e reproduza com som. Verifique lábios, dentes,
língua, piscadas e pausas de frente e de lado. Com ferramentas ao vivo do
Blender, o agente pode iniciar a reprodução, percorrer os quadros e capturar
poses representativas; uma verificação numérica, por si só, não permite afirmar
que o agente ouviu o áudio ou assistiu à reprodução contínua. A aprovação visual
do usuário é o ponto de transferência, não a quantidade de verificações
automáticas aprovadas.

## Tarefa manual: prender a cabeça aprovada a um corpo

No Blender, prenda a cabeça aprovada ao corpo rigado escolhido e salve um novo
arquivo `assembled.blend`. Preserve as shape keys faciais, os pesos e o
armature facial. Posicione juntos a cabeça, o cabelo e as partes dentárias.
Mantenha o rig original do corpo e anote o nome do osso da cabeça. Remova ou
oculte intencionalmente a cabeça original; um corte Boolean não aplicado é
compatível se for identificado explicitamente. Não inclua os objetos cortadores
na exportação do personagem. Não junte a malha do rosto à malha do corpo se isso
destruir as shape keys faciais. Quando estiver pronto, devolva o arquivo ao
agente.

## Tarefa 2: do personagem montado ao FBX para Unity

> Prendi a cabeça aprovada ao corpo em `work/character/assembled.blend`.
> Inspecione o arquivo, conecte os esqueletos e exporte um FBX pronto para Unity.

O agente inventaria os armatures, os nomes dos ossos, o skinning e as
restrições de fixação. Ele informa os nomes reais a `export-unity.ps1`; os nomes
do exemplo abaixo não são valores universais:

```powershell
.\export-unity.ps1 .\work\character\assembled.blend -BodyArmature Armature -FaceArmature face_rig -HeadBone Head
```

Um corte Boolean intencional na cabeça do corpo pode ser finalizado com
`-ApplyBodyBooleans <body-mesh-name>`. O auxiliar se recusa a descartar shape
keys ativas do corpo. Ele combina os armatures, parenta as raízes faciais ao
osso da cabeça do corpo, redireciona o skinning e os drivers corretivos e
verifica as posições faciais avaliadas e a quantidade de shape keys. Colisões
de nomes e transformações de bind não compatíveis geram erros explicativos.
Antes da exportação, prenda acessórios rígidos ao osso apropriado usando pesos
completos; parentar apenas o objeto não é suficiente. Confira no relatório a
lista de malhas para identificar partes ausentes.

As saídas são um novo `.blend`, um `.fbx`, um `.export.json` e arquivos de
textura. O FBX representa um personagem neutro para execução, sem uma ação de
fala pré-gravada que concorra com os drivers de boca do Unity. A prévia falante
original continua disponível separadamente. Restrições e drivers do Blender
não se tornam componentes de execução do Unity: após importar, verifique as
variações de blendshape, a resposta da mandíbula e dos dentes e o mapeamento dos
olhos. Uma gravação bem-sucedida do FBX não comprova que a deformação funciona.

## Tarefa 3: importar e configurar o personagem em uma cena

> Importe o personagem exportado para meu projeto Unity em `<project path>` e
> configure-o na cena `<scene>` com este WAV de voz e o JSON do Rhubarb. Use o
> Animator do corpo e os componentes de rosto, olhar e expressão do repositório.

Consulte [Integração com Unity](unity.pt-BR.md). Execute
`doctor.ps1 -Stage Unity -UnityProject <path>`. Instale os scripts mantidos com
`install-unity.ps1 <path>`; revise scripts existentes que sejam diferentes
antes de usar `-UpdateExisting`. Importe o FBX, as texturas, o WAV e o JSON
correspondente para uma pasta do personagem em `Assets`. Use um Avatar Humanoid
válido, mantenha ou atribua o controller do corpo, instancie o modelo na cena
solicitada e use a janela genérica Character Pipeline ou o método público
`Configure(root, clip, cues)` por meio do Unity MCP.

O agente verifica compilação, Avatar, renderers deformáveis, referências dos
componentes, materiais, escala e responsabilidade de cada canal. Se houver
ferramentas ao vivo conectadas, ele executa um teste audiovisual no modo Play,
salva a cena ou o prefab solicitado e informa o que foi efetivamente testado.
Sem Unity MCP, ele pode preparar os arquivos e fornecer os passos exatos no
editor; a configuração da cena e a reprodução continuam pendentes até serem
feitas. O fluxo não adiciona automaticamente TTS, serviços de diálogo nem
animações pagas.

Registre explicitamente o estado da etapa: `preview ready`, `user accepted`,
`awaiting manual body attachment`, `FBX exported`, `Unity configured` ou
`Play-mode reviewed`. Não marque etapas posteriores como concluídas só porque
as anteriores já têm arquivos.
