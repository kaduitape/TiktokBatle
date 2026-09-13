# TikTok Battle Arena

> Deploy em produção com Traefik e Cloudflare: veja [DEPLOY_TRAEFIK.md](DEPLOY_TRAEFIK.md).

Jogo 2D interativo em tempo real para TikTok LIVE: espectadores entram na arena
como bolinhas físicas com sua foto de perfil, e presentes da live viram
ataques, curas e combos contra um dos dois personagens configuráveis (Lado A
vs Lado B).

Este repositório segue deliberadamente a ordem de desenvolvimento do próprio
prompt (seção 55/56): o **núcleo** —
`espectador → presente → identificar usuário → obter avatar → localizar/criar
bolinha → bolinha executa ação → projétil atinge personagem → XP alterado →
efeito visual → ranking atualizado` — está implementado ponta a ponta e
testado, e as fases seguintes (combos, ataques especiais, morte súbita, nova
rodada, templates, editor de arena, música/mixer) também estão implementadas.
O que resta em aberto é essencialmente uma única coisa: testar a conexão
contra uma TikTok LIVE de verdade (o conector existe e usa o mesmo pipeline,
mas não há credenciais/rede para validar isso nesta sessão) — ver "Status por
fase" abaixo para o detalhe completo do que está e não está pronto.

## Três modos de batalha

O mesmo pipeline, personagens, presentes, combos, efeitos e áudio servem aos
três modos — o admin escolhe por batalha, em **Admin → Batalhas → Modo**.

### 🎯 Personagens (modo clássico)

Os espectadores atacam os dois personagens configurados. Presentes tiram ou
dão XP do Lado A / Lado B, e vence quem sobrar com XP.

### ⚔️ Guerra de Times (PvP)

Os **espectadores são os lutadores**. Cada um vira uma bolinha com poder
próprio:

- **Crescimento**: cada presente enviado aumenta o poder do próprio lutador, e
  o tamanho da bolinha escala com esse poder (logaritmicamente, para um
  "baleia" não cobrir a arena inteira). Sobe de nível a cada faixa de poder.
- **Usuário contra usuário**: o mesmo presente que faz você crescer também cai
  como um golpe em um inimigo aleatório do time oposto — presentes de cura só
  fazem crescer, não batem.
- **Combate contínuo**: um tick no servidor faz os lutadores vivos trocarem
  tiros automaticamente, mesmo sem ninguém enviando presente.
- **Barra de vida individual** e número de poder acima de cada bolinha; quem
  zera o poder é **eliminado** e some da arena.
- **Poderes especiais**: meteoro, raio, ataque aéreo etc. funcionam igual, só
  que mirando lutadores do time inimigo em vez do personagem.
- **Times balanceados**: quem entra sem escolher lado cai no time com menos
  lutadores; quem manda presente entra no time que aquele presente ataca.
- Vitória quando um time perde todos os lutadores. O reinício de rodada revive
  todo mundo no poder inicial, sem precisar reentrar.

Todos os números do modo (poder inicial, poder por presente, intervalo do tick,
atacantes por tick, dano base, nível a cada X, eliminação ligada/desligada,
poder de respawn) ficam na chave `team_battle` de **Settings** — dá para
rebalancear uma live em andamento sem deploy:

```bash
curl -X PUT localhost:8000/api/settings/team_battle \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"starting_power":100,"power_per_gift_value":10,"tick_seconds":2,
       "attackers_per_tick":40,"attack_base_damage":4,
       "attack_power_scaling":0.004,"level_up_every":500,
       "elimination_enabled":true,"respawn_power":0}'
```

### 🪖 Guerra de Tanques

Os **dois charges são os chefões** e os espectadores são as tropas que
derrubam o chefão adversário.

- **Entrada pelo chat**: quem comenta `P` entra no time do Lado A, quem
  comenta `B` entra no Lado B. As palavras-chave são configuráveis, e a
  mensagem tem que ser só a palavra — conversa normal no chat não recruta
  ninguém por acidente. Comentar a outra letra troca de lado.
