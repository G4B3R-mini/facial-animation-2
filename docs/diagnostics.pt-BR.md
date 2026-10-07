# Ferramentas de QA e reparo opcional

As ferramentas mantidas ficam em `scripts/face_pipeline/` e são compartilhadas
pelas habilidades do Codex e do Claude. Os caminhos antigos dos scripts do
Claude encaminham para essas ferramentas. Para diagnósticos e renderizações,
use o Blender em segundo plano sobre cópias. Nenhum dos comandos abaixo altera
implicitamente uma sessão aberta no editor.

| Ferramenta | Finalidade |
| --- | --- |
| `audit_scene.py` | Inventário da fonte e avisos sobre sombreamento, shells, duplicatas e orientação; aceita `--obj NAME` |
| `diagnose_rig.py` | Avalia animações ou poses sintéticas de keys **e** poses diretas da mandíbula; informa mudanças de área por face e pesos dentários; aceita `--obj NAME` |
| `qa_render.py` | Renderiza imagens neutras, de mandíbula direta, expressão e piscada, em escala de busto; aceita `--closeup`, `--obj NAME` e `--tag NAME` opcionais |
| `make_sheet.py` | Monta as imagens de QA com Python comum e Pillow; aceita `--kind bust` ou `mouth` |
| `reanimate.py` | Gera cues do Rhubarb e, com áudio, um arquivo blend animado separado, usando perfil incorporado ou explícito |
| `fix_commissure.py` | Suavização local opcional de pesos/deltas nos cantos; inspecione primeiro com `--dry`; aceita `--obj NAME` |
| `place_teeth.py` | Estima a posição usando um modelo doador fornecido pelo usuário; confira as vistas frontal e lateral antes de aceitar |
| `attach_lashes.py` | Transfere opcionalmente o movimento das pálpebras para pequenas shells separadas; inspecione com `--dry` / `--object NAME` |
| `ambient_face.py` | Avançado: substitui a atuação de fala por um loop facial ambiente |
| `unity_prep.py` | Combina armatures do personagem montado, preserva shape keys, redireciona drivers e exporta um FBX neutro para Unity; consulte `agent-wizard.md` |

Antes de usar uma ferramenta de reparo opcional, leia a docstring do módulo
para saber a invocação exata. Não aplique suavização de cantos ou transferência
de cílios globalmente só porque um diagnóstico listou essa possibilidade.

Indicadores úteis incluem a razão de área avaliada por face (picos grandes, em
torno de 2,6–3 vezes, merecem inspeção), mudanças entre amostras da animação,
variação de pesos em faces que conectam regiões e pesos rígidos nas partes
dentárias. São heurísticas de depuração, não limites universais de qualidade.
Polígonos minúsculos ou degenerados na fonte podem inflar as razões; inspecione
as faces correspondentes. Uma grande variação de peso, isoladamente, não prova
que haja rasgo.

Historicamente, `diagnose_rig.py` usa heurísticas geométricas/de material para
identificar dentes quando não há grupos dentários nomeados; arcadas fragmentadas
podem passar despercebidas. Confirme os componentes e os pesos dos vértices
antes de aceitar a classificação dos dentes ou usá-la como máscara de reparo.
Para medições precisas apenas da pele, use os papéis de componentes do relatório
da construção e confira-os novamente após qualquer edição de topologia.

Os ângulos solicitados para QA são 9 e 18 graus. O rig pode limitá-los;
inspecione o limite registrado no JSON de QA/diagnóstico antes de comparar duas
poses que pareçam iguais. Varreduras apenas de shape keys não substituem o teste
real do osso da mandíbula.
