#!/bin/bash
# VPS Paper Mode Setup Script
# Run this directly on the VPS

set -e

echo "========================================================================"
echo "VPS PAPER MODE SETUP"
echo "========================================================================"

cd /opt/gitco/alpha-trader-bot

# 1. Update .env
echo "1. Setting TRADE_MODE=paper..."
grep -q "^TRADE_MODE=" .env && sed -i "s/^TRADE_MODE=.*/TRADE_MODE=paper/" .env || echo "TRADE_MODE=paper" >> .env
echo "✅ .env updated"
cat .env
echo ""

# 2. Stop any running instances
echo "2. Stopping existing processes..."
systemctl stop alpha_bot 2>/dev/null || true
pkill -9 -f "python.*main.py" 2>/dev/null || true
pkill -9 -f "uvicorn" 2>/dev/null || true
sleep 2
echo "✅ Stopped"
echo ""

# 3. Check if venv exists
echo "3. Checking Python environment..."
if [ ! -d "venv" ]; then
    echo "Creating venv..."
    python3 -m venv venv
fi
./venv/bin/python3 --version
echo "✅ Python environment ready"
echo ""

# 4. Install dependencies
echo "4. Installing dependencies..."
./venv/bin/pip install -q -r requirements.txt
echo "✅ Dependencies installed"
echo ""

# 5. Start bot manually first (to see errors)
echo "5. Starting bot manually to check for errors..."
echo "Running: ./venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000"
echo "Press Ctrl+C after 5 seconds if it starts successfully"
echo ""
timeout 10 ./venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 || true
echo ""

# 6. If manual start worked, start as service
echo "6. Starting as background service..."
nohup ./venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &
sleep 3
echo "✅ Started in background"
echo ""

# 7. Verify
echo "7. Verification..."
ps aux | grep "[p]ython.*main.py\|[u]vicorn"
echo ""

echo "8. Testing API..."
curl -s http://localhost:8000/stats | python3 -m json.tool | head -20
echo ""

echo "========================================================================"
echo "✅ SETUP COMPLETE"
echo "========================================================================"
echo "Bot should now be running in PAPER MODE with $200 balance"
echo "========================================================================"
