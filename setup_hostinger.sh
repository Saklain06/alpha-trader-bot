#!/bin/bash

# ==============================================================================
# 🚀 HOSTINGER VPS SETUP SCRIPT
# ==============================================================================
# This script automates the installation of the Trading Bot on a fresh Ubuntu VPS.
# Run this as ROOT.

set -e # Exit on error

# ------------------------------------------------------------------------------
# 1. PRELIMINARY CHECKS
# ------------------------------------------------------------------------------
if [ "$EUID" -ne 0 ]; then
  echo "❌ Please run as root (sudo bash setup_hostinger.sh)"
  exit 1
fi

echo "🟢 Starting Setup..."
USER_HOME=$(pwd)
echo "📂 Working Directory: $USER_HOME"

# ------------------------------------------------------------------------------
# 2. SYSTEM UPDATES & DEPENDENCIES
# ------------------------------------------------------------------------------
echo "🔄 Updating System Packages..."
apt update && apt upgrade -y

echo "📦 Installing Dependencies (Python, Node, Nginx, UFW)..."
apt install -y python3-pip python3-venv git curl nginx ufw build-essential

# Install Node.js 18.x
if ! command -v node &> /dev/null; then
    echo "📦 Installing Node.js..."
    curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
    apt install -y nodejs
fi

# Install PM2
if ! command -v pm2 &> /dev/null; then
    echo "📦 Installing PM2..."
    npm install -g pm2
fi

# ------------------------------------------------------------------------------
# 3. FIREWALL SETUP
# ------------------------------------------------------------------------------
echo "🛡️ Configuring Firewall..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw allow 8000/tcp # Backend API
ufw --force enable
ufw status | grep 8000

# ------------------------------------------------------------------------------
# 4. BACKEND SETUP
# ------------------------------------------------------------------------------
echo "🐍 Setting up Python Environment..."

# Create Venv if not exists
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    echo "❌ requirements.txt not found!"
    exit 1
fi

# Create Systemd Service for Backend
echo "⚙️ Creating Systemd Service..."
SERVICE_FILE="/etc/systemd/system/alpha_bot.service"

cat > $SERVICE_FILE <<EOF
[Unit]
Description=Alpha Trader Bot Backend
After=network.target

[Service]
User=root
WorkingDirectory=$USER_HOME
ExecStart=$USER_HOME/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment=TRADE_MODE=live
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable alpha_bot
systemctl restart alpha_bot
echo "✅ Backend Service Started!"

# ------------------------------------------------------------------------------
# 5. FRONTEND SETUP
# ------------------------------------------------------------------------------
echo "🎨 Setting up Frontend..."
cd crypto-dashboard

if [ ! -d "node_modules" ]; then
    npm install
fi

echo "🏗 Building Next.js App..."
npm run build

echo "🚀 Starting Frontend with PM2..."
pm2 delete dashboard 2>/dev/null || true
pm2 start npm --name "dashboard" -- start -- -p 3000

pm2 save
# Ensure PM2 starts on boot
pm2 startup systemd -u root --hp /root 2>/dev/null || true

cd ..

# ------------------------------------------------------------------------------
# 6. NGINX REVERSE PROXY
# ------------------------------------------------------------------------------
echo "🌐 Configuring Nginx..."
NGINX_CONF="/etc/nginx/sites-available/default"

cat > $NGINX_CONF <<EOF
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
    }

    # Optional: Proxy API if we wanted to hide port 8000
    # Proxy API from /api to localhost:8000
    location /api/ {
        rewrite ^/api/(.*) /\$1 break;
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
    }
}
EOF

nginx -t && systemctl restart nginx

# ------------------------------------------------------------------------------
# 7. FINISH
# ------------------------------------------------------------------------------
IP=$(curl -s ifconfig.me)
echo "========================================================"
echo "✅ DEPLOYMENT COMPLETE!"
echo "========================================================"
echo "🌍 Dashboard: http://$IP"
echo "🔌 API Port:  http://$IP:8000/docs"
echo "========================================================"
echo "👉 Make sure port 8000 is open in your Hostinger Firewall!"
