
import pexpect
import sys

HOST = "89.116.34.45"
USER = "root"
PASS = "Saklain@061524"
REMOTE_FILE = "/opt/gitco/alpha-trader-bot/logic/strategy.py"

def check_remote_strategy():
    print(f"🔍 Checking {REMOTE_FILE} on {HOST}...")
    # grep for a removed filter to confirm it's GONE
    # "Chase Protection" was removed. So grep should FAIL.
    
    cmd = f'ssh {USER}@{HOST} "grep \'Chase Protection\' {REMOTE_FILE}"'
    child = pexpect.spawn(cmd, encoding='utf-8', timeout=30)
    
    i = child.expect(['password:', 'continue connecting', pexpect.EOF, pexpect.TIMEOUT])
    if i == 0:
        child.sendline(PASS)
    elif i == 1:
        child.sendline('yes')
        child.expect('password:')
        child.sendline(PASS)
        
    child.expect(pexpect.EOF)
    output = child.before.strip()
    
    print("\n--- GREP OUTPUT (Should be empty) ---")
    print(output)
    
    if "Chase Protection" in output:
        print("\n❌ FAILED: Chase Protection still found on VPS!")
    else:
        print("\n✅ SUCCESS: Chase Protection NOT found. Revert is LIVE.")

if __name__ == "__main__":
    check_remote_strategy()
