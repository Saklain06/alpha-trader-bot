#!/bin/bash

# Function to clean up background processes
cleanup() {
    echo "🛑 Stopping System..."
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID
    fi
    exit 0
}

# Trap signals
trap cleanup SIGINT SIGTERM

echo "🚀 Starting Alpha Trader System (Production Mode)..."

# 1. Start Backend with Auto-Restart Supervisor
echo "-> Starting Backend Supervisor..."
(
    while true; do
        echo "🔄 [SUPERVISOR] Starting Backend on port 8000..."
        ./venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 > server.log 2>&1
        
        EXIT_CODE=$?
        echo "⚠️ [SUPERVISOR] Backend crashed with exit code $EXIT_CODE. Restarting in 5 seconds..."
        sleep 5
    done
) &
BACKEND_SUPERVISOR_PID=$!
BACKEND_PID=$BACKEND_SUPERVISOR_PID # For cleanup tracking

# Wait for backend to be ready (Initial check)
echo "-> Waiting for backend to be ready..."
MAX_ATTEMPTS=30
ATTEMPT=0
while ! curl -s http://localhost:8000/stats > /dev/null; do
    sleep 1
    ATTEMPT=$((ATTEMPT + 1))
    if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
        echo "⚠️ Backend taking long to start (or crashing loop). Check server.log."
        break # Don't exit, let supervisor handle it, but proceed to frontend
    fi
done
echo "✅ Backend seems UP."

# 2. Start Frontend
echo "-> Starting Frontend Dashboard..."
cd crypto-dashboard
npm run dev

# If frontend exits, kill backend
cleanup
