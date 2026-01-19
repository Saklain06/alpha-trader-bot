import pexpect
import sys
import time

HOST = "89.116.34.45"
USER = "root"
PASS = "Saklain@061524"

CMD_FAST_UPDATE = """
export PATH=$PATH:/usr/bin:/usr/local/bin
cd /opt/gitco/alpha-trader-bot

echo "📥 PULLING LATEST CHANGES..."
git pull

echo "🏗 BUILDING FRONTEND..."
cd crypto-dashboard
npm install
npm run build

echo "🚀 RESTARTING PM2..."
pm2 restart dashboard
"""

try:
    print(f"🔄 Connecting to {USER}@{HOST}...")
    child = pexpect.spawn(f'ssh {USER}@{HOST}', encoding='utf-8', timeout=60)
    
    i = child.expect(['password:', 'continue connecting', pexpect.EOF, pexpect.TIMEOUT])
    if i == 1:
        child.sendline('yes')
        child.expect('password:')
    
    child.sendline(PASS)
    child.expect(['#', '$'], timeout=10)
    print("✅ Logged in!")

    child.sendline("cat > fast_update.sh << 'EOF'")
    child.sendline(CMD_FAST_UPDATE)
    child.sendline("EOF")
    child.expect(['#', '$'], timeout=10)

    print("🚀 EXECUTING FAST UPDATE...")
    child.sendline("bash fast_update.sh")
    
    # 5 minute timeout for build
    child.expect(['#', '$'], timeout=300)
    
    print("✅ Update complete!")
    print(child.before)
    
    child.sendline('exit')
    child.close()

except Exception as e:
    print(f"❌ Error: {e}")
    try: print("Last Output:", child.before)
    except: pass
