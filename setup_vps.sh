#!/bin/bash
# ==============================================================================
# Alpha Trader Bot - Hostinger VPS 1-Click Installer
# ==============================================================================
set -e

echo ""
echo "=========================================================================="
echo "    🚀 DEPLOYING ALPHA TRADER BOT (1H FIBONACCI + TRAILING SL)           "
echo "=========================================================================="
echo ""

# 1. Update OS packages
echo "[1/6] Updating system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git curl ufw

# 2. Setup directory & fetch code
INSTALL_DIR="/opt/alpha-trader-bot"
echo "[2/6] Setting up project in $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

if [ -d "$INSTALL_DIR/.git" ]; then
    echo "Updating existing repository..."
    cd "$INSTALL_DIR"
    git fetch origin main
    git reset --hard origin/main
else
    echo "Cloning repository from GitHub..."
    git clone https://github.com/Saklain06/alpha-trader-bot.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# 3. Setup Python venv
echo "[3/6] Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -q -r requirements.txt

# 4. Setup .env if missing
echo "[4/6] Checking configuration (.env)..."
if [ ! -f ".env" ]; then
    cat << 'EOF' > .env
TRADE_MODE=paper
BASE_BALANCE=800
MAX_POSITION_COUNT=2
MAX_ORDER_USD=2000
MAX_SYMBOL_EXPOSURE_USD=2000
MAX_DAILY_LOSS_USD=150
EOF
    echo "Created default .env in Paper Mode."
fi

# 5. Configure Firewall
echo "[5/6] Configuring firewall rules (SSH 22 & Web UI 8000)..."
ufw allow 22/tcp -q || true
ufw allow 8000/tcp -q || true
ufw --force enable -q || true

# 6. Install & Start Systemd Service
echo "[6/6] Installing systemd background service..."
cat << 'EOF' > /etc/systemd/system/alpha_bot.service
[Unit]
Description=Alpha Trader Bot (24/7 Binance Spot)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/alpha-trader-bot
ExecStart=/opt/alpha-trader-bot/venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment=PYTHONIOENCODING=utf-8

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable alpha_bot -q
systemctl restart alpha_bot

SERVER_IP=$(curl -s -m 5 https://api.ipify.org || hostname -I | awk '{print $1}')

echo ""
echo "=========================================================================="
echo "    🎉 ALPHA TRADER BOT IS NOW RUNNING 24/7 ON YOUR VPS!                "
echo "=========================================================================="
echo "  Web Dashboard:  http://${SERVER_IP}:8000"
echo "  Check Status:   systemctl status alpha_bot"
echo "  View Live Logs: journalctl -u alpha_bot -f"
echo "  Edit Config:    nano /opt/alpha-trader-bot/.env"
echo "=========================================================================="
echo ""
