#!/usr/bin/env python3
import requests
import os
from jose import jwt
from datetime import datetime, timedelta, timezone

# Load Env
from dotenv import load_dotenv
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE_THIS_IN_PRODUCTION_TO_A_VERY_LONG_RANDOM_STRING")
ALGORITHM = "HS256"

# Create Token
def create_token():
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    data = {"sub": "admin", "role": "admin", "exp": expire}
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

token = create_token()
headers = {"Authorization": f"Bearer {token}"}
base_url = "http://localhost:8000"

print("="*60)
print("TESTING RISK PERCENTAGE UPDATE (VPS LOCALHOST)")
print("="*60)

# 1. Check Initial
try:
    r = requests.get(f"{base_url}/risk_pct", headers=headers)
    print(f"Initial GET: {r.status_code} -> {r.json()}")
except Exception as e:
    print(f"Error connecting: {e}")
    exit(1)

# 2. Update to 1.5% (0.015)
print("\nUpdating to 1.5% (0.015)...")
r = requests.post(f"{base_url}/risk_pct?pct=0.015", headers=headers)
print(f"POST Response: {r.status_code} -> {r.json()}")

# 3. Verify Update
r = requests.get(f"{base_url}/risk_pct", headers=headers)
print(f"Verify GET: {r.status_code} -> {r.json()}")

if r.json().get("risk_pct") == 0.015:
    print("✅ SUCCESS: Value updated correctly!")
else:
    print("❌ ERROR: Value did not update!")

# 4. Revert to 2.0% (0.02)
print("\nReverting to 2.0% (0.02)...")
r = requests.post(f"{base_url}/risk_pct?pct=0.02", headers=headers)
print(f"Revert POST: {r.status_code} -> {r.json()}")

print("="*60)