- **Chefões com mais de 1 milhão de vida**: Lula e Bolsonaro entram com
  **1.500.000 de vida** cada, então a partida é uma guerra de desgaste do
  time inteiro, não de um presente sortudo.
- **Todo mundo atira só no chefão inimigo**: cada presente faz o tanque do
  espectador girar, recuar no tranco e disparar um obus **no chefão do time
  adversário**. Espectador nunca atira em espectador.
- **Quanto mais moedas, mais forte**: o dano no chefão é o preço do presente
  em moedas × quantidade × `boss_damage_per_coin` (500 por padrão).
- **Os chefões revidam com bombas**: a cada ~12 segundos cada chefão lança
  uma bomba num **espectador ativo do time adversário** — o alvo sai dos 10
  mais recentes a interagir, a bomba tira 150 de dano e derruba um soldado
  de vida cheia, que **sai do jogo** com explosão.
- **Charges fixos, mas vivos**: ficam parados no lugar, respirando,
  balançando de leve e dando um soco no ar de vez em quando; ao atirar,
  giram na direção do alvo e recuam, e tremem quando tomam um obus.

Com os valores padrão (chefão com 1.500.000 de vida, 500 de dano por moeda):

| Presente | Moedas | Dano no chefão | Vida do chefão |
|---|---|---|---|
| 🌹 Rosa | 1 | 500 | 0,03% |
| 🌸 Flor Aberta | 10 | 5.000 | 0,3% |
| 🍩 Rosquinha | 30 | 15.000 | 1% |
| 🫶 Mãos Coração | 100 | 50.000 | 3,3% |
| ☄️ Meteoro | 500 | 250.000 | 16,7% |

Ajuste tudo na chave `tank_war` de **Settings** (`team_a_keyword`,
`team_b_keyword`, `soldier_hp`, `boss_damage_per_coin`,
`bomb_interval_seconds`, `bomb_damage`, `bomb_active_pool`) e o preço em
moedas de cada presente em **Admin → Presentes**.

> **A arte dos charges**: o modo já vem com a batalha "Guerra de Tanques" e os
> dois personagens ("Lula" e "Bolsonaro") cadastrados, mas **sem imagem** —
> suba os PNGs em **Admin → Personagens**. Até lá eles aparecem como
> placeholder. Como o desenho é uma imagem única, a animação é do conjunto
> (respiro, balanço, soco, giro, recuo): animar braço e rosto separadamente
> exigiria a arte exportada em camadas separadas.

> **Atualizando um banco que já existia**: nada a fazer — as migrations
> cuidam disso automaticamente no startup (ver "Migrations" abaixo).

## Personagens animados (folha de sprites)

Um personagem pode ser um desenho parado ou uma **folha de sprites**: uma única
imagem com várias poses lado a lado, que o jogo toca em sequência para o
personagem se mexer. Vale para os três modos.

### Como cadastrar

1. Monte a imagem com as poses numa grade de **células do mesmo tamanho**.
2. Em **Admin → Personagens**, suba essa imagem no campo *Imagem*.
3. Preencha o bloco *Animação*:

| Campo | O que é |
|---|---|
| **Colunas** | quantas poses por linha. **0 = imagem parada** (comportamento antigo) |
| **Linhas** | quantas linhas a grade tem |
| **Quadros** | quantas poses de verdade existem. `0` = a grade toda; use quando as últimas células ficaram vazias |
| **Quadros por segundo** | velocidade da animação. 6–10 costuma ficar bom; acima de 15 fica agitado demais |

Não é preciso medir pixel nenhum: o tamanho de cada pose é a imagem dividida
pela grade. Personagens que já existem continuam parados, porque nascem com
colunas = 0.

Quando há animação, o jogo desliga o "respiro" falso (o sobe-e-desce e o soco
no ar que existiam para dar vida a um desenho estático) — a folha já faz esse
trabalho. Girar para mirar, o recuo do tiro e o tranco ao levar dano continuam
valendo, porque são movimentos do personagem inteiro.

### Trocando a arte com a live no ar

