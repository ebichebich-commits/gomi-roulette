#!/usr/bin/env bash
# ebiserver (Ubuntu) 用セットアップ: gomi-roulette と gomi-roulette-data を clone し、systemd で常駐起動する。
#   bash install-ebiserver.sh            # ~/gomi-roulette, ~/gomi-roulette-data に配置
# 非公開リポジトリの clone には、事前に git の認証（PAT / SSH鍵）を設定しておくこと。
set -euo pipefail

BASE="${BASE:-$HOME}"
PORT="${PORT:-8095}"
APP_URL="${APP_URL:-https://github.com/ebichebich-commits/gomi-roulette.git}"
DATA_URL="${DATA_URL:-https://github.com/ebichebich-commits/gomi-roulette-data.git}"
APP_DIR="$BASE/gomi-roulette"
DATA_DIR="$BASE/gomi-roulette-data"

[ -d "$APP_DIR/.git" ]  && git -C "$APP_DIR" pull --ff-only  || git clone "$APP_URL"  "$APP_DIR"
[ -d "$DATA_DIR/.git" ] && git -C "$DATA_DIR" pull --ff-only || git clone "$DATA_URL" "$DATA_DIR"

PY="$(command -v python3)"
sudo tee /etc/systemd/system/gomi-roulette.service >/dev/null <<EOF
[Unit]
Description=Gomi/Souji duty roulette (web)
After=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
Environment=GOMI_ROULETTE_DATA_DIR=$DATA_DIR
ExecStart=$PY $APP_DIR/web/server.py --host 0.0.0.0 --port $PORT
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now gomi-roulette
sudo systemctl restart gomi-roulette
sleep 1
systemctl --no-pager status gomi-roulette | head -n 8
echo "OK: http://$(hostname):$PORT/  (Tailscale: http://<tailscale名またはIP>:$PORT/)"
