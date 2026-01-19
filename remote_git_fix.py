import pexpect
import sys
import time

HOST = "89.116.34.45"
USER = "root"
PASS = "Saklain@061524"

CMD_GIT_FIX = """
export PATH=$PATH:/usr/bin:/usr/local/bin
cd /opt/gitco/alpha-trader-bot

echo "--- GIT STATUS (BEFORE) ---"
git status
git log -1 --oneline

echo "--- FETCHING ---"
git fetch --all

echo "--- HARD RESET ---"
git reset --hard origin/main

echo "--- GIT STATUS (AFTER) ---"
git log -1 --oneline

echo "--- CHECKING FILE CONTENT ---"
grep "const API =" crypto-dashboard/app/page.tsx || echo "Old API const GONE (Good)"
grep "API_REF.current" crypto-dashboard/app/page.tsx | head -n 3

echo "--- REBUILDING ---"
cd crypto-dashboard
npm install
npm run build
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

    child.sendline("cat > git_fix.sh << 'EOF'")
    child.sendline(CMD_GIT_FIX)
    child.sendline("EOF")
    child.expect(['#', '$'], timeout=10)

    print("🔧 EXECUTING GIT FORCE FIX & REBUILD...")
    child.sendline("bash git_fix.sh")
    
    # 5 min timeout for build
    child.expect(['#', '$'], timeout=300)
    
    print("✅ Fix process complete!")
    print(child.before)
    
    child.sendline('exit')
    child.close()

except Exception as e:
    print(f"❌ Error: {e}")
    try: print("Last Output:", child.before)
    except: pass
