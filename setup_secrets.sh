#!/bin/bash
# =============================================================================
# ZohoMap Secrets Setup Script
# Injects all sensitive credentials into the systemd service file as
# environment variables. The service file is only readable by root.
#
# Run: sudo ./setup_secrets.sh
# =============================================================================

set -e

SERVICE_FILE="/etc/systemd/system/zohomap.service"

echo "=============================================="
echo "    ZohoMap Secrets Configuration"
echo "=============================================="
echo ""
echo "You will be prompted for each secret. Press Enter to keep the current value."
echo ""

# --- Helper: read current value from service file ---
get_current() {
    local KEY="$1"
    sudo grep -oP "(?<=${KEY}=)[^\"]+" "$SERVICE_FILE" 2>/dev/null | head -1 || true
}

# --- Interactive prompt (reads directly from /dev/tty to avoid pipe issues) ---
ask() {
    local KEY="$1"
    local LABEL="$2"
    local CURRENT
    CURRENT=$(get_current "$KEY")

    if [ -n "$CURRENT" ]; then
        echo "$LABEL" >&2
        echo -n "  [Current: ***SET*** - press Enter to keep, or type new value]: " >&2
    else
        echo "$LABEL" >&2
        echo -n "  [NOT SET - enter value]: " >&2
    fi

    local INPUT
    read -r INPUT < /dev/tty
    if [ -n "$INPUT" ]; then
        printf '%s' "$INPUT"
    else
        printf '%s' "$CURRENT"
    fi
}

ZOHO_CLIENT_ID=$(ask "ZOHO_CLIENT_ID"       "Zoho Client ID:")
echo ""
ZOHO_CLIENT_SECRET=$(ask "ZOHO_CLIENT_SECRET"   "Zoho Client Secret:")
echo ""
GOOGLE_MAPS_API_KEY=$(ask "GOOGLE_MAPS_API_KEY"  "Google Maps API Key:")
echo ""
SECRET_KEY=$(ask "APP_SECRET_KEY"          "Flask Secret Key (run: python3 -c \"import secrets; print(secrets.token_hex(32))\"):")
echo ""
DATABASE_URI=$(ask "DATABASE_URI"           "Database URI (e.g. postgresql://zohouser:pass@localhost/zohomap):")
echo ""

# Keep the existing Fernet key if one exists, otherwise generate a new one
FERNET_KEY=$(get_current "TOKEN_ENCRYPTION_KEY")
if [ -z "$FERNET_KEY" ]; then
    echo "Generating new Fernet encryption key..."
    FERNET_KEY=$(sudo /var/www/zohomap/venv/bin/python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    echo "Fernet key generated."
else
    echo "Existing Fernet key found. Keeping it unchanged."
fi

echo ""
echo "Writing secrets to $SERVICE_FILE ..."

cat <<EOF | sudo tee "$SERVICE_FILE" > /dev/null
[Unit]
Description=Gunicorn instance to serve ZohoMap
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/zohomap
Environment="PATH=/var/www/zohomap/venv/bin"
Environment="FLASK_ENV=production"
Environment="ZOHO_CLIENT_ID=${ZOHO_CLIENT_ID}"
Environment="ZOHO_CLIENT_SECRET=${ZOHO_CLIENT_SECRET}"
Environment="GOOGLE_MAPS_API_KEY=${GOOGLE_MAPS_API_KEY}"
Environment="APP_SECRET_KEY=${SECRET_KEY}"
Environment="DATABASE_URI=${DATABASE_URI}"
Environment="TOKEN_ENCRYPTION_KEY=${FERNET_KEY}"
ExecStart=/var/www/zohomap/venv/bin/gunicorn --workers 4 --worker-class gthread --threads 8 --timeout 120 --bind unix:zohomap.sock -m 007 app:app

[Install]
WantedBy=multi-user.target
EOF

sudo chmod 600 "$SERVICE_FILE"
sudo chown root:root "$SERVICE_FILE"
sudo systemctl daemon-reload
sudo systemctl restart zohomap

echo ""
echo "=============================================="
echo "    Done! Verifying service is running..."
echo "=============================================="
sleep 3
sudo systemctl is-active zohomap && echo "Service: RUNNING" || echo "Service: FAILED — run: sudo journalctl -u zohomap -n 20"
echo ""
echo "NEXT STEP: Remove secrets from /var/www/zohomap/config.ini"
echo "Only keep: redirect_uri, accounts_url, api_url"
