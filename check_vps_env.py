
import pexpect
import sys

HOST = "89.116.34.45"
USER = "root"
PASS = "Saklain@061524"

def check_env():
    print(f"🔍 Checking .env on {HOST}...")
    child = pexpect.spawn(f'ssh {USER}@{HOST} "cat /opt/gitco/alpha-trader-bot/.env"', encoding='utf-8', timeout=30)
    
    i = child.expect(['password:', 'continue connecting', pexpect.EOF, pexpect.TIMEOUT])
    if i == 0:
        child.sendline(PASS)
    elif i == 1:
        child.sendline('yes')
        child.expect('password:')
        child.sendline(PASS)
        
    child.expect(pexpect.EOF)
    print("\n--- REMOTE .ENV FILE ---")
    print(child.before)
    print("------------------------")

if __name__ == "__main__":
    check_env()
