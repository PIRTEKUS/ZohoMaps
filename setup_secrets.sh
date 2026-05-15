#!/bin/bash
# =============================================================================
# ZohoMap Secrets Setup Script
# Injects all sensitive credentials into the systemd service file as
# environment variables. The service file is only readable by root,
# making this far more secure than storing secrets in config.ini.
#
# Run this script ONCE after initial setup, or whenever a secret needs rotating.
# After running, remove the sensitive values from config.ini.
# =============================================================================

set -e  # Exit immediately on any error

echo "=============================================="
echo "    ZohoMap Secrets Configuration"
echo "=============================================="
echo ""
echo "This script will securely store your API credentials"
echo "as environment variables in the systemd service file."
echo "You will be prompted for each value."
echo "Leave a prompt BLANK and press Enter to keep the existing value."
echo ""

SERVICE_FILE="/etc/systemd/system/zohomap.service"

# --- Helper: read current value from service file ---
get_current() {
    grep -oP "(?<=${1}=)[^\"]+" "$SERVICE_FILE" 2>/dev/null || echo ""
}

# --- Helper: prompt user for a value ---
prompt_secret() {
    local VAR_NAME="$1"
    local PROMPT_TEXT="$2"
    local CURRENT
    CURRENT=$(get_current "$VAR_NAME")

    if [ -n "$CURRENT" ]; then
        echo -n "$PROMPT_TEXT [current: ***ALREADY SET*** - press Enter to keep]: "
    else
        echo -n "$PROMPT_TEXT [NOT SET]: "
    fi

    read -r INPUT
    if [ -n "$INPUT" ]; then
        echo "$INPUT"
    else
        echo "$CURRENT"
    fi
}

# Prompt for each secret
ZOHO_CLIENT_ID=$(prompt_secret "ZOHO_CLIENT_ID" "Zoho Client ID")
ZOHO_CLIENT_SECRET=$(prompt_secret "ZOHO_CLIENT_SECRET" "Zoho Client Secret")
GOOGLE_MAPS_API_KEY=$(prompt_secret "GOOGLE_MAPS_API_KEY" "Google Maps API Key")
SECRET_KEY=$(prompt_secret "APP_SECRET_KEY" "Flask Secret Key (generate with: python3 -c \"import secrets; print(secrets.token_hex(32))\")")
DATABASE_URI=$(prompt_secret "DATABASE_URI" "Database URI (e.g. postgresql://zohouser:pass@localhost/zohomap)")

# Generate a Fernet key if one doesn't already exist
FERNET_KEY=$(get_current "TOKEN_ENCRYPTION_KEY")
if [ -z "$FERNET_KEY" ]; then
    echo "Generating new Fernet encryption key..."
    FERNET_KEY=$(sudo /var/www/zohomap/venv/bin/python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    echo "Fernet key generated."
else
    echo "Fernet encryption key already exists. Keeping existing key."
fi

echo ""
echo "Writing secrets to systemd service file..."

# Write the complete, updated service file
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

# Protect the service file
sudo chmod 600 "$SERVICE_FILE"
sudo chown root:root "$SERVICE_FILE"

sudo systemctl daemon-reload
sudo systemctl restart zohomap

echo ""
echo "=============================================="
echo "    Secrets stored and service restarted!"
echo "=============================================="
echo ""
echo "NEXT STEP: Remove secrets from config.ini!"
echo "Edit /var/www/zohomap/config.ini and remove or blank out:"
echo "  - client_id"
echo "  - client_secret"
echo "  - maps_api_key"
echo "  - secret_key"
echo "  - database_uri (if it contains a password)"
echo ""
echo "Leave non-secret settings in config.ini:"
echo "  - redirect_uri"
echo "  - accounts_url"
echo "  - api_url"
