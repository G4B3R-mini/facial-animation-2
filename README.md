# Tripo Face RigTradução

Prepare uma cabeça de personagem gerada no Blender, construa um equipamento de rosto processual,
e teste-o falando um clipe de voz de amostra com Rhubarb Lip Sync.

O fluxo de trabalho pretendido é **cabeça preparada -> falando Blender preview -> usuário
prende a cabeça a um corpo manipulado -> agente conecta esqueletos -> FBX -> Cena Unity**.
Impulsione-o solicitando a habilidade do repositório Codex ou Claude; o agente executa o
comandos e verificações de pré-requisitos. Modelos, texturas, vozes e movimentos são seus.

Comece com o [presbítero impulsionado por prompt](docs/agent-wizard.md), incluindo exemplo
prompts para cada tarefa e a transferência manual de aderência do corpo. O
[Guia de unidade] (docs/unity.md) abrange os componentes reutilizáveis e a configuração de cena genérica.
O auto-contido [Blacksmith preparado-cabeça-exemplo](exemplos/README.md) mostra
como devem ser dispostos os dentes superiores, os dentes inferiores e os objetos da língua separados.

Para a janela de configuração do Unity, crie `dist/TripoFaceRig-Unity.unitypackage` com
`python scripts/build_unity_package.py`. Importá-lo, atribuir o seu modelo, voz,
clipes de animação ociosos e falantes, em seguida, clique em **Criar e enxame de caracteres de fala**.
Ele cria e atribui o controlador do Animador, máscara, perfil de fala e componentes.
Lançamentos do GitHub publicados são compilados e anexam o mesmo pacote automaticamente.

Trata-se de um pipeline experimental assistido por artistas. Detecção de boca e facial
pesos precisam de revisão visual por personagem. Nomes de expressão ou passando numérico
portões não garantem animação aceitável. O caminho mantido é o
equipamento processual; ajuste canônico legado/extensões não são o caminho recomendado.

## Requisitos

- Blender: o fluxo de trabalho atual foi exercido com **5.1.1**. Outras versões
  não são certificados; use a versão salvadora ou mais recente para arquivos de mistura fornecidos.
- [Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync): testado com
  1.14.0. Extraia a distribuição completa, incluindo recursos do reconhecedor.
- PowerShell 5.1+ no Windows, ou PowerShell 7 para outros sistemas, para os wrappers.
  Os comandos Direct Blender/Python também estão documentados; o macOS/Linux não é testado.
- Opcional regular Python 3 + Travesseiro para folhas de contato QA:
  `python -m pip install Pillow`. Os scripts principais são executados no Python do Blender.
- Conexão opcional do Blender MCP para inspeção ao vivo por um assistente.
  Nenhuma conexão MCP é necessária para compilações de linha de comando.

Coloque `blender` e `rhubarb` no PATH, defina `BLENDER_PATH` / `RHUBARB_PATH`, ou use
`-Blender` / `-Rhubarb` caminhos executáveis. Você pode armazenar padrões específicos da máquina
em ignorado `pipeline.local.json`; começar a partir de [pipeline.example.json](pipeline.example.json).

## Comece com um assistente

Abra este clone no Codex e invoque:

> $tripo-face-rig Rig a cabeça preparada no trabalho/character/source.blend e
> anime-o com work/character/voice.wav. Verifique os pré-requisitos e me dê
> um arquivo Blender falando para revisar.

