# Integração com Unity

## Instalar e usar a janela de configuração

Gere o pacote importável com `python scripts/build_unity_package.py`. Com o
projeto aberto, clique duas vezes em `dist/TripoFaceRig-Unity.unitypackage` e
clique em **Import**. A janela será aberta após a compilação dos scripts; para
reabri-la, use **Tools > Tripo Face Rig > Character Pipeline**. O pacote contém
apenas os componentes de execução mantidos e ferramentas genéricas do editor.
GUIDs estáveis dos scripts preservam referências no projeto de referência. Se
outro projeto já tiver cópias instaladas com GUIDs ou caminhos diferentes, use
`install-unity.ps1` para atualizá-las no lugar, em vez de importar classes
duplicadas.

Atribua um prefab ou uma instância de cena do modelo, uma voz de teste e um
clipe de repouso Humanoid. No painel Project, expanda um FBX de animação e
arraste o subasset **AnimationClip** para o campo. Use **Add speaking
animation** para cada clipe de fala/gesto. As animações precisam ser importadas
como Humanoid, compatíveis com o tipo de rig do modelo. Forneça o JSON do
Rhubarb ou procure o executável do Rhubarb para que o assistente gere as
marcações a partir do WAV. O botão de download abre a página oficial de versões.

Clique em **Create and wire speaking character**, salve a cena e pressione
Play. O assistente cria uma pasta exclusiva em `Assets/TripoFaceRigGenerated`,
com controller do Animator, máscara da parte superior do corpo, cópias dos
clipes de animação e perfil de atuação. Ele atribui o controller, conecta todos
os componentes de execução e preserva o asset do controller anterior. Uma nova
construção cria outra versão; não sobrescreve os assets de outro personagem. As
cópias das animações removem curvas explícitas de ossos/blendshapes e eventos
de animação para evitar conflito com os drivers faciais.

A camada base do corpo repete o repouso selecionado com IK dos pés. Uma camada
Override limita os gestos ao torso/braços/dedos e exclui cabeça/pernas. A análise
da fala agenda acentos gestuais e controla seus envelopes, usando a mesma
abordagem de execução do personagem de referência coordenado. Por padrão, os
segmentos de gesto usam até os três primeiros segundos de cada clipe; ajuste
início/acentuação/sustentação/fim no perfil gerado para seus clipes. A opção
**Existing performance** copia um perfil criado anteriormente, preservando
seus marcadores de segmento e notas de atuação específicas da amostra. O pacote
incluído não contém os modelos, vozes ou clipes de movimento do personagem de
referência.

O repouso preserva explicitamente o valor neutro de mandíbula Humanoid
importado. Remover todas as curvas da mandíbula pode fazer com que a pose
muscular padrão do Unity abra uma mandíbula fechada. A articulação da boca
continua sob responsabilidade do reprodutor de blendshapes faciais.

Os scripts de execução mantidos em `unity/` incluem a implementação coordenada
atual de boca, olhar e expressões do projeto de referência. Instale somente o
subconjunto selecionado por `install-unity.ps1`. Scripts antigos do editor
nesse diretório são ferramentas históricas de configuração específicas do
personagem; copiar a pasta inteira pode incluir classes de editor duplicadas ou
dependências opcionais do uLipSync.

## Importar e pré-visualizar

1. Importe o FBX exportado e os arquivos de textura; habilite a importação de
   blendshapes. Configure Rig como Humanoid e verifique o Avatar. Mapeie a
   cabeça real do corpo, mas, se houver ossos oculares duplicados e sem uso no
   corpo, selecione os ossos oculares funcionais do rosto para Left Eye/Right
   Eye. Confira também o mapeamento de Jaw, que pode ter a mesma ambiguidade.
2. Importe o WAV de voz e o JSON do Rhubarb correspondente. Para análise, use
   uma configuração de importação de áudio que disponibilize amostras PCM
   acessíveis (`Decompress On Load`).
