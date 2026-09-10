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
testado. Funcionalidades secundárias (música, editor visual de arena, conexão
real com TikTok) estão com a arquitetura pronta para receberem essas
funcionalidades, mas ainda não totalmente implementadas — ver "Status por
fase" abaixo.

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

Na primeira subida o backend semeia automaticamente: 8 presentes padrão
(seção 12 do prompt), 5 tiers de combo, 2 personagens genéricos ("Lado A" /
"Lado B") e uma batalha padrão — assim o fluxo funciona imediatamente sem
nenhum cadastro manual.

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
                    XPManager · RankingManager · FeedManager
```

Backend: `backend/app/{models,schemas,services,providers,ws,api}`
Frontend: `frontend/src/{arena/game/managers,admin/pages}`

### Banco de dados

`characters`, `battles`, `battle_sessions`, `gifts`, `combo_tiers`,
`players`, `battle_events`, `settings` — nenhum personagem, presente ou
batalha é hardcoded; tudo é CRUD via `/api/*` e o painel admin.

## Status por fase (ordem do prompt, seção 55)

| Fase | Descrição | Status |
|---|---|---|
| 1 | Arena 9:16 + dois lados + personagens configuráveis | ✅ |
| 2 | Bolinhas com avatar, física Matter (gravidade/colisão/quique/acúmulo) | ✅ |
| 3 | Simulador (usuário/avatar/presente) usando o pipeline real | ✅ |
| 4 | Tiro, míssil, cura + atualização de XP | ✅ |
| 5 | WebSocket em tempo real | ✅ |
| 6 | GiftRuleEngine (presente → ação → animação → XP) | ✅ |
| 7 | Provedor real do TikTok LIVE | ⚙️ interface pronta (`LiveEventProvider`), `TikTokProvider` implementado contra o pacote `TikTokLive`, mas **não testado contra uma live real** nesta sessão (sem credenciais/rede disponíveis aqui) |
| 8 | Combos, ataques especiais, ranking, músicas, efeitos, morte súbita, vitória | 🟡 parcial — ver abaixo |
| 9 | Otimização para live real (500-1000 jogadores) | 🟡 parcial — ver abaixo |

### O que está implementado na Fase 8

- Combos configuráveis por threshold (x1/x10/x25/x50/x100 → TIRO/RAJADA/
  METRALHADORA/BAZUCA/ATAQUE ESPECIAL), com agregação real (seção 26/27).
- Ranking em tempo real (dano/cura/presentes/combo) com painel que entra e
  sai da tela periodicamente (seção 36).
- Vitória (XP a zero), banner de vitória e bolinhas do time vencedor
  comemorando.
- Efeitos: tiro, míssil (fumaça + explosão + tremor de câmera), cura
  (corações + partículas), avatar gigante, onda de choque, furacão, meteoro,
  raio e ataque aéreo já têm managers prontos (`MissileManager`,
  `AvatarManager.applyRadialForce/spinAll`) — expostos como métodos que o
  `GiftRuleEngine`/admin ainda precisam mapear para presentes/botões
  específicos.
- Música, mixer de áudio, morte súbita com multiplicador, editor visual de
  arena (drag-and-drop), templates de batalha e novo-round com contagem
  regressiva **ainda não foram construídos** — a base modular (tabelas,
  managers separados, `Settings` genérico) foi deixada pronta para que
  entrem sem refatoração do núcleo.

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
  broadcast hoje são in-process — суficiente para um único container;
  Redis já está no compose para quando isso for necessário), e testes de
  carga reais acima de algumas centenas de bolinhas simultâneas em produção.

## Conectando a uma TikTok LIVE real

`backend/app/providers/tiktok_provider.py` já traduz eventos do pacote
[`TikTokLive`](https://github.com/isaackogan/TikTokLive) para o `LiveEvent`
padrão. Para ativar:

```bash
pip install TikTokLive
```

e chame (via um endpoint/admin action a construir) `tiktok_provider.start(session_id, tiktok_username="...")`.
Isso não foi exposto como endpoint REST nesta versão porque exige testes
contra uma live real, fora do escopo desta sessão de desenvolvimento — a
tradução de eventos, porém, já está implementada e usa o mesmo
`GamePipeline` do simulador.

## Presentes padrão (seção 12)

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

Tudo isso é editável em **Admin → Presentes**, sem precisar mexer em código.