A Arena é uma fonte de navegador do OBS que fica aberta o dia inteiro. Depois de
trocar a imagem de um personagem (ou o fundo da batalha) em **Personagens**,
clique em **reiniciar** na batalha: o servidor reenvia o estado completo e a
Arena aberta redesenha os personagens com a arte nova — **sem precisar fechar e
reabrir a fonte no OBS**.

O painel mostra a prévia de cada imagem ao lado do campo e na lista de
personagens, então dá para conferir qual desenho ficou em qual lado antes de
montar a batalha.

### Imagens de reação (dano e disparo)

Além da animação em loop, um personagem pode ter **dois desenhos avulsos** que
entram por um instante quando algo acontece:

| Campo | Quando aparece |
|---|---|
| **Imagem ao levar dano** | no instante em que o tiro acerta — na Guerra de Tanques quando o chefão leva um obus, no modo clássico quando o personagem perde XP |
| **Imagem ao disparar** | na Guerra de Tanques, no instante do disparo de canhão (vale para o tiro dos espectadores e para a bomba do chefão) |

As duas são opcionais e podem ser subidas à mão em **Admin → Personagens** ou
geradas junto com a folha (abaixo). Sem elas nada muda: continua o tranco do
recuo e a piscada vermelha de antes. Com a imagem de dano, a piscada vermelha
é desligada — ela dobraria com um desenho que já está vermelho.

A troca respeita a altura do personagem na tela, então a arte de reação não
precisa ter as mesmas dimensões da arte parada. Quando duas reações se
atropelam (levar dano no meio de um disparo), a mais recente manda, e só ela
devolve o personagem à pose de descanso.

### Gerando as poses pelo próprio painel

Com uma chave de imagem configurada, **Admin → Gerar sprites** faz tudo sem
sair do navegador: você descreve o personagem (ou sobe a caricatura pronta),
lista as poses, marca se quer as imagens de dano e de disparo, e o painel
devolve tudo montado e já aplica no personagem escolhido.

O truque que mantém o personagem igual entre os quadros: **tudo é edição de uma
única imagem de referência**. Essa referência é a caricatura que você subiu ou,
se não subir nenhuma, a primeira pose gerada a partir da descrição. Todas as
outras imagens — as outras poses, o dano, o disparo — saem de edições dela, com
o prompt dizendo apenas o que muda.

**Se você já tem o desenho, suba.** Aí a semelhança é a do seu desenho e não a
que o modelo inventar, e a imagem enviada vira o **quadro 1** da animação.
Nesse caso a descrição vira opcional (ajuda o modelo a entender o desenho).

### A chave da API de imagem

Há dois lugares para colocá-la, e a do painel tem prioridade:

**No painel** (mais simples): em **Admin → Gerar sprites**, o primeiro cartão
tem o campo para colar. O botão *Testar* confirma se a chave funciona sem
gastar crédito — ele só lista os modelos, que é de graça. Fica guardada no
banco deste servidor.

**No `.env` do servidor** (quando você não quer a chave no banco):

```bash
BATTLE_IMAGE_API_KEY=sk-...        # chave da OpenAI (platform.openai.com)
BATTLE_IMAGE_MODEL=gpt-image-1     # opcional, esse é o padrão
```

Em qualquer um dos dois, a chave **nunca volta para o navegador**: o painel
mostra só os quatro últimos caracteres e de onde ela veio.

> **Onde ela fica exposta:** a chave do painel é gravada na tabela
> `app_secrets` em texto puro — o sistema não tem cofre de senhas. Quem tiver
> acesso ao banco ou a um backup dele lê a chave. Em servidor compartilhado,
> prefira o `.env`. Essa tabela é deliberadamente separada de `settings`,
> porque `GET /api/settings/{chave}` é público e serve o placar para a Arena
> sem login.

Sem chave nenhuma, a página continua abrindo e explica o que fazer — o resto
do sistema não depende dela em nada.

Cada imagem é uma chamada à API e é cobrada à parte: 4 poses + dano + disparo =
6 imagens na fatura (5 se você subiu a caricatura, porque aí o quadro 1 já é
seu). O limite por geração é de 8 poses, justamente para um clique distraído
não virar uma conta alta.

