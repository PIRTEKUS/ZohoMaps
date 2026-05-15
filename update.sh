#!/bin/bash

echo "=========================================="
echo "    ZohoMap Server Update Script"
echo "=========================================="

# Navigate to the project directory first
cd /var/www/zohomap || { echo "Error: /var/www/zohomap directory not found"; exit 1; }

# 1. Pull latest code from GitHub
echo "[1/4] Pulling latest changes from GitHub (may prompt for sudo)..."
sudo git pull origin main

# 2. Activate virtual environment
echo "[2/4] Activating Python virtual environment..."
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "Warning: venv not found. Ensure you created it as per README."
fi

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
sudo chown -R www-data:www-data /var/www/zohomap
# Re-apply execute permissions on shell scripts so they can still be run with sudo
sudo chmod +x /var/www/zohomap/*.sh

# 4. Restart the service
echo "[4/4] Restarting ZohoMap service (may prompt for sudo password)..."
sudo systemctl restart zohomap

echo "=========================================="
echo "    Update Complete!"
echo "=========================================="

# 5. Run connection diagnostics
echo ""
echo "=========================================="
echo "    Running Connection Diagnostics"
echo "=========================================="

# Read secrets from the systemd service file
SERVICE_FILE="/etc/systemd/system/zohomap.service"

get_env() {
    sudo grep -oP "(?<=${1}=)[^\"]+" "$SERVICE_FILE" 2>/dev/null | head -1 || true
}

DB_URI=$(get_env "DATABASE_URI")
ZOHO_ID=$(get_env "ZOHO_CLIENT_ID")
ZOHO_SECRET=$(get_env "ZOHO_CLIENT_SECRET")

# Test 1: App health endpoint
echo "[DIAG 1/3] Testing app health endpoint..."
sleep 2  # Give the service a moment to fully start
HTTP_STATUS=$(curl -sk -o /dev/null -w "%{http_code}" https://localhost/health 2>/dev/null || echo "000")
if [ "$HTTP_STATUS" = "200" ]; then
    echo "  ✅ App /health: OK (HTTP 200)"
elif [ "$HTTP_STATUS" = "503" ]; then
    echo "  ⚠️  App /health: App running but DB connection FAILED (HTTP 503)"
else
    echo "  ❌ App /health: UNREACHABLE (HTTP $HTTP_STATUS) — check: sudo journalctl -u zohomap -n 30"
fi

# Test 2: Database connection
echo "[DIAG 2/3] Testing database connection..."
if [ -z "$DB_URI" ] || [ "$DB_URI" = "sqlite:///database.db" ]; then
    if [ -f "/var/www/zohomap/database.db" ]; then
        echo "  ✅ SQLite: database.db file found"
    else
        echo "  ⚠️  SQLite: database.db not found — will be created on first run"
    fi
else
    # Test PostgreSQL connection
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

# Test 3: Zoho API credentials (validate client ID format only — no live call)
echo "[DIAG 3/3] Checking Zoho credentials..."
if [ -z "$ZOHO_ID" ] || [ "$ZOHO_ID" = "Zoho Client ID [NOT SET]:" ]; then
    echo "  ❌ Zoho credentials: NOT configured in service file"
    echo "     Run: sudo ./setup_secrets.sh"
else
    echo "  ✅ Zoho credentials: Present in service file"
fi

echo ""
echo "=========================================="
echo "    Diagnostics Complete"
echo "=========================================="
