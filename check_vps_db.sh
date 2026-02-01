#!/bin/bash
# Simple VPS database check script
# This will show the exact current state

echo "========================================"
echo "VPS DATABASE STATE CHECK"
echo "========================================"

cd /opt/gitco/alpha-trader-bot

echo ""
echo "1. RISK_PCT VALUE:"
echo "-------------------"
sqlite3 trades.db "SELECT key, value FROM app_state WHERE key='risk_pct';"

echo ""
echo "2. ALL STATE VALUES:"
echo "-------------------"
sqlite3 trades.db "SELECT key, value FROM app_state ORDER BY key;"

echo ""
echo "3. TRADE COUNT:"
echo "-------------------"
sqlite3 trades.db "SELECT COUNT(*) FROM trades;"

echo ""
echo "4. BOT PROCESS:"
echo "-------------------"
ps aux | grep "[p]ython.*main.py\|[u]vicorn" || echo "No process found"

echo ""
echo "5. API TEST:"
echo "-------------------"
curl -s http://localhost:8000/stats 2>&1 | python3 -m json.tool 2>&1 | head -30

echo ""
echo "========================================"
