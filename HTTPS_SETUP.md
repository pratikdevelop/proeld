# ProELD — HTTPS + Production Setup Guide

## Step 1: Get a domain
Buy a domain (e.g. `proeld.yourdomain.com`) from Namecheap, Cloudflare, etc.
Point its A record to your server's IP address.

## Step 2: Install Nginx + Certbot (Ubuntu/Debian)
```bash
sudo apt update
sudo apt install nginx certbot python3-certbot-nginx -y
```

## Step 3: Nginx config
Create `/etc/nginx/sites-available/proeld`:
```nginx
server {
    listen 80;
    server_name proeld.yourdomain.com;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    # WebSocket support
    location /ws/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host $host;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/proeld /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## Step 4: Get free TLS certificate
```bash
sudo certbot --nginx -d proeld.yourdomain.com
# Follow prompts — auto-renews via cron
```

Certbot will rewrite your nginx config to add HTTPS and redirect HTTP → HTTPS automatically.

## Step 5: Generate a strong JWT secret
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## Step 6: Production .env
```env
APP_ENV=production
APP_VERSION=3.2.0

MONGO_URI=mongodb+srv://USERNAME:PASSWORD@cluster0.xxxxx.mongodb.net/proeld?retryWrites=true&w=majority
MONGO_DB=proeld

JWT_SECRET=<output from step 5 — 64 hex chars>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
REFRESH_TOKEN_EXPIRE_DAYS=7

ALLOWED_ORIGINS=https://proeld.yourdomain.com

LOG_LEVEL=INFO
LOG_JSON=true
```

## Step 7: Run with Gunicorn (not uvicorn dev server)
```bash
pip install gunicorn
gunicorn main:app \
  --workers 2 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 127.0.0.1:8000 \
  --timeout 120 \
  --access-logfile /var/log/proeld/access.log \
  --error-logfile /var/log/proeld/error.log
```

## Step 8: systemd service (auto-restart on crashes)
Create `/etc/systemd/system/proeld.service`:
```ini
[Unit]
Description=ProELD ELD API
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/proeld
EnvironmentFile=/var/www/proeld/.env
ExecStart=/usr/local/bin/gunicorn main:app \
    --workers 2 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 127.0.0.1:8000 \
    --timeout 120
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable proeld
sudo systemctl start proeld
sudo systemctl status proeld
```

## Step 9: Verify security headers
```bash
curl -I https://proeld.yourdomain.com/health
# Should show: Strict-Transport-Security, Content-Security-Policy, X-Frame-Options
```

Or use: https://securityheaders.com (paste your URL)

## Step 10: MongoDB Atlas security
- Network Access → restrict to your server IP (not 0.0.0.0/0)
- Database Access → use a dedicated user with readWrite on proeld db only
- Enable Atlas backup → Continuous Cloud Backup
