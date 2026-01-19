import pexpect
import sys
import time

HOST = "89.116.34.45"
USER = "root"
PASS = "Saklain@061524"

CMD_CHECK_CODE = """
cd /opt/gitco/alpha-trader-bot
echo "--- GIT LOG ---"
git log -1
echo ""
echo "--- PAGE.TSX CONTENT (GREP API) ---"
grep -C 5 "getApiUrl" crypto-dashboard/app/page.tsx
echo ""
echo "--- PM2 STATUS ---"
pm2 status
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

    child.sendline("cat > code_check.sh << 'EOF'")
    child.sendline(CMD_CHECK_CODE)
    child.sendline("EOF")
    child.expect(['#', '$'], timeout=10)

    print("🔎 RUNNING CODE CHECK...")
    child.sendline("bash code_check.sh")
    child.expect(['#', '$'], timeout=20)
    
    print("--- REPORT ---")
    print(child.before)
    
    child.sendline('exit')
    child.close()

except Exception as e:
    print(f"❌ Error: {e}")
    try: print("Last Output:", child.before)
    except: pass
