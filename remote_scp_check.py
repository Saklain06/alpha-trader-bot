import pexpect
import sys

HOST = "89.116.34.45"
USER = "root"
PASS = "Saklain@061524"
REMOTE_PATH = "/opt/gitco/alpha-trader-bot/crypto-dashboard/app/page.tsx"
LOCAL_PATH = "vps_page.tsx"

try:
    cmd = f"scp {USER}@{HOST}:{REMOTE_PATH} {LOCAL_PATH}"
    print(f"Executing: {cmd}")
    
    child = pexpect.spawn(cmd, encoding='utf-8', timeout=60)
    
    i = child.expect(['password:', 'continue connecting', pexpect.EOF, pexpect.TIMEOUT])
    if i == 1:
        child.sendline('yes')
        child.expect('password:')
    
    child.sendline(PASS)
    
    # Wait for completion
    child.expect(pexpect.EOF)
    
    print("✅ Transfer complete!")

except Exception as e:
    print(f"❌ Error: {e}")
