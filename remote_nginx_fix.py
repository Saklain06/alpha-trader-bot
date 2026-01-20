import pexpect

HOST = "89.116.34.45"
USER = "root"
PASS = "Saklain@061524"

NGINX_CONF = r"""
server {
    listen 80;
    server_name _;

    # Backend API Proxy
    location /api/ {
        rewrite ^/api/(.*) /$1 break;
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # Frontend Proxy (Next.js)
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;

        # [FIX] KILL CACHE
        add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0" always;
        add_header Pragma "no-cache" always;
        add_header Expires "0" always;
    }
}
"""

def fix_nginx():
    print(f"🔄 Updating Nginx on {HOST}...")
    child = pexpect.spawn(f'ssh {USER}@{HOST}', encoding='utf-8', timeout=60)
    i = child.expect(['password:', 'continue connecting', pexpect.EOF, pexpect.TIMEOUT])
    if i == 1: 
        child.sendline('yes'); child.expect('password:')
    child.sendline(PASS)
    child.expect(['#', '$'])
    
    # Write config
    child.sendline("cat > /etc/nginx/sites-available/default << 'EOF_NGINX'")
    for line in NGINX_CONF.split('\n'):
        if line.strip():
            child.sendline(line)
    child.sendline("EOF_NGINX")
    child.expect(['#', '$'])
    
    # Reload
    print("🔄 Reloading Nginx...")
    child.sendline("nginx -t && systemctl reload nginx")
    child.expect(['#', '$'])
    print(child.before)
    print("✅ Nginx Updated!")

if __name__ == "__main__":
    try:
        fix_nginx()
    except Exception as e:
        print(f"❌ Error: {e}")