A habilidade do Codex está em [.agents/skills/tripo-face-rig/SKILL.md](.agents/skills/tripo-face-rig/SKILL.md).
É escopo de repositório: mantenha o clone disponível em vez de copiar apenas o seu
SKILL.md em uma pasta de habilidades globais. Veja [documentação de habilidades do Codex](https://developers.openai.com/codex/skills/)
para a descoberta. A correspondência [Claude skill](.claude/skills/tripo-face-rig/SKILL.md)
utiliza o mesmo fluxo de trabalho e scripts.

## Início rápido

Primeiro criar/importar um modelo e colocar sua cabeça, olhos, sobrancelhas, dentes e língua
em Blender. Salve uma malha preparada de `cabeça` mais chamada `upper_jaw`, `lower_jaw`,
e objetos `lingue` sob `work/character/source.blend`. Mantenha o cabelo separado.
Leia [instruções de preparação](docs/workflow.md) para integração olho/sobrancelha e
verificações de colocação frontal/lateral antes de construir.

A partir desta pasta de repositório:

```powershell
# Construir um equipamento de revisão e relatório JSON correspondente.
.\rig.ps1 .\work\character\source.blend

# Depois de aceitar o equipamento visualmente, adicione a fala e o som da amostra.
.\lipsync.ps1 .\work\character\voice.wav -Rig .\work\character\source_rig.blend
```

O primeiro comando produz `source_rig.blend` e `source_rig.json`. O segundo
produz `source_rig_voice_lipsync.blend` e Rhubarb timings ao lado do equipamento.
Abra a mistura animada e pressione o espaço. Mantenha a voz WAV disponível em sua
caminho referenciado. Renderizar um vídeo codificado é uma operação separada do Blender.

Para testes repetidos, defina `rig` em `pipeline.local.json`, em seguida, execute apenas:

```powershell
.\lipsync.ps1 .\trabalho\caractere\voice.wav
```

`-Output` seleciona um caminho de saída diferente. Use `-Recognizer fonético` para
clipes de voz não-inglês. Os scripts param em erros de ferramenta e protegem arquivos de entrada
de ser usado como saída. Re-execução de um caminho de saída substitui que gerou execução.

## Configurações e limitações do equipamento

`rig.ps1` mantém as costuras labiais intactas por padrão. `-Abertura do MouthMode -SealRest 0.5`
foi útil para uma cabeça visivelmente aberta, mas não é uma predefinição universal. Inspecionar
medidas da boca, limite da mandíbula, cantos dos lábios e colocação dentária. O direto
ponto de entrada `autorig.py` mantém seu comportamento de costura automática legado; passar
`--no-split-seam` ao preservar uma cavidade que já está aberta.

A plataforma cria ossos da mandíbula/língua/olho/sobrancelha onde as partes medidas os suportam,
chaves de forma facial processuais, uma cavidade bucal e rascunhos opcionais do ARKit/VRChat.
Sobrancelhas/olhos/cílios separados requerem preparação ou ligação; cabelo estático não é
física do cabelo. Você fornece o corpo manipulado no estágio de fixação manual; o
próxima tarefa do agente conecta os esqueletos e exportações para Unity. Um equipamento pode salvar
enquanto um portão de verificação falha: inspecionar o
relatório e resultado renderizado em vez de ignorar a saída não zero.

## Documentação e código

- [Fulware completo](docs/workflow.md): criação, colocação, compilação, revisão, áudio.
- [Troubleshooting](docs/troubleshooting.md): detecção de boca, pesos, dentes, reprodução.
- [Ferramentas de diagnóstico](docs/diagnostics.md): renderizações de QA e reparos direcionados opcionais.
- [Publicando](docs/publishing.md): arquivos ignorados, exportação de fonte limpa, histórico.
- [Dependências de terceiros](THIRD_PARTY.md): ferramentas externas e separação de ativos.
- `autorig.py`, `tripo_face_rig/`: aparelhamento medido, expressões, verificação, animação.
- `scripts/face_pipeline/`: auxiliares compartilhados de assistente/CLI.
- `unidade/`: componentes de tempo de execução mantidos e configuração genérica; consulte o guia Unity.
- `blender_extension/`: fontes legadas/avançadas; configuração extra e
  validação necessária. Extensões empacotadas e ativos de modelo de terceiros são excluídos.

## Contribuindo

Mantenha reproduções ignoradas `trabalho/` ou `scratchpad/`. Enviar código, reproduzível
comandos e achados; não cometam modelos/áudio privados, executados gerados ou
configuração da máquina. Alterações de teste em cópias de fundo, incluem evidências visuais
quando a deformação muda, e distinguir verificações numéricas da aprovação artística.
Use `python -m unittest discover -s tests` para verificações portáteis de ajuda/embalagem.
A verificação de preservação do motorista auto-suficiente é executada no Blender:
`blender -b --factory-startup --python-exit-code 1 --python tests/blender_animation_smoke.py`.

## Licença

Este repositório e seu exemplo de Ferreiro incluído estão disponíveis sob o
[LICENÇA MIT](LICENÇA). Ferramentas e ativos de terceiros conservam seus respectivos
licenças; ver [THIRD_PARTY.md](THIRD_PARTY.md).

Relatório pré-requisito: `./doctor.ps1`. Esqueleto/tarefa de exportação: `./export-unity.ps1`.
Instalação de componentes Unity: `./install-unity.ps1 <project-path>`.