3. Instancie o personagem na cena desejada. Preserve o controller do Animator
   do corpo; confira escala, altura em relação ao chão, materiais e espaços de
   cor das texturas.
4. Use a janela de configuração descrita acima. Agentes podem chamar
   `CharacterPipelineSetup.Build(model, voice, cues, idle, speakingClips)` para
   gerar o controller e a configuração completa, ou `Configure(root, clip, cues)`
   para conectar somente rosto/áudio preservando um controller existente do
   corpo. A cena será marcada como modificada; revise as alterações e salve-a.
5. Entre no modo Play. `SpeechGestureDriver` inicia o clipe depois que a cena
   estabiliza; `RhubarbVisemePlayer` lê as marcações usando o relógio do mesmo
   `AudioSource`. Com o som, revise o fechamento da boca, língua/dentes, olhar
   e piscadas. Saia do modo Play antes de salvar.

## Responsabilidade pelos canais e movimento corporal

| Canal | Responsável |
| --- | --- |
| Articulação da fala | `RhubarbVisemePlayer` |
| Olhar da cabeça/olhos e piscadas | `ConversationalGaze` |
| Expressões e combinação final do sorriso | `ConversationExpressionDriver` |
| Análise do áudio, tempo das frases e acionamento dos gestos | `SpeechGestureDriver` |
| Intensidade dos gestos de torso/braços | `SubtleBodyDriver`, quando há uma camada adequada |

`FaceMeshUtil` seleciona as formas que realmente deformam a malha; cópias
inertes de shapes no cabelo não são alvos válidos. Inclua renderers separados
de dentes/língua quando eles deformarem. Confira em cada modelo os canais
ausentes, inclusive `tongueUp`. Não suponha que todas as keys com nomes ARKit
tenham dados úteis. Drivers do Blender não são preservados como drivers do
Unity; shapes exportadas relacionadas à mandíbula precisam mover a geometria
dentária relevante.

A janela de configuração cria um controller a partir dos clipes corporais
fornecidos pelo usuário. A API `Configure`, sozinha, preserva um controller
existente. `SpeechPerformanceProfile` armazena segmentos de gestos e notas
opcionais de atuação para a gravação real. Evite curvas faciais pré-gravadas ou
animação da mandíbula que concorram com a articulação em execução. A
configuração desativa sistemas antigos conhecidos que escrevem no rosto, mas o
agente também precisa inspecionar camadas personalizadas do Animator e outros
componentes do projeto.

`RuntimeLipSyncService` está disponível para futura integração com WAV gerado.
Uma prévia com amostra fixa usa JSON pré-calculado e não precisa do Rhubarb
durante a execução. Para distribuir reconhecimento em execução, é preciso
incluir a distribuição completa do Rhubarb para a plataforma e seus avisos de
licença; ela não vem incluída nem é baixada automaticamente.

## Limites da validação

Um script que compila, um Avatar válido ou uma cena configurada não equivalem à
aprovação artística. Capture um teste curto no modo Play, a uma distância de
conversa e em close do rosto; confira os renderers-alvo, os coeficientes que
mudam, a deformação real e a sincronização do áudio. Informe versões de
editor/plataforma sem suporte e qualquer falta de acesso às ferramentas ao
vivo. Não inclua cenas, clipes, modelos, presets ou caminhos absolutos
específicos do projeto neste repositório público.

Os componentes do pacote compilam com Unity 6000.3.10f1. O assistente também
passou por um teste de configuração no editor em um personagem temporário numa
cena de prévia, usando o modelo Humanoid, o clipe de repouso e os clipes de
gesto do projeto de referência. O teste verificou camadas do controller,
máscaras, segmentos de gesto válidos e referências dos componentes. A
qualidade audiovisual da reprodução contínua ainda precisa ser avaliada com o
modelo e os clipes escolhidos.
