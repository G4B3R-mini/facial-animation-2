# Preparar uma cópia pública do repositório

Gere o pacote instalável para Unity com `python scripts/build_unity_package.py`.
Anexe `dist/TripoFaceRig-Unity.unitypackage` à versão publicada no GitHub. Ele
contém código C# mantido e metadados estáveis do Unity, mas nenhum modelo, voz,
clipe de movimento, executável do Rhubarb ou cena de projeto. `dist/` permanece
ignorado; o gerador e o código-fonte ficam no Git. O guia de Unity explica como
instalar e usar a janela de configuração. O workflow **Build Unity package** do
GitHub Actions também gera um artefato para download sob demanda e o anexa
automaticamente às versões publicadas no GitHub.

O `.gitignore` da raiz exclui diretórios de trabalho, modelos, mídia gerada,
relatórios do Rhubarb, binários empacotados, dependências baixadas, configuração
local e arquivos pessoais de experimentos/histórico. Coloque novas execuções em
`work/` para que seus relatórios JSON e demais saídas também sejam excluídos.
Testes em `tests/`, manifestos, configurações de exemplo e recursos criados
intencionalmente em `docs/assets/` continuam versionados.

Ignorar um arquivo não o remove do índice nem de commits anteriores. Se um
artefato já estiver versionado, use `git rm --cached -- path` para parar de
versioná-lo sem remover a cópia local. Antes de confirmar alterações,
inspecione `git status`, `git diff --cached` e `git ls-files`. Não use a
exclusão de arquivos no sistema de arquivos para limpar o índice do Git.

## Começar um histórico público a partir de uma exportação limpa

Este checkout de desenvolvimento contém commits antigos com artefatos de
modelos/testes. Enviar o branch existente transfere esses objetos históricos
mesmo que a árvore atual esteja limpa. O exportador de fonte cria um diretório
separado a partir do **código-fonte de trabalho atual**, aplicando `.gitignore`
inclusive aos arquivos já versionados. Ele não copia `.git`, recursos do
usuário, configuração da máquina nem o histórico antigo.

```powershell
python scripts/export_source.py scratchpad/public-release --init
```

O destino precisa ser novo ou vazio; o exportador nunca apaga um diretório
existente. `--init` inicializa um novo branch `main` e prepara os arquivos
exportados para commit, mas não cria commit nem contata um remoto. Revise a
exportação antes de publicar:

```powershell
Set-Location scratchpad/public-release
git status --short
git diff --cached --stat
```

O repositório é distribuído sob a licença MIT indicada na raiz. Confirme que os
novos recursos de exemplo pertencem ao contribuidor ou têm termos de
redistribuição compatíveis. Em seguida, crie o commit e adicione o remoto do
GitHub **no repositório exportado**. A preparação não configura URL remota, não
cria commit, não envia alterações e não reescreve histórico.
Se for necessário preservar o histórico público existente, faça uma revisão e
migração separadas; não force o envio de um histórico reescrito como parte de
uma limpeza incidental.

O exportador inclui novos arquivos-fonte não ignorados e também os arquivos de
trabalho já versionados; revise a lista. Ignorar credenciais comuns não equivale
a uma verificação completa de segredos. Não coloque conteúdo confidencial em
código ou documentação versionados e confira a procedência antes de publicar.
Recursos externos não são cobertos por uma futura licença do código.
