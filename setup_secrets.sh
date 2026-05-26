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

# --- Helper: read current value from service file or config.ini ---
get_current() {
    local KEY="$1"
    local VAL
    VAL=$(sudo grep -oP "(?<=${KEY}=)[^\"]+" "$SERVICE_FILE" 2>/dev/null | head -1 || true)
    if [ -n "$VAL" ]; then
        echo "$VAL"
        return
    fi
    # Fallback to config.ini
    local CONFIG_FILE=""
    if [ -f "/var/www/zohomap/config.ini" ]; then
        CONFIG_FILE="/var/www/zohomap/config.ini"
    elif [ -f "config.ini" ]; then
        CONFIG_FILE="config.ini"
    fi
    if [ -n "$CONFIG_FILE" ]; then
        local CONFIG_KEY
        case "$KEY" in
            ZOHO_CLIENT_ID) CONFIG_KEY="client_id" ;;
            ZOHO_CLIENT_SECRET) CONFIG_KEY="client_secret" ;;
            ZOHO_REDIRECT_URI) CONFIG_KEY="redirect_uri" ;;
            GOOGLE_MAPS_API_KEY) CONFIG_KEY="maps_api_key" ;;
            APP_SECRET_KEY) CONFIG_KEY="secret_key" ;;
            DATABASE_URI) CONFIG_KEY="database_uri" ;;
            *) CONFIG_KEY="" ;;
        esac
        if [ -n "$CONFIG_KEY" ]; then
            VAL=$(grep -i "^[[:space:]]*${CONFIG_KEY}[[:space:]]*=" "$CONFIG_FILE" 2>/dev/null | head -n1 | cut -d'=' -f2- | xargs || true)
            if [ -n "$VAL" ]; then
                echo "$VAL"
                return
            fi
        fi
    fi
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
ZOHO_REDIRECT_URI=$(ask "ZOHO_REDIRECT_URI"     "Zoho Redirect URI(s) (comma-separated, e.g. https://yourdomain.com/callback):")
echo ""
ZOHO_REFRESH_TOKEN=$(ask "ZOHO_REFRESH_TOKEN"   "Zoho Permanent Refresh Token (from /admin/refresh-token-setup — leave blank to skip):")
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
Environment="ZOHO_REDIRECT_URI=${ZOHO_REDIRECT_URI}"
$([ -n "${ZOHO_REFRESH_TOKEN}" ] && echo "Environment=\"ZOHO_REFRESH_TOKEN=${ZOHO_REFRESH_TOKEN}\"")
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

# ── Write a www-data-readable env file for the nightly sync service ──────────
# The sync service runs as www-data and cannot read the root-only service file.
# This env file contains the same vars so the sync job can start correctly.
ENV_FILE="/etc/zohomap/app.env"
echo ""
echo "Writing env file for nightly sync to $ENV_FILE ..."
sudo mkdir -p /etc/zohomap
cat <<ENVEOF | sudo tee "$ENV_FILE" > /dev/null
PATH=/var/www/zohomap/venv/bin
FLASK_ENV=production
ZOHO_CLIENT_ID=${ZOHO_CLIENT_ID}
ZOHO_CLIENT_SECRET=${ZOHO_CLIENT_SECRET}
ZOHO_REDIRECT_URI=${ZOHO_REDIRECT_URI}
$([ -n "${ZOHO_REFRESH_TOKEN}" ] && echo "ZOHO_REFRESH_TOKEN=${ZOHO_REFRESH_TOKEN}")
GOOGLE_MAPS_API_KEY=${GOOGLE_MAPS_API_KEY}
APP_SECRET_KEY=${SECRET_KEY}
DATABASE_URI=${DATABASE_URI}
TOKEN_ENCRYPTION_KEY=${FERNET_KEY}
ENVEOF
sudo chown root:www-data "$ENV_FILE"
sudo chmod 640 "$ENV_FILE"
echo "  ✅  $ENV_FILE written (readable by www-data)"

# ── Update the sync service to load env from the env file ───────────────────
SYNC_SERVICE="/etc/systemd/system/zohomap-sync.service"
cat <<SYNCEOF | sudo tee "$SYNC_SERVICE" > /dev/null
[Unit]
Description=ZohoMap Nightly Data Sync Job
After=network.target zohomap.service

[Service]
Type=oneshot
User=www-data
Group=www-data
WorkingDirectory=/var/www/zohomap
EnvironmentFile=/etc/zohomap/app.env
ExecStart=/var/www/zohomap/venv/bin/python3 /var/www/zohomap/run_nightly_sync.py
StandardOutput=append:/var/www/zohomap/debug.log
StandardError=append:/var/www/zohomap/debug.log
SYNCEOF
sudo chmod 644 "$SYNC_SERVICE"
echo "  ✅  $SYNC_SERVICE updated with EnvironmentFile"

sudo systemctl daemon-reload
sudo systemctl restart zohomap

echo ""
echo "=============================================="
echo "    Done! Verifying service is running..."
echo "=============================================="
sleep 3
sudo systemctl is-active zohomap && echo "Service: RUNNING" || echo "Service: FAILED — run: sudo journalctl -u zohomap -n 20"
echo ""
echo "NEXT STEP: You can safely delete /var/www/zohomap/config.ini entirely since all"
echo "configurations are now securely stored as environment variables!"
echo ""
