#!/bin/bash
# =============================================================================
# ZohoMap Secrets Setup Script  (Standalone Server Edition)
# Writes all sensitive credentials to /etc/zohomap/app.env and installs
# the repo's zohomap.service which reads from that file.
#
# Use this on standalone Ubuntu servers.
# AWS multi-instance deployments use load_aws_secrets.sh instead.
#
# Run: sudo ./setup_secrets.sh
# =============================================================================

set -e

ENV_FILE="/etc/zohomap/app.env"

echo "=============================================="
echo "    ZohoMap Secrets Configuration"
echo "    (Standalone server setup)"
echo "=============================================="
echo ""
echo "You will be prompted for each secret. Press Enter to keep the current value."
echo ""

# --- Helper: read current value from app.env or config.ini ---
get_current() {
    local KEY="$1"
    local VAL

    # First try the env file (source of truth after first run)
    if [ -f "$ENV_FILE" ]; then
        VAL=$(sudo grep -oP "(?<=${KEY}=).+" "$ENV_FILE" 2>/dev/null | head -1 || true)
        if [ -n "$VAL" ]; then echo "$VAL"; return; fi
    fi

    # Fallback: old-style service file with inline Environment= lines
    local SERVICE_FILE="/etc/systemd/system/zohomap.service"
    VAL=$(sudo grep -oP "(?<=${KEY}=)[^\"]+\" "$SERVICE_FILE" 2>/dev/null | head -1 || true)
    if [ -n "$VAL" ]; then echo "$VAL"; return; fi

    # Fallback: config.ini
    local CONFIG_FILE=""
    if [ -f "/var/www/zohomap/config.ini" ]; then CONFIG_FILE="/var/www/zohomap/config.ini"
    elif [ -f "config.ini" ]; then CONFIG_FILE="config.ini"; fi
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
            if [ -n "$VAL" ]; then echo "$VAL"; return; fi
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
ZOHO_REFRESH_TOKEN=$(ask "ZOHO_REFRESH_TOKEN"   "Zoho Permanent Refresh Token (leave blank to skip):")
echo ""
GOOGLE_MAPS_API_KEY=$(ask "GOOGLE_MAPS_API_KEY"  "Google Maps API Key:")
echo ""
SECRET_KEY=$(ask "APP_SECRET_KEY"          "Flask Secret Key (run: python3 -c \"import secrets; print(secrets.token_hex(32))\"):")
echo ""
DATABASE_URI=$(ask "DATABASE_URI"           "Database URI (e.g. postgresql://zohouser:pass@localhost/zohomap or sqlite:///database.db):")
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

# ── Write /etc/zohomap/app.env ───────────────────────────────────────────────
# This is the single source of truth for secrets on standalone servers.
# Both zohomap.service and zohomap-sync.service load from this file.
echo ""
echo "Writing secrets to $ENV_FILE ..."
sudo mkdir -p /etc/zohomap
sudo tee "$ENV_FILE" > /dev/null <<ENVEOF
# ZohoMap environment secrets — managed by setup_secrets.sh
# DO NOT COMMIT this file. It is readable by root and www-data only.
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

# ── Install service files from the repo ─────────────────────────────────────
# zohomap.service reads from EnvironmentFile=-/etc/zohomap/app.env
# zohomap-sync.service reads from EnvironmentFile=/etc/zohomap/app.env
echo ""
echo "Installing service files from repo..."
sudo cp /var/www/zohomap/zohomap.service /etc/systemd/system/zohomap.service
sudo chmod 644 /etc/systemd/system/zohomap.service
echo "  ✅  zohomap.service installed"

sudo cp /var/www/zohomap/zohomap-sync.service /etc/systemd/system/zohomap-sync.service
sudo chmod 644 /etc/systemd/system/zohomap-sync.service
echo "  ✅  zohomap-sync.service installed"

sudo systemctl daemon-reload
sudo systemctl restart zohomap

echo ""
echo "=============================================="
echo "    Done! Verifying service is running..."
echo "=============================================="
sleep 3
sudo systemctl is-active zohomap && echo "Service: RUNNING ✅" || echo "Service: FAILED ❌ — run: sudo journalctl -u zohomap -n 20"
echo ""
echo "NEXT STEP: You can safely delete /var/www/zohomap/config.ini — all"
echo "secrets are now stored securely in $ENV_FILE"
echo ""
