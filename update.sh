#!/bin/bash

echo "=========================================="
echo "    ZohoMap Server Update Script"
echo "=========================================="

# Navigate to the project directory first
cd /var/www/zohomap || { echo "Error: /var/www/zohomap directory not found"; exit 1; }

# 1. Pull latest code from GitHub
echo "[1/4] Pulling latest changes from GitHub..."
# Allow root (sudo) to access the repo even if owned by a different user
sudo git config --global --add safe.directory /var/www/zohomap
sudo git pull origin main

# 2. Ensure virtual environment exists and is activated
echo "[2/4] Checking Python virtual environment..."
if [ ! -f "venv/bin/activate" ]; then
    echo "  venv not found — creating it now..."
    python3 -m venv venv
    echo "  venv created."
else
    echo "  venv found."
fi
source venv/bin/activate

# 2.5 Install OS Dependencies
echo "[2.5/4] Installing required system packages (may prompt for sudo password)..."
sudo apt-get update && sudo apt-get install -y libpq-dev python3-dev gcc

# 3. Install dependencies
echo "[3/4] Installing/updating requirements..."
pip install -r requirements.txt

# 3.5 Generate SSL cert if needed for HTTP
echo "[3.5/4] Checking for SSL certificates..."
if [ ! -f "cert.pem" ] || [ ! -f "key.pem" ]; then
    echo "Generating self-signed SSL certificate for HTTPS..."
    openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 3650 -subj "/CN=zohomap"
fi

