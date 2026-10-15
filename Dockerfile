# Gold signal bot: MetaTrader 5 (Wine) + mt5linux bridge + Python bot in one container.
#   docker compose up -d --build
# MT5 is a Windows program, so it runs under Wine with a virtual screen (Xvfb).
FROM ubuntu:22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Wine (WineHQ stable), virtual screen, VNC (one-time MT5 login), Python
RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates wget gnupg cabextract procps xauth xvfb x11vnc \
        python3 python3-venv python3-pip \
    && mkdir -pm755 /etc/apt/keyrings \
    && wget -qO /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key \
    && wget -qNP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources \
    && apt-get update \
    && apt-get install -y --install-recommends winehq-stable \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. UID/GID default to 1000 (the usual first user on the host) so the
# ./ code mount is readable and the /backup state folder can be chowned to it.
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid ${APP_GID} appgroup \
    && useradd --uid ${APP_UID} --gid ${APP_GID} --create-home appuser \
    && mkdir -p /home/appuser/.mt5 /app/data/state /tmp/.X11-unix \
    && chmod 1777 /tmp/.X11-unix \
    && chown -R appuser:appgroup /home/appuser /app

# Python environment for the bot (the code itself is mounted at /app by compose)
COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r /tmp/requirements.txt \
    && /opt/venv/bin/pip install --no-deps mt5linux

COPY deploy/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER appuser
ENV HOME=/home/appuser \
    DISPLAY=:99 \
    WINEPREFIX=/home/appuser/.mt5 \
    WINEARCH=win64 \
    WINEDEBUG=-all \
    MT5_BRIDGE_HOST=localhost \
    MT5_BRIDGE_PORT=18812 \
    MT5_TERMINAL_PATH="C:/Program Files/MetaTrader 5/terminal64.exe" \
    GOLDBOT_STATE_DIR=/app/data/state

WORKDIR /app
EXPOSE 5900

# Healthy = the bot process is running (first start installs MT5, hence the long start period)
HEALTHCHECK --interval=60s --timeout=5s --start-period=20m --retries=3 \
    CMD pgrep -f "run_live.py" >/dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
