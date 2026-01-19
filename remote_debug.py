import pexpect
import sys
import time

HOST = "89.116.34.45"
USER = "root"
PASS = "Saklain@061524"

try:
    print(f"🔄 Connecting to {USER}@{HOST}...")
    child = pexpect.spawn(f'ssh {USER}@{HOST}', encoding='utf-8', timeout=60)
    
    # Send all output to stdout so we can see it in agent logs
    child.logfile = sys.stdout
    
    i = child.expect(['password:', 'continue connecting', pexpect.EOF, pexpect.TIMEOUT])
    if i == 1:
        child.sendline('yes')
        child.expect('password:')
    
    child.sendline(PASS)
    
    # Wait for login
    time.sleep(5)
    
    print("\n--- SENDING COMMANDS ---\n")
    
    child.sendline('ls -la /opt/gitco')
    time.sleep(2)
    
    child.sendline('cd /opt/gitco/alpha-trader-bot && git log -1 --oneline')
    time.sleep(2)
    
    child.sendline('grep "getApiUrl" crypto-dashboard/app/page.tsx -A 5')
    time.sleep(2)
    
    print("\n--- DONE ---\n")
    
    child.sendline('exit')
    child.close()

except Exception as e:
    print(f"❌ Error: {e}")
