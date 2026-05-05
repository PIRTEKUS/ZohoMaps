#!/bin/bash

echo "=========================================="
echo "    ZohoMap Server Update Script"
echo "=========================================="

# Navigate to the project directory first
cd /var/www/zohomap || { echo "Error: /var/www/zohomap directory not found"; exit 1; }

# 1. Pull latest code from GitHub
echo "[1/4] Pulling latest changes from GitHub..."
git pull origin main

# 2. Activate virtual environment
echo "[2/4] Activating Python virtual environment..."
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "Warning: venv not found. Ensure you created it as per README."
fi

# 3. Install dependencies
echo "[3/4] Installing/updating requirements..."
pip install -r requirements.txt

# 3.5 Fix permissions
echo "Fixing permissions for www-data..."
sudo chown -R www-data:www-data /var/www/zohomap

# 4. Restart the service
echo "[4/4] Restarting ZohoMap service (may prompt for sudo password)..."
sudo systemctl restart zohomap

echo "=========================================="
echo "    Update Complete!"
echo "=========================================="
