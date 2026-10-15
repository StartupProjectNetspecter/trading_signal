#!/usr/bin/env bash
# Install the gold signal bot on an Ubuntu server (x86_64): Wine + MetaTrader 5 + mt5linux bridge + bot,
# with systemd user services so everything starts on boot.  Run as your normal user (not root):
#     bash deploy/ubuntu/install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
export WINEPREFIX="${WINEPREFIX:-$HOME/.mt5}"
export WINEARCH=win64
export WINEDEBUG=-all
export DISPLAY=:99
PY_VERSION=3.10.11
WIN_PY="$WINEPREFIX/drive_c/Program Files/Python310/python.exe"
MT5_EXE="$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe"

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }

say "Checking the machine"
[ "$(uname -m)" = "x86_64" ] || { echo "MT5 needs an Intel/AMD (x86_64) server. Found: $(uname -m)"; exit 1; }
[ "$(id -u)" != "0" ] || { echo "Run as your normal user (the script uses sudo when needed)."; exit 1; }
free -h | awk '/Mem:/ {print "RAM: " $2 " (2 GB minimum, 4 GB recommended)"}'

say "Installing Wine, virtual screen and Python"
sudo dpkg --add-architecture i386
sudo mkdir -pm755 /etc/apt/keyrings
sudo wget -qO /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key
CODENAME="$(lsb_release -cs)"
sudo wget -qNP /etc/apt/sources.list.d/ "https://dl.winehq.org/wine-builds/ubuntu/dists/${CODENAME}/winehq-${CODENAME}.sources"
sudo apt-get update
sudo apt-get install -y --install-recommends winehq-stable
sudo apt-get install -y xvfb x11vnc python3-venv python3-pip wget cabextract

say "Starting a temporary virtual screen"
Xvfb :99 -screen 0 1280x800x24 >/dev/null 2>&1 &
XVFB_PID=$!
trap 'kill $XVFB_PID 2>/dev/null || true' EXIT
sleep 3
wineboot -i >/dev/null 2>&1 || true

if [ ! -f "$MT5_EXE" ]; then
  say "Installing MetaTrader 5 (Windows) under Wine"
  wget -qO /tmp/mt5setup.exe https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe
  wine /tmp/mt5setup.exe /auto || true
  for _ in $(seq 1 60); do [ -f "$MT5_EXE" ] && break; sleep 5; done
  [ -f "$MT5_EXE" ] || { echo "MT5 install did not finish - re-run this script."; exit 1; }
fi

if [ ! -f "$WIN_PY" ]; then
  say "Installing Windows Python $PY_VERSION under Wine (for the MT5 bridge)"
  wget -qO /tmp/python-win.exe "https://www.python.org/ftp/python/${PY_VERSION}/python-${PY_VERSION}-amd64.exe"
  wine /tmp/python-win.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 || true
  [ -f "$WIN_PY" ] || { echo "Windows Python install failed - re-run this script."; exit 1; }
fi
wine "$WIN_PY" -m pip install --quiet --upgrade pip
wine "$WIN_PY" -m pip install --quiet MetaTrader5 mt5linux

say "Creating the Linux Python environment for the bot"
python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$REPO_DIR/.venv/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"
"$REPO_DIR/.venv/bin/pip" install --quiet rpyc
"$REPO_DIR/.venv/bin/pip" install --quiet --no-deps mt5linux   # keep our numpy/pandas versions

say "Writing systemd services (start on boot)"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
COMMON="Environment=DISPLAY=:99
Environment=WINEPREFIX=$WINEPREFIX
Environment=WINEDEBUG=-all"

cat > "$UNIT_DIR/goldbot-screen.service" <<EOF
[Unit]
Description=Gold bot - virtual screen for MT5
[Service]
ExecStart=/usr/bin/Xvfb :99 -screen 0 1280x800x24
Restart=always
[Install]
WantedBy=default.target
EOF

cat > "$UNIT_DIR/goldbot-mt5.service" <<EOF
[Unit]
Description=Gold bot - MetaTrader 5 (Wine)
After=goldbot-screen.service
Requires=goldbot-screen.service
[Service]
$COMMON
ExecStart=/usr/bin/wine "$MT5_EXE" /portable
Restart=always
RestartSec=20
[Install]
WantedBy=default.target
EOF

cat > "$UNIT_DIR/goldbot-bridge.service" <<EOF
[Unit]
Description=Gold bot - mt5linux bridge (Windows Python under Wine)
After=goldbot-mt5.service
Requires=goldbot-mt5.service
[Service]
$COMMON
ExecStartPre=/bin/sleep 20
ExecStart=$REPO_DIR/.venv/bin/python -m mt5linux "$WIN_PY"
Restart=always
RestartSec=20
[Install]
WantedBy=default.target
EOF

cat > "$UNIT_DIR/goldbot.service" <<EOF
[Unit]
Description=Gold signal bot (Telegram + auto-trade)
After=goldbot-bridge.service
Requires=goldbot-bridge.service
[Service]
WorkingDirectory=$REPO_DIR
Environment=MT5_BRIDGE_HOST=localhost
Environment=MT5_BRIDGE_PORT=18812
Environment="MT5_TERMINAL_PATH=C:/Program Files/MetaTrader 5/terminal64.exe"
Environment=PYTHONUNBUFFERED=1
ExecStartPre=/bin/sleep 15
ExecStart=$REPO_DIR/.venv/bin/python run_live.py
Restart=always
RestartSec=30
[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable goldbot-screen goldbot-mt5 goldbot-bridge goldbot
sudo loginctl enable-linger "$USER"   # keep services running without being logged in

say "Done. Next steps (see docs/UBUNTU_DEPLOY.md):"
cat <<EOF
 1. Copy your .env (Telegram token) to $REPO_DIR/.env
 2. Start MT5 once and log in through VNC:   bash deploy/ubuntu/vnc.sh
 3. Start everything:                        systemctl --user start goldbot-screen goldbot-mt5 goldbot-bridge goldbot
 4. Watch the bot log:                       journalctl --user -u goldbot -f
EOF
