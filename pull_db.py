
import pexpect
import sys

HOST = "89.116.34.45"
USER = "root"
PASS = "Saklain@061524"
REMOTE_DB = "/opt/gitco/alpha-trader-bot/trades.db"
LOCAL_DB = "trades_vps_check.db"

def pull_db():
    print(f"📥 Pulling {REMOTE_DB} from {HOST}...")
    cmd = f"scp {USER}@{HOST}:{REMOTE_DB} {LOCAL_DB}"
    
    child = pexpect.spawn(cmd, encoding='utf-8', timeout=60)
    i = child.expect(['password:', 'continue connecting', pexpect.EOF, pexpect.TIMEOUT])
    
    if i == 0:
        child.sendline(PASS)
    elif i == 1:
        child.sendline('yes')
        child.expect('password:')
        child.sendline(PASS)
        
    child.expect(pexpect.EOF)
    print("✅ Database pulled as trades_vps_check.db")

if __name__ == "__main__":
    pull_db()
