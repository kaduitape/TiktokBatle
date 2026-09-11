# TikTok Battle Arena

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

## Stack

- **Backend**: Python 3.12 + FastAPI + SQLAlchemy (async) + PostgreSQL + Redis (reservado para filas/pub-sub multi-processo)
- **Game**: React + Phaser 3 (engine) com o plugin de física Matter.js embutido no Phaser
- **Tempo real**: WebSocket nativo (`/ws/arena/{session_id}`)
- **Admin**: React (mesma SPA, rotas `/admin/*`)
- **Deploy**: Docker + Docker Compose

## Rodando

```bash
docker compose up --build
```

- Backend: http://localhost:8000 (docs automáticos em `/docs`)
- Painel admin: http://localhost:8080/#/admin
- Arena (fonte de vídeo para OBS): http://localhost:8080/#/arena?battle=<id>

Na primeira subida o backend semeia automaticamente: 14 presentes padrão
(8 da seção 12 + 6 ataques especiais das seções 20-25), 5 tiers de combo,
2 personagens genéricos ("Lado A" / "Lado B") e uma batalha padrão — assim
o fluxo funciona imediatamente sem nenhum cadastro manual.

### Login do painel admin

O painel (`/admin/*`) fica atrás de login — a **Arena** (fonte OBS) nunca
precisa de login, só as ações administrativas (CRUD, simulador, live,
mixer) exigem token. Credenciais padrão para o primeiro acesso:

```
usuário: admin
senha:   changeme
```

**Troque isso antes de expor a instância**, via variáveis de ambiente:

```bash
BATTLE_ADMIN_USERNAME=seu_usuario
BATTLE_ADMIN_PASSWORD=uma_senha_forte
BATTLE_SECRET_KEY=uma_string_aleatoria_longa   # assina os tokens de sessão
```

Se `BATTLE_SECRET_KEY` não for definida, uma chave aleatória é gerada a
cada início do processo — funciona bem para um único container, mas
invalida sessões abertas a cada reinício e não funciona com múltiplas
réplicas atrás de um load balancer (defina a variável explicitamente
nesses casos). O backend loga um aviso no startup se a senha padrão ainda
estiver em uso.

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
áudio, chave `audio_mixer`).

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