### Montando a folha a partir de imagens soltas

A IA entrega **uma pose por arquivo**. O script junta tudo e já diz o que
digitar no painel:

```bash
pip install Pillow
python scripts/make_spritesheet.py pose1.png pose2.png pose3.png pose4.png -o lula.png
```

Ele recorta o vazio em volta de cada pose, deixa todas do mesmo tamanho,
alinha pelos pés (para o personagem não flutuar de um quadro para o outro) e
imprime as colunas/linhas/quadros prontos para copiar. Use `--columns 4` para
quebrar em várias linhas.

### Especificações da imagem para gerar na IA (manualmente)

Se preferir gerar fora do painel, peça **uma pose por vez**, sempre com estas
regras — são as mesmas que o painel aplica sozinho:

- **PNG com fundo transparente**, personagem de corpo inteiro.
- **Mesmo enquadramento em todas as poses**: mesma distância da câmera, mesmo
  tamanho do personagem, pés na mesma altura. Esse é o erro mais comum — se o
  tamanho variar entre as poses, a animação "pula".
- **Mesma iluminação, mesmas cores, mesmo traço** em todas.
- **Tamanho por pose**: 512×768 px é um bom padrão (o jogo redimensiona para
  ~560 px de altura na Guerra de Tanques e ~900 px no modo clássico). Menos de
  300 px de altura fica borrado na tela 1080×1920.
- **Limite da folha inteira: 4096×4096 px.** Acima disso algumas placas de
  vídeo recusam a textura e o personagem some. Com células de 512 px de
  largura, isso dá até 8 colunas.
- **4 a 8 poses** já dá uma animação convincente; 6 fps com 6 poses = 1 segundo
  de ciclo.
- O ciclo é em **loop**, então a última pose tem que combinar com a primeira.

Modelo de prompt que funciona bem (troque só a parte da pose):

> Caricatura de corpo inteiro do personagem X, estilo cartoon, fundo totalmente
> transparente, personagem centralizado ocupando toda a altura da imagem, pés na
> base do quadro, visto de frente, iluminação neutra e uniforme, sem sombra no
> chão, 512x768. **Pose: braço direito levantado na altura do ombro, boca
> aberta.**

Depois repita trocando só a frase da pose: *braço abaixado*, *braço a meio
caminho*, *boca fechada*, e assim por diante. Se a sua ferramenta tiver edição
da mesma imagem (inpainting / "editar esta imagem"), **prefira isso a gerar do
zero** — mudar só o braço na mesma arte mantém a consistência que o gerador
não consegue repetir sozinho.

## Stack

- **Backend**: Python 3.12 + FastAPI + SQLAlchemy (async) + PostgreSQL + Redis (reservado para filas/pub-sub multi-processo)
- **Game**: React + Phaser 3 (engine) com o plugin de física Matter.js embutido no Phaser
- **Tempo real**: WebSocket nativo (`/ws/arena/{session_id}`)
- **Admin**: React (mesma SPA, rotas `/admin/*`)
- **Deploy**: Docker + Docker Compose

## Rodando

```bash
# na primeira execução: copie .env.example para .env e defina os segredos
docker compose up --build -d
```

O frontend é o único serviço exposto: http://localhost:8080 (ou a porta definida
em `HTTP_PORT`). Ele encaminha `/api`, `/uploads` e `/ws` internamente para o
backend — banco, Redis e API não ficam públicos.

- Documentação da API: http://localhost:8080/docs
- Painel admin: http://localhost:8080/#/admin
- Arena (fonte de vídeo para OBS): http://localhost:8080/#/arena?battle=<id>

Na primeira subida o backend semeia automaticamente: 14 presentes padrão
(8 da seção 12 + 6 ataques especiais das seções 20-25, cada um com seu preço
em moedas), 5 tiers de combo, 4 personagens ("Lado A"/"Lado B" e
"Lula"/"Bolsonaro") e três batalhas prontas — uma por modo — assim os três
modos funcionam imediatamente sem nenhum cadastro manual.

### Login do painel admin

