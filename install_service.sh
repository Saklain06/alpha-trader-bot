#!/bin/bash

SERVICE_NAME="alpha_bot.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
CURRENT_DIR=$(pwd)

echo "🛠️  Installing Alpha Trader as a System Service..."

# Check sudo access
if [ "$EUID" -ne 0 ]; then 
  echo "❌ Please run as root (use sudo)"
  exit 1
fi

echo "-> Copying service file..."
cp "$CURRENT_DIR/alpha_bot.service" "$SERVICE_PATH"

echo "-> Reloading systemd daemon..."
systemctl daemon-reload

echo "-> Enabling service to start on boot..."
systemctl enable $SERVICE_NAME

echo "-> Starting service now..."
systemctl restart $SERVICE_NAME

echo "✅ Success! The bot is running 24/7."
echo "   - Status: systemctl status $SERVICE_NAME"
echo "   - Logs:   journalctl -u alpha_bot -f"
