import os
import sys
import pexpect
import subprocess
from datetime import datetime

HOST = "89.116.34.45"
USER = "root"
PASS = "Saklain@061524"
REMOTE_DIR = "/opt/gitco/alpha-trader-bot"
ZIP_NAME = "project_deploy.zip"

def create_zip():
    print("📦 Zipping project...")
    cmd = [
        "zip", "-r", ZIP_NAME,
        "main.py",
        "database.py",
        "logic",
        "crypto-dashboard",
        "requirements.txt",
        ".env",
        "setup_hostinger.sh",
        "alpha_bot.service",
        "DEPLOYMENT.md",
        "auth.py",
        "seed_user.py"
    ]
    subprocess.run(cmd + ["-x", "crypto-dashboard/node_modules/*", "crypto-dashboard/.next/*", "*.pyc", "__pycache__/*"], check=True)
    print("✅ Zip created.")

def upload_and_deploy():
    print(f"🚀 Deploying to {HOST}...")
    
    # Upload
    print("📤 Uploading zip...")
    child = pexpect.spawn(f'scp {ZIP_NAME} {USER}@{HOST}:/root/{ZIP_NAME}', encoding='utf-8', timeout=120)
    i = child.expect(['password:', 'continue connecting', pexpect.EOF, pexpect.TIMEOUT])
    if i == 1:
        child.sendline('yes')
        child.expect('password:')
    child.sendline(PASS)
    child.expect(pexpect.EOF)
    print("✅ Upload complete.")

    # Remote Commands
    print("🔄 Running Remote Build (This may take 2-3 minutes)...")
    
    # We use a raw text block for the remote script to avoid escaping issues in Python strings
    # Note: We escape $ variables with \$ if we were using f-strings, but this is a triple-quoted string.
    # Actually, in standard python strings, $ is literal. So $host stays $host.
    REMOTE_SCRIPT = r"""
set -e

# Stop Services
systemctl stop alpha_bot || true
pm2 stop dashboard || true

# Prepare Directory
mkdir -p /opt/gitco/alpha-trader-bot

# Backup DB
if [ -f /opt/gitco/alpha-trader-bot/trades.db ]; then
    cp /opt/gitco/alpha-trader-bot/trades.db /root/trades.db.bak
fi

# Unzip
unzip -o /root/project_deploy.zip -d /opt/gitco/alpha-trader-bot

# Restore DB
if [ -f /root/trades.db.bak ]; then
    mv /root/trades.db.bak /opt/gitco/alpha-trader-bot/trades.db
fi

# Setup Permissions
chmod +x /opt/gitco/alpha-trader-bot/setup_hostinger.sh

# Install Backend
cd /opt/gitco/alpha-trader-bot
if [ ! -d "venv" ]; then
    echo "Creating venv..."
    python3 -m venv venv
fi
./venv/bin/pip install -r requirements.txt

# Run DB Migration (Fix Missing Columns)
echo "🔄 Running DB Migration..."
python3 migrate_db_v2.py

# Build Frontend (Nuclear Cache Clear)
cd crypto-dashboard
echo "🧹 NUKING NEXT.JS CACHE..."
rm -rf .next
rm -rf node_modules/.cache
npm install
npm run build

# Apply Nginx Config (Aggressive Caching Fix)
echo "🔧 Updating Nginx Config..."
cat > /etc/nginx/sites-available/default << 'EOF_NGINX'
server {
    listen 80;
    server_name _;

    # Backend API Proxy
    location /api/ {
        rewrite ^/api/(.*) /$1 break;
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # Frontend Proxy (Next.js)
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;

        # [FIX] KILL CACHE
        add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0" always;
        add_header Pragma "no-cache" always;
        add_header Expires "0" always;
    }
}
EOF_NGINX

# Reload Nginx
nginx -t && systemctl reload nginx

# Restart Services
pm2 restart dashboard
systemctl restart alpha_bot

echo "✅ DEPLOYMENT SUCCESSFUL"
"""
    
    child = pexpect.spawn(f'ssh {USER}@{HOST}', encoding='utf-8', timeout=600)
    i = child.expect(['password:', 'continue connecting', pexpect.EOF, pexpect.TIMEOUT])
    if i == 1: 
        child.sendline('yes'); child.expect('password:')
    child.sendline(PASS)
    child.expect(['#', '$'])
    
    child.sendline(f"cat > /root/deploy_exec.sh << 'EOF_SCRIPT'")
    # We need to be careful sending the script if it contains EOF_SCRIPT inside it? No.
    # But sending large blocks via sendline can be tricky.
    # We will split strictly by lines.
    for line in REMOTE_SCRIPT.split('\n'):
        child.sendline(line)
    
    child.sendline("EOF_SCRIPT")
    child.expect(['#', '$'])
    
    child.sendline("bash /root/deploy_exec.sh")
    
    # Stream output
    while True:
        try:
            line = child.readline()
            if not line: break
            print(line.strip())
            if "DEPLOYMENT SUCCESSFUL" in line:
                break
        except pexpect.TIMEOUT:
            print("...working...")
            continue
        except pexpect.EOF:
            break
    child.close()

if __name__ == "__main__":
    try:
        create_zip()
        upload_and_deploy()
        os.remove(ZIP_NAME)
    except Exception as e:
        print(f"❌ Error: {e}")