# 3.8 Fix permissions
echo "Fixing permissions for www-data..."
sudo mkdir -p /var/www/zohomap/static/custom_markers
sudo chown -R www-data:www-data /var/www/zohomap
# Re-apply execute permissions on shell scripts so they can still be run with sudo
sudo chmod +x /var/www/zohomap/*.sh

# 4. Install service files from repo
echo "[4/4] Installing service files..."
sudo cp /var/www/zohomap/zohomap.service /etc/systemd/system/zohomap.service
sudo chmod 644 /etc/systemd/system/zohomap.service
echo "  ✅ zohomap.service installed"

# 4a. Install AWS secrets loader service (only activates on AWS — skipped gracefully on standalone)
sudo cp /var/www/zohomap/zohomap-secrets.service /etc/systemd/system/
sudo chmod +x /var/www/zohomap/load_aws_secrets.sh
sudo systemctl daemon-reload

# Detect whether this is an AWS instance using IMDSv2
IS_AWS=false
_IMDS_TOKEN=$(curl -sf -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 60" --max-time 2 2>/dev/null || true)
if [ -n "$_IMDS_TOKEN" ]; then
    IS_AWS=true
fi

if $IS_AWS; then
    echo "  🟦 AWS environment detected — loading secrets from Secrets Manager..."
    sudo systemctl enable zohomap-secrets.service
    if sudo /var/www/zohomap/load_aws_secrets.sh; then
        echo "  ✅ Secrets loaded into /etc/zohomap/app.env"
    else
        echo "  ❌ Failed to load secrets from AWS — check IAM role has secretsmanager:GetSecretValue on zohomap/production"
    fi
else
    echo "  🟩 Standalone environment detected."
    if [ -f "/etc/zohomap/app.env" ]; then
        echo "  ✅ /etc/zohomap/app.env found — secrets already configured"
    else
        echo "  ⚠️  /etc/zohomap/app.env is MISSING"
        echo "     Run: sudo ./setup_secrets.sh   (only needed once per server)"
    fi
fi

# 4.1 Restart the main app (now that secrets are loaded)
echo "Restarting ZohoMap service..."
sudo systemctl restart zohomap

# 4.2 Update Nginx configuration and reload
echo "Updating Nginx configuration and reloading..."
sudo cp /var/www/zohomap/zohomap.nginx.conf /etc/nginx/sites-available/zohomap
sudo ln -sf /etc/nginx/sites-available/zohomap /etc/nginx/sites-enabled/zohomap
sudo nginx -t && sudo systemctl reload nginx

# 4.5 Install / refresh nightly sync timer
echo "[4.5/4] Installing nightly sync timer (11pm EST daily)..."
sudo cp /var/www/zohomap/zohomap-sync.service /etc/systemd/system/
sudo cp /var/www/zohomap/zohomap-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable zohomap-sync.timer --now
echo "  ✅ Nightly sync timer active. Next run:"
systemctl list-timers zohomap-sync.timer --no-pager 2>/dev/null | tail -2 || true


echo "=========================================="
echo "    Update Complete!"
echo "=========================================="

# 5. Run connection diagnostics
echo ""
echo "=========================================="
echo "    Running Connection Diagnostics"
echo "=========================================="

# Read secrets from /etc/zohomap/app.env (works for both AWS and standalone)
get_env() {
    sudo grep -oP "(?<=${1}=).+" /etc/zohomap/app.env 2>/dev/null | head -1 || true
}

DB_URI=$(get_env "DATABASE_URI")
ZOHO_ID=$(get_env "ZOHO_CLIENT_ID")

# Test 1: App health endpoint (wait up to 10s for gunicorn to start)
echo "[DIAG 1/3] Testing app health endpoint..."
for i in 1 2 3 4 5; do
    sleep 2
    HTTP_STATUS=$(curl -sk -o /dev/null -w "%{http_code}" http://localhost/health 2>/dev/null \
                  || curl -sk -o /dev/null -w "%{http_code}" https://localhost/health 2>/dev/null \
                  || echo "000")
    [ "$HTTP_STATUS" != "000" ] && break
done
if [ "$HTTP_STATUS" = "200" ]; then
    echo "  ✅ App /health: OK (HTTP 200)"
elif [ "$HTTP_STATUS" = "503" ]; then
    echo "  ⚠️  App /health: running but DB connection failed (HTTP 503)"
    echo "     Check: sudo journalctl -u zohomap -n 30"
else
    echo "  ❌ App /health: UNREACHABLE (HTTP $HTTP_STATUS)"
    echo "     Check: sudo journalctl -u zohomap -n 30"
fi

# Test 2: Database connection
echo "[DIAG 2/3] Testing database connection..."
if $IS_AWS; then
    if [ -n "$DB_URI" ]; then
        DB_TEST=$(sudo /var/www/zohomap/venv/bin/python3 -c "
import sys
from urllib.parse import urlparse
try:
    import pg8000.dbapi, ssl
    p = urlparse('$DB_URI')
    ssl_ctx = None
    if 'sslmode' in (p.query or ''):
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
    conn = pg8000.dbapi.connect(user=p.username, password=p.password, host=p.hostname, port=p.port or 5432, database=p.path.lstrip('/'), ssl_context=ssl_ctx)
    conn.close()
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
" 2>&1)
        if [ "$DB_TEST" = "OK" ]; then
            echo "  ✅ PostgreSQL (RDS): Connected successfully"
        else
            echo "  ❌ PostgreSQL (RDS): $DB_TEST"
            echo "     Check: RDS Security Group allows port 5432 from this instance"
        fi
    else
        echo "  ❌ DATABASE_URI not found in /etc/zohomap/app.env"
    fi
else
    if [ -z "$DB_URI" ] || [ "$DB_URI" = "sqlite:///database.db" ]; then
        if [ -f "/var/www/zohomap/database.db" ]; then
            echo "  ✅ SQLite: database.db file found"
        else
            echo "  ⚠️  SQLite: database.db not found — will be created on first run"
        fi
    else
        DB_TEST=$(sudo /var/www/zohomap/venv/bin/python3 -c "
import pg8000.dbapi
from urllib.parse import urlparse
try:
    p = urlparse('$DB_URI')
    conn = pg8000.dbapi.connect(user=p.username, password=p.password, host=p.hostname, port=p.port or 5432, database=p.path.lstrip('/'))
    conn.close()
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
" 2>&1)
        if [ "$DB_TEST" = "OK" ]; then
            echo "  ✅ PostgreSQL: Connected successfully"
        else
            echo "  ❌ PostgreSQL: $DB_TEST"
        fi
    fi
fi

# Test 3: Zoho credentials
echo "[DIAG 3/3] Checking Zoho credentials..."
if [ -n "$ZOHO_ID" ]; then
    echo "  ✅ Zoho credentials: Present in /etc/zohomap/app.env"
else
    echo "  ❌ Zoho credentials: NOT found in /etc/zohomap/app.env"
    if $IS_AWS; then
        echo "     Check: AWS Secrets Manager has ZOHO_CLIENT_ID in zohomap/production"
    else
        echo "     Run: sudo ./setup_secrets.sh"
    fi
fi

echo ""
echo "=========================================="
echo "    Diagnostics Complete"
echo "=========================================="