O painel (`/admin/*`) fica atrás de login — a **Arena** (fonte OBS) nunca
precisa de login, só as ações administrativas (CRUD, simulador, live,
mixer) exigem token. Antes da primeira execução, copie `.env.example` para
`.env` e substitua todos os valores de exemplo, em especial:

```bash
BATTLE_ADMIN_USERNAME=seu_usuario
BATTLE_ADMIN_PASSWORD=uma_senha_forte
BATTLE_SECRET_KEY=uma_string_aleatoria_longa   # assina os tokens de sessão
```

O Compose exige essas credenciais para iniciar. O arquivo `.env` é ignorado
pelo Git e nunca deve ser enviado ao repositório.

### Rodando localmente sem Docker

```bash
# backend
cd backend
pip install -r requirements.txt
export BATTLE_DATABASE_URL="sqlite+aiosqlite:///./dev.db"   # ou aponte para um Postgres
uvicorn app.main:app --reload

# frontend
cd frontend
npm install
npm run dev
```

## Testando o fluxo principal

1. Abra o painel admin → **Simulador**.
2. Abra a **Arena** em outra aba (botão "Abrir arena para ver ao vivo").
3. No simulador, clique **👤 Simular novo espectador** — uma bolinha cai do
   topo da arena com "X ENTROU NA BATALHA".
4. Escolha um presente (ex: 🌹 Rosa) e clique **▶ SIMULAR PRESENTE** — a
   bolinha do usuário é destacada, dispara um tiro até o personagem, o XP
   diminui com animação suave na barra, e o ranking é atualizado.
5. Aumente a quantidade (ex: 50) para ver o sistema de combo agregando em
   RAJADA/METRALHADORA/BAZUCA em vez de 50 animações independentes.
6. **🔥 Teste de estresse** gera N usuários + presentes de uma vez, passando
   pelo mesmo pipeline (seção 46 do prompt).

Todo evento — simulado ou de uma live real futura — passa pelo **mesmo**
código (`GamePipeline.handle_event`), como exige a seção 45 do prompt.

## Arquitetura (mapeada nas seções 49-50 do prompt)

```
LiveEventProvider (Simulation | TikTok)
        │  LiveEvent padronizado (seção 48)
        ▼
   EventQueue (fila assíncrona por sessão)
        ▼
   EventNormalizer → GiftRuleEngine → AvatarService → XPManager
        ▼                                  │
   BattleManager (vitória)          RankingManager
        ▼
  ConnectionManager (WebSocket) ──► Phaser GameScene
                                        │
                    AvatarManager · ProjectileManager · MissileManager
                    HealManager · ComboManager · EffectsManager
                    XPManager · RankingManager · FeedManager · AudioManager
```

Backend: `backend/app/{models,schemas,services,providers,ws,api}`
Frontend: `frontend/src/{arena/game/managers,admin/pages}`

### Banco de dados

`characters`, `battles`, `battle_sessions`, `gifts`, `combo_tiers`,
`players`, `battle_events`, `music_tracks`, `settings` — nenhum personagem,
presente, batalha ou música é hardcoded; tudo é CRUD via `/api/*` e o
painel admin. `settings` é um KV genérico (hoje usado para o mixer de
áudio (`audio_mixer`) e para o balanceamento dos modos PvP
(`team_battle`) e tanque (`tank_war`)).

### Migrations

O schema é do Alembic (`backend/alembic/`), e o backend roda
`alembic upgrade head` sozinho no startup — não existe mais `create_all`.
Três situações, todas sem SQL manual:

| Situação | O que acontece |
|---|---|
| Banco novo | Roda todas as migrations em ordem e cria tudo |
| Banco já no Alembic | Roda só as que faltam |
| Banco criado pelo `create_all` antigo (tabelas existem, sem `alembic_version`) | É **adotado**: recebe um `stamp` na revisão base e depois só o delta é aplicado — os dados são preservados |

Esse terceiro caso é o que permite atualizar uma instância que já estava
rodando antes do modo PvP sem perder nada. A revisão `0001` descreve de
propósito o schema **anterior** ao PvP, e a `0002` acrescenta as colunas
novas com `server_default` (sem isso não é possível adicionar coluna
`NOT NULL` em tabela com registros).

