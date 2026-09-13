# Colocando a Battle Arena em produção

Este guia publica a aplicação em `https://arena.navit.com.br` através do
Traefik que já existe na VPS. A aplicação não abre PostgreSQL, Redis ou o
backend para a internet. O Nginx interno encaminha `/api`, `/uploads` e `/ws`
ao backend.

## 1. Confirme Traefik e Cloudflare

No Hostinger Docker Manager desta VPS, o Traefik usa `network_mode: host` e o
resolvedor `letsencrypt` com desafio HTTP. Portanto, use o overlay
`docker-compose.hostinger.yml`; não conecte o Traefik a uma rede externa, pois
o Docker Compose rejeita `network_mode` e `networks` no mesmo serviço.

Para uma instalação Traefik convencional, conectada a uma rede Docker
compartilhada, mantenha o uso de `docker-compose.traefik.yml` e configure o
nome da rede e do resolvedor conforme o seu proxy.

No Cloudflare, o registro `A` de `arena.navit.com.br` deve apontar para o IP
público da VPS. Deixe o SSL/TLS em **Full (strict)** quando o Traefik emitir
um certificado. Não use o modo **Flexible**, pois ele causa redirecionamento
infinito entre Cloudflare e Traefik. Confirme também que WebSockets estão
liberados na zona.

O valor de `TRAEFIK_CERT_RESOLVER` precisa ser o nome exato do resolvedor já
configurado no Traefik. Nesta VPS ele é `letsencrypt`; troque-o somente se o
seu proxy usar outro nome.

## 2. Configure o ambiente

No diretório do projeto na VPS:

```bash
cp .env.example .env
```

Edite `.env` e substitua obrigatoriamente as senhas e o segredo. Mantenha estas
linhas para esta instalação:

```env
BATTLE_PUBLIC_URL=https://arena.navit.com.br
BATTLE_CORS_ORIGINS=["https://arena.navit.com.br"]
HTTP_BIND_ADDRESS=127.0.0.1
HTTP_PORT=8080
BATTLE_DOMAIN=arena.navit.com.br
TRAEFIK_HTTP_ENTRYPOINT=web
TRAEFIK_HTTPS_ENTRYPOINT=websecure
TRAEFIK_CERT_RESOLVER=letsencrypt
```

`HTTP_BIND_ADDRESS=127.0.0.1` é intencional: a porta 8080 serve apenas para
diagnóstico local na VPS. O acesso público passa pelo Traefik em 443.

## 3. Suba a versão de produção

```bash
docker compose -f docker-compose.yml -f docker-compose.hostinger.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.hostinger.yml ps
curl http://127.0.0.1:8080/api/health
```

> **O deploy automático usa o mesmo overlay.** O workflow do GitHub Actions
> passa `-f docker-compose.hostinger.yml` junto com o compose base e **falha**
> se o container do frontend subir sem o label `traefik.enable` — sem isso, um
> deploy recriava o frontend sem os labels e o domínio passava a responder 404
> com todos os containers saudáveis. Para usar outro overlay (ou nenhum),
> defina no `.env`, sem aspas:
>
> ```bash
> COMPOSE_OVERLAY=docker-compose.traefik.yml   # ou: none
> ```

O último comando deve devolver `{"status":"ok"}`. Em seguida, abra
`https://arena.navit.com.br` no navegador. O certificado é definido pelas
labels de `docker-compose.hostinger.yml`; o Traefik da VPS redireciona HTTP
para HTTPS globalmente.

Para acompanhar a conexão do TikTok durante o teste:

```bash
docker compose -f docker-compose.yml -f docker-compose.hostinger.yml logs -f backend
```

Não rode `docker compose down -v`: a opção `-v` apaga os volumes do banco e
dos uploads.

## 4. Primeira LIVE no TikTok

1. Abra `https://arena.navit.com.br/#/admin` e entre com o usuário administrador.
2. Entre em **Ao vivo**. O assistente confirma se o cliente TikTokLive está na imagem.
3. Escolha a batalha. Copie a URL gerada para a fonte **Navegador** do OBS, em
   `1080 x 1920`, e deixe a fonte aberta.
4. Inicie a LIVE pelo TikTok Live Studio ou OBS/TikTok. A VPS hospeda a arena;
   ela não envia o vídeo ao TikTok.
5. No passo 3 do assistente, informe o `@usuario` do criador sem `@` e clique
   em **Conectar TikTok**. Espere o estado **Conectado e recebendo eventos**.
6. Envie um presente de teste. No passo 4, associe o ID capturado à ação do
   jogo. A associação fica gravada no banco e vale nas próximas lives.
7. Faça um teste de presente e, no modo Guerra de Tanques, de comentário para
   entrar em cada time. Só então abra a LIVE ao público.

O cliente processa apenas o evento final de um presente em sequência, evitando
duplicar dano. Se a conexão cair, ele tenta reconectar automaticamente; o
estado e a mensagem de erro ficam visíveis no assistente.

## Diagnóstico rápido

| Sintoma | Verificação |
| --- | --- |
| Domínio retorna 404/502 | Confirme as labels do frontend, o resolvedor `letsencrypt` e os logs do Traefik. Neste Hostinger o proxy usa rede `host`; não adicione uma rede externa ao serviço Traefik. |
| Redirecionamento infinito | No Cloudflare, altere SSL/TLS para **Full (strict)**; não use Flexible. |
| Arena abre, mas para ao vivo | Confira se a conexão está verde no assistente e se Cloudflare/Traefik permitem WebSocket. |
| Presente não faz nada | Envie um teste, abra o passo 4 e associe o ID TikTok capturado a uma regra ativa. |
| Falha ao conectar ao TikTok | Confirme que a LIVE está ativa, o usuário está correto e a VPS tem saída HTTPS para TikTok. Veja `logs -f backend`. |

TikTokLive é um cliente comunitário de Webcast, não uma API oficial do
TikTok. Mantenha uma conta de teste e valide a integração depois de upgrades
do TikTokLive antes de uma live importante.
