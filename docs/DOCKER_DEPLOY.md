# Run the bot 24/7 with Docker (your server)

One container (`trading-signal-bot`) runs MetaTrader 5 under Wine, the mt5linux bridge and the bot.
Same style as your other services: `build: .`, `env_file: .env`, non-root `appuser`,
memory limits, state in `/backup/apps/…`. It needs **no** reverse proxy, database network or public port:
it only connects out to the broker and Telegram.

Requirements: Docker + Compose, **x86_64** server (`uname -m` → `x86_64`), ~2 GB RAM for this container.

## 1. Get the code
```bash
git clone https://github.com/StartupProjectNetspecter/trading_signal.git
cd trading_signal
```

## 2. Create `.env`
```bash
nano .env
```
```
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=1255394122
VNC_PASSWORD=choose_a_password
```

## 3. Backup folder for the bot state
```bash
sudo mkdir -p /backup/apps/trading-signal-bot/data
docker compose build
docker compose run --rm --entrypoint id bot        # shows uid/gid, usually 1000
sudo chown -R 1000:1000 /backup/apps/trading-signal-bot/data
```
If your host user is not uid 1000, build with your ids instead:
`docker compose build --build-arg APP_UID=$(id -u) --build-arg APP_GID=$(id -g)`.

## 4. Start
```bash
docker compose up -d
docker compose logs -f bot
```
The **first start installs MT5 and Windows Python (5–15 min)**. Until you log in to MT5 (next step) the bot
restarts every 30 s - that is normal.

## 5. Log in to MT5 once (VNC)
```bash
ssh -L 5900:localhost:5900 <user>@<server-ip>
```
VNC viewer → `localhost:5900` → `VNC_PASSWORD`. In MT5:
1. **File → Login to Trade Account**: your demo (tick *Save password*).
2. **Tools → Options → Expert Advisors**: tick **Allow algorithmic trading**; untick the two
   "Disable… when the account/profile has been changed" boxes; keep "Disable… via external Python API" **unticked**.
3. Click **Algo Trading** in the toolbar → **green**.

You get **🤖 Bot started** on Telegram. Then **🤖 Auto-Trade → ✅ Auto ON**.
**Stop the bot on your Windows PC** - only one copy may run.

## Everyday commands
| What | Command |
|---|---|
| Live log | `docker compose logs -f bot` |
| Status / health | `docker compose ps` |
| Restart | `docker compose restart bot` |
| Update code | `git pull && docker compose restart bot` |
| Update after Dockerfile / requirements change | `git pull && docker compose up -d --build` |
| Stop | `docker compose stop bot` |
| Remove (keeps MT5 login + state) | `docker compose down` |

## Where things are kept
| What | Where | Survives rebuild |
|---|---|---|
| Bot code + config.yaml | your repo folder (mounted at /app) | yes (it's the host folder) |
| Journal, mode, auto-trade, alerts | `/backup/apps/trading-signal-bot/data` | yes, and backed up |
| MT5 + your MT5 login | Docker volume `mt5-wine` | yes (`down -v` deletes it) |

## Troubleshooting
| Symptom | Fix |
|---|---|
| `Permission denied` on /app/data/state | Step 3: chown the backup folder to the container's uid |
| `MetaTrader 5 install failed` | `docker compose restart bot` (retries); check internet |
| Bot restarts with `MT5 initialize failed` | MT5 not logged in → step 5 |
| Auto-Trade: Algo Trading is OFF | VNC → click **Algo Trading** (green) |
| `exec format error` | ARM server - MT5 needs x86_64 |

MT5 under Wine with the community `mt5linux` bridge is not officially supported by MetaQuotes.
Test on demo for a few days before relying on it.
