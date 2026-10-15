#!/usr/bin/env bash
# Container start: virtual screen + VNC, first-run install of MT5 and Windows Python (kept in the
# Wine prefix volume), then MT5, the mt5linux bridge and the bot - each restarted if it stops.
set -u

PY_VERSION=3.10.11
WIN_PY="$WINEPREFIX/drive_c/Program Files/Python310/python.exe"
MT5_EXE="$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe"
log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S') UTC] $*"; }

# ---- virtual screen + VNC (port 5900; compose publishes it on the host's localhost only) ----
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
Xvfb :99 -screen 0 1280x800x24 >/dev/null 2>&1 &
sleep 2
if [ -n "${VNC_PASSWORD:-}" ]; then
  x11vnc -storepasswd "$VNC_PASSWORD" $HOME/.vncpass >/dev/null 2>&1
  VNC_AUTH=(-rfbauth $HOME/.vncpass)
else
  VNC_AUTH=(-nopw)
fi
x11vnc -display :99 -forever -shared -quiet -rfbport 5900 "${VNC_AUTH[@]}" >/dev/null 2>&1 &

# ---- first run: install MT5 and Windows Python into the persistent Wine prefix ----
if [ ! -f "$MT5_EXE" ] || [ ! -f "$WIN_PY" ]; then
  log "First start: installing MetaTrader 5 and Windows Python under Wine (5-15 minutes)..."
  wineboot -i >/dev/null 2>&1 || true
fi
if [ ! -f "$MT5_EXE" ]; then
  wget -qO /tmp/mt5setup.exe https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe
  wine /tmp/mt5setup.exe /auto >/dev/null 2>&1 &
  for _ in $(seq 1 120); do [ -f "$MT5_EXE" ] && break; sleep 5; done
  sleep 20
  wineserver -k || true
  [ -f "$MT5_EXE" ] && log "MetaTrader 5 installed" || log "ERROR: MetaTrader 5 install failed - restart the container to retry"
fi
if [ ! -f "$WIN_PY" ]; then
  wget -qO /tmp/python-win.exe "https://www.python.org/ftp/python/${PY_VERSION}/python-${PY_VERSION}-amd64.exe"
  wine /tmp/python-win.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 >/dev/null 2>&1 || true
  wine "$WIN_PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1
  wine "$WIN_PY" -m pip install --quiet MetaTrader5 mt5linux >/dev/null 2>&1
  [ -f "$WIN_PY" ] && log "Windows Python + MetaTrader5 + mt5linux installed" || log "ERROR: Windows Python install failed - restart the container to retry"
fi

# ---- MetaTrader 5 (restarts if it closes) ----
(
  while true; do
    log "Starting MetaTrader 5"
    wine "$MT5_EXE" /portable >/dev/null 2>&1
    log "MetaTrader 5 stopped - restarting in 10s"
    sleep 10
  done
) &
sleep 30

# ---- mt5linux bridge (restarts if it stops) ----
(
  while true; do
    log "Starting mt5linux bridge on port ${MT5_BRIDGE_PORT}"
    /opt/venv/bin/python -m mt5linux "$WIN_PY" >/dev/null 2>&1
    log "Bridge stopped - restarting in 10s"
    sleep 10
  done
) &
sleep 15

# ---- the bot (foreground; restarts if it stops, e.g. MT5 not logged in yet) ----
cd /app
[ -f .env ] || log "WARNING: /app/.env missing - Telegram will be off. Create it next to docker-compose.yml."
while true; do
  log "Starting the bot"
  /opt/venv/bin/python run_live.py
  log "Bot stopped - restarting in 30s (first time: log in to MT5 through VNC)"
  sleep 30
done
