#!/bin/bash

echo "=========================================="
echo "    ZohoMap Server Hardening Script"
echo "=========================================="

cd /var/www/zohomap || { echo "Error: /var/www/zohomap directory not found"; exit 1; }

# Task 1: Fix config.ini file permissions
echo "[1/5] Fixing config.ini file permissions..."
sudo chmod 600 /var/www/zohomap/config.ini
sudo chown www-data:www-data /var/www/zohomap/config.ini

# Task 2: Git secret exposure
echo "[2/5] Ensuring config.ini is safely ignored..."
grep -q "config.ini" .gitignore || echo "config.ini" >> .gitignore

# Task 3: Harden self-signed SSL cert
echo "[3/5] Hardening SSL Certificates..."
if [ -f "cert.pem" ]; then sudo cp cert.pem cert.pem.bak; fi
if [ -f "key.pem" ]; then sudo cp key.pem key.pem.bak; fi

sudo openssl req -x509 -nodes -days 3650 \
  -newkey rsa:2048 \
  -keyout /var/www/zohomap/key.pem \
  -out /var/www/zohomap/cert.pem \
  -subj "/CN=zohomaps.pirtekusa.com/O=Pirtek USA/C=US" \
  -addext "subjectAltName=DNS:zohomaps.pirtekusa.com,IP:10.1.3.187"

sudo chown www-data:www-data /var/www/zohomap/cert.pem /var/www/zohomap/key.pem
sudo chmod 644 /var/www/zohomap/cert.pem
sudo chmod 600 /var/www/zohomap/key.pem

echo "Copying updated Nginx configuration and reloading..."
sudo cp /var/www/zohomap/zohomap.nginx.conf /etc/nginx/sites-available/zohomap
sudo nginx -t && sudo systemctl reload nginx

# Task 4: Fix Gunicorn socket permission error
echo "[4/5] Fixing Gunicorn socket permissions..."
sudo mkdir -p /var/www/.gunicorn
sudo chown www-data:www-data /var/www/.gunicorn
sudo chmod 750 /var/www/.gunicorn

# Task 5: Generate TOKEN_ENCRYPTION_KEY and switch to gevent workers
echo "[5/5] Generating token encryption key and switching to gevent workers..."

# Generate a valid Fernet key using Python
FERNET_KEY=$(sudo /var/www/zohomap/venv/bin/python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

if [ -z "$FERNET_KEY" ]; then
    echo "ERROR: Failed to generate Fernet key. Aborting."
    exit 1
fi

echo "Generated Fernet key successfully."

# Write the full service file with all environment variables and gevent workers
cat <<EOF | sudo tee /etc/systemd/system/zohomap.service > /dev/null
[Unit]
Description=Gunicorn instance to serve ZohoMap
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/zohomap
Environment="PATH=/var/www/zohomap/venv/bin"
Environment="FLASK_ENV=production"
Environment="TOKEN_ENCRYPTION_KEY=${FERNET_KEY}"
ExecStart=/var/www/zohomap/venv/bin/gunicorn --workers 4 --worker-class gevent --worker-connections 100 --timeout 120 --bind unix:zohomap.sock -m 007 app:app

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl restart zohomap.service

echo "Waiting 4 seconds for service to stabilize..."
sleep 4

echo "=========================================="
echo "    Final Health Check"
echo "=========================================="
echo "===== CONFIG.INI PERMISSIONS =====" && \
ls -la /var/www/zohomap/config.ini && \
echo "===== KEY/CERT PERMISSIONS =====" && \
ls -la /var/www/zohomap/key.pem /var/www/zohomap/cert.pem && \
echo "===== CERT SAN CHECK =====" && \
openssl x509 -in /var/www/zohomap/cert.pem -noout -ext subjectAltName && \
echo "===== GITIGNORE =====" && \
grep "config.ini" /var/www/zohomap/.gitignore && \
echo "===== SERVICE STATUS =====" && \
sudo systemctl is-active zohomap.service && \
echo "===== GUNICORN WORKERS =====" && \
ps aux | grep gunicorn | grep -v grep && \
echo "===== NGINX HEADERS =====" && \
curl -skI https://localhost/ | grep -iE "strict-transport|x-frame|x-content" && \
echo "===== HTTPS RESPONSE =====" && \
curl -sk https://localhost/ -o /dev/null -w "Status: %{http_code}\n"