Para rodar à mão (ex: aplicar antes de subir a app, ou inspecionar):

```bash
cd backend
alembic current            # em que revisão o banco está
alembic upgrade head       # aplica o que falta
alembic downgrade -1       # volta uma revisão
```

O Alembic usa a mesma `BATTLE_DATABASE_URL` da aplicação, só trocando o
driver async pelo sync — não há uma segunda variável de banco para manter
em sincronia.

### Fronteira de autenticação

Token HMAC assinado no backend (`app/core/auth.py`, sem dependência nova),
emitido por `POST /api/auth/login` e enviado como `Authorization: Bearer
<token>` pelo painel admin. A regra é simples: **qualquer ação de escrita
do admin exige token; tudo que a Arena (fonte OBS, sem login) precisa ler
continua público** — listar batalhas/presentes/músicas/mixer, iniciar uma
sessão de batalha, o WebSocket `/ws/arena/{session_id}` e o ranking. CRUD
de personagens/batalhas/presentes/combos/músicas, upload de arquivos,
simulador, live (conectar/desconectar TikTok) e reiniciar/templatizar uma
batalha exigem token.

## Status por fase (ordem do prompt, seção 55)

| Fase | Descrição | Status |
|---|---|---|
| 1 | Arena 9:16 + dois lados + personagens configuráveis | ✅ |
| 2 | Bolinhas com avatar, física Matter (gravidade/colisão/quique/acúmulo) | ✅ |
| 3 | Simulador (usuário/avatar/presente) usando o pipeline real | ✅ |
| 4 | Tiro, míssil, cura + atualização de XP | ✅ |
| 5 | WebSocket em tempo real | ✅ |
| 6 | GiftRuleEngine (presente → ação → animação → XP) | ✅ |
| 7 | Provedor real do TikTok LIVE | ⚙️ interface pronta (`LiveEventProvider`), `TikTokProvider` traduz eventos do pacote `TikTokLive`, exposto no admin (**Live**) e via `/api/live/*` — mas **não testado contra uma live real** nesta sessão (sem credenciais/rede disponíveis aqui) |
| 8 | Combos, ataques especiais, ranking, músicas, efeitos, morte súbita, vitória | ✅ ver detalhes abaixo |
| 9 | Otimização para live real (500-1000 jogadores) | 🟡 parcial — ver abaixo |

### O que está implementado na Fase 8

- Combos configuráveis por threshold (x1/x10/x25/x50/x100 → TIRO/RAJADA/
  METRALHADORA/BAZUCA/ATAQUE ESPECIAL), com agregação real (seção 26/27).
- Ranking em tempo real (dano/cura/presentes/combo) com painel que entra e
  sai da tela periodicamente (seção 36).
- Ataques especiais totalmente jogáveis como presentes comuns (editáveis em
  **Admin → Presentes**, sem código): ☄️ Meteoro, ⚡ Raio, ✈️ Ataque Aéreo,
  🌪️ Furacão (gira as bolinhas via física), 💥 Onda de Choque (empurra as
  bolinhas com força radial do Matter.js) e 🦣 Avatar Gigante (aumenta
  massa/tamanho/força temporariamente) — seções 20-25.
- Vitória (XP a zero), banner de vitória, bolinhas do time vencedor
  comemorando.
- **Morte súbita** (seção 37): ao esgotar `battle_time_seconds`, a sessão
  entra em `sudden_death` com multiplicador de dano configurável
  (2x, escalando para 3x após 60s adicionais).
- **Nova rodada** (seção 40): reinício manual (`POST /battles/{id}/restart`)
  ou automático com contagem regressiva transmitida por WebSocket
  (`NOVA BATALHA EM: 10...1`) — reseta o XP *na mesma sessão*, sem precisar
  reconectar o navegador do OBS.
- **Templates de batalha** (seção 44): salvar qualquer batalha como modelo
  reutilizável com qualquer nome (ex: "Política", "Futebol") e instanciar
  novas batalhas a partir dele.
