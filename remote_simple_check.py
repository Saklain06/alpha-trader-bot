import pexpect
import sys

HOST = "89.116.34.45"
USER = "root"
PASS = "Saklain@061524"

def run_cmd(child, cmd):
    print(f"Executing: {cmd}")
    child.sendline(cmd)
    child.expect(['#', '$'], timeout=10)
    print(child.before.strip())
    print("-" * 20)

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

    run_cmd(child, 'date')
    run_cmd(child, 'ls -F /opt/gitco/')
    run_cmd(child, 'ls -F /opt/gitco/alpha-trader-bot/')
    
    # Check git log
    run_cmd(child, 'cd /opt/gitco/alpha-trader-bot && git log -1 --oneline')
    
    # Check content
    run_cmd(child, 'grep "getApiUrl" crypto-dashboard/app/page.tsx -A 5')

    child.sendline('exit')
    child.close()

except Exception as e:
    print(f"❌ Error: {e}")
    try: print("Last Output:", child.before)
    except: pass
