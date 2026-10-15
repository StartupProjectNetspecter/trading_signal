#!/usr/bin/env bash
# One-time (or occasional) access to the MT5 window on the server, to log in and switch on Algo Trading.
# Only listens on localhost - connect through an SSH tunnel from your PC:
#     ssh -L 5900:localhost:5900 <user>@<server>
# then open a VNC viewer (e.g. RealVNC Viewer / TigerVNC) to:  localhost:5900
set -euo pipefail
systemctl --user start goldbot-screen goldbot-mt5
echo "VNC on localhost:5900 (Ctrl+C to stop). In MT5:"
echo "  File > Login to Trade Account  (your demo)"
echo "  Tools > Options > Expert Advisors > tick 'Allow algorithmic trading'"
echo "  Click the 'Algo Trading' button so it is green"
x11vnc -display :99 -localhost -nopw -forever -quiet
