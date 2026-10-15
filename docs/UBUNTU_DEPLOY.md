# Run the bot 24/7 on an Ubuntu server

MetaTrader 5 is a Windows program, so on Ubuntu it runs inside **Wine**. The bot (Linux Python)
talks to it through the **mt5linux** bridge. Everything starts automatically after a reboot.

```
Ubuntu server
 ├─ goldbot-screen   virtual screen (Xvfb :99)
 ├─ goldbot-mt5      MetaTrader 5 under Wine
 ├─ goldbot-bridge   mt5linux bridge (Windows Python under Wine, port 18812)
 └─ goldbot          run_live.py  →  Telegram
```

## Requirements
- Ubuntu 22.04 or 24.04, **x86_64** (Intel/AMD). ARM servers cannot run MT5.
- 2 GB RAM minimum (4 GB recommended), ~10 GB free disk.
- Check with: `uname -m` (must print `x86_64`) and `free -h`.

## 1. Get the code
```bash
sudo apt-get install -y git
git clone https://github.com/StartupProjectNetspecter/trading_signal.git
cd trading_signal
```

## 2. Install everything (15–30 min)
```bash
bash deploy/ubuntu/install.sh
```
It installs Wine, MT5, Windows Python, the bridge, the bot environment and 4 auto-start services.

## 3. Copy your Telegram secrets
The `.env` file is not on GitHub (on purpose). From your Windows PC:
```bash
scp .env <user>@<server>:~/trading_signal/.env
```
Optional, for the 📊 Performance button: `scp -r reports <user>@<server>:~/trading_signal/`

## 4. Log in to MT5 once (VNC)
On the server:
```bash
bash deploy/ubuntu/vnc.sh
```
On your PC, open a tunnel, then a VNC viewer (RealVNC Viewer or TigerVNC) to `localhost:5900`:
```bash
ssh -L 5900:localhost:5900 <user>@<server>
```
In the MT5 window:
1. **File → Login to Trade Account**: your demo account (tick *Save password*).
2. **Tools → Options → Expert Advisors**: tick **Allow algorithmic trading**; untick the two
   "Disable… when the account/profile has been changed" boxes; keep "Disable… via external Python API" **unticked**.
3. Click **Algo Trading** in the toolbar so it is **green**.

Close the viewer and press Ctrl+C in `vnc.sh`. MT5 remembers the login.

## 5. Start
```bash
systemctl --user start goldbot-screen goldbot-mt5 goldbot-bridge goldbot
journalctl --user -u goldbot -f        # live bot log (Ctrl+C to stop watching)
```
You should get **🤖 Bot started** on Telegram.

**Stop the bot on your Windows PC** - only one copy may run at a time.

## Everyday commands
| What | Command |
|---|---|
| Bot status | `systemctl --user status goldbot` |
| Bot log | `journalctl --user -u goldbot -f` |
| Restart the bot | `systemctl --user restart goldbot` |
| Restart everything | `systemctl --user restart goldbot-screen goldbot-mt5 goldbot-bridge goldbot` |
| Stop everything | `systemctl --user stop goldbot goldbot-bridge goldbot-mt5 goldbot-screen` |
| Update the code | `git pull && systemctl --user restart goldbot` |
| See the MT5 window | `bash deploy/ubuntu/vnc.sh` + SSH tunnel |

## Troubleshooting
| Symptom | Fix |
|---|---|
| `MT5 initialize failed` / no data | Check `systemctl --user status goldbot-mt5 goldbot-bridge`; open VNC and check MT5 is logged in |
| 🤖 Auto-Trade "Algo Trading is OFF" | VNC → click **Algo Trading** (green) |
| Bridge errors after a reboot | `systemctl --user restart goldbot-bridge goldbot` |
| Wine install fails on a new Ubuntu version | Check https://wiki.winehq.org/Ubuntu for the right package source |

The Linux path relies on Wine and the community `mt5linux` bridge, which MetaQuotes does not officially
support. Test it on the demo account for a few days before relying on it.
