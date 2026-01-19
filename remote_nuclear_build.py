import pexpect
import sys
import time

HOST = "89.116.34.45"
USER = "root"
PASS = "Saklain@061524"

CMD_NUCLEAR_BUILD = """
export PATH=$PATH:/usr/bin:/usr/local/bin
cd /opt/gitco/alpha-trader-bot

echo "📥 PULLING..."
git pull

echo "☢️ NUCLEAR CACHE CLEAR..."
cd crypto-dashboard
rm -rf .next
rm -rf node_modules
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

    child.sendline("cat > nuclear_build.sh << 'EOF'")
    child.sendline(CMD_NUCLEAR_BUILD)
    child.sendline("EOF")
    child.expect(['#', '$'], timeout=10)

    print("☢️ EXECUTING NUCLEAR BUILD (This takes time)...")
    child.sendline("bash nuclear_build.sh")
    
    # 10 min timeout
    child.expect(['#', '$'], timeout=600)
    
    print("✅ Build complete!")
    print(child.before)
    
    child.sendline('exit')
    child.close()

except Exception as e:
    print(f"❌ Error: {e}")
    try: print("Last Output:", child.before)
    except: pass