- **Editor de arena** (seção 42): página admin com preview 9:16 onde os
  dois personagens são arrastáveis para reposicionar (salva em
  `Character.pos_x/pos_y`). XP/ranking/feed/legenda ainda usam posições
  fixas — só os personagens são reposicionáveis por enquanto.
- **Música e mixer de áudio** (seções 31-34): upload de playlist por
  categoria (normal/perigo/vitória/derrota) com troca automática conforme o
  XP cai abaixo de 25%, fade in/out, e mixer com volumes independentes por
  canal (música/tiros/explosões/alertas/interface/vitória). Efeitos de tiro,
  míssil, cura, combo e fanfarra de vitória são **sintetizados via Web Audio
  API** (osciladores/ruído) — nenhum arquivo de áudio é necessário para o
  jogo soar; apenas a trilha de fundo (BGM) depende de upload, já que essa é
  a parte que normalmente exige conteúdo licenciado.

### O que está implementado na Fase 9

- Fila assíncrona por sessão (`EventQueue`) evita que rajadas de presentes
  bloqueiem o ingest.
- Texturas de avatar são "bakeadas" uma única vez por (URL, cor de time) em
  vez de recalcular máscara circular a cada frame — suporta centenas de
  bolinhas simultâneas sem custo por frame.
- Pool de projéteis (tiro) para evitar alocação constante de objetos.
- Limite de jogadores configurável por batalha com remoção do mais antigo
  inativo (nunca durante uma ação em curso) — seção 29/30.
- **Não implementado**: pooling de partículas mais agressivo, sharding do
  WebSocket por múltiplos processos via Redis pub/sub (a fila e o
  broadcast hoje são in-process — suficiente para um único container;
  Redis já está no compose para quando isso for necessário), e testes de
  carga reais acima de algumas centenas de bolinhas simultâneas em produção.

## Conectando a uma TikTok LIVE real

`backend/app/providers/tiktok_provider.py` traduz eventos do pacote
[`TikTokLive`](https://github.com/isaackogan/TikTokLive) para o `LiveEvent`
padrão, e está exposto no admin em **Live** (conectar/desconectar por nome de
usuário) e via `POST /api/live/{session_id}/connect`. Para ativar, instale a
dependência opcional no backend:

```bash
pip install TikTokLive
```

O pacote não vem no `requirements.txt` por padrão porque exige acesso de
rede aos servidores de sinalização do TikTok, que não está disponível em
todo ambiente de deploy. A tradução de eventos usa o mesmo `GamePipeline`
do simulador — mas **a conexão contra uma live real não foi testada** nesta
sessão de desenvolvimento (sem credenciais/rede disponíveis aqui).

## Presentes padrão (seção 12 + especiais das seções 20-25)

| Presente | Ação | Valor | Alvo |
|---|---|---|---|
| 🌹 Rosa | Tiro | -1 XP | Lado A |
| 🤍 Rosa Branca | Tiro | -1 XP | Lado B |
| 🌸 Flor Aberta | Míssil | -10 XP | Lado A |
| 🦖 Dino | Míssil | -10 XP | Lado B |
| 🍩 Rosquinha | Cura | +30 XP | Lado A |
| ⚽ Bola TikTok Brasil | Cura | +30 XP | Lado B |
| 🫶 Mãos Coração | Super Cura | +100 XP | Lado A |
| 🧸 Ursinho | Super Cura | +100 XP | Lado B |
| ☄️ Meteoro | Especial | -50 XP | Lado A |
| ⚡ Raio | Especial | -25 XP | Lado A |
| ✈️ Ataque Aéreo | Especial | -30 XP | Lado A |
| 🌪️ Furacão | Especial (física) | 0 XP | Lado A |
| 💥 Onda de Choque | Especial (física) | 0 XP | Lado A |
| 🦣 Avatar Gigante | Especial (buff) | 0 XP | Lado A |

Os seis especiais vêm pré-cadastrados só para o Lado A — duplique qualquer
um no admin trocando `target_side` para `B` para ter a versão espelhada.
Tudo isso é editável em **Admin → Presentes**, sem precisar mexer em código.
