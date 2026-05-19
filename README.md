# ZohoMap

ZohoMap is a Python/Flask web application that integrates with Zoho CRM and Google Maps. It provides a dynamic, secure portal where users authenticate via Zoho OAuth 2.0, and the server maps CRM records (Accounts, Leads, Ship To Addresses) filtered by their assigned **franchise memberships** — ensuring each user only sees data they are authorised to view.

## Features

- **Franchise-Based Data Privacy**: Records are filtered server-side by the user's assigned franchise(es), using Zoho's COQL API to resolve multiuserlookup field memberships.
- **Centralised Admin Sync**: All CRM data fetches use a server-side admin token stored in config — no per-user API profile permissions required.
- **Zoho OAuth 2.0 Integration**: Users log in with their Zoho account; the app resolves their numeric CRM ID and pre-caches franchise memberships at login.
- **Dynamic Module Settings**: Admin UI to configure which Zoho modules to display, which fields to show, and how to geocode records.
- **Smart Geocoding**: Converts addresses to coordinates via Google Maps Geocoding API; results are cached in the database to minimise API costs.
- **Customisable Map Markers**: Select per-module colours to distinguish record types on the map.
- **Admin Diagnostic Tools**: Built-in CRM Explorer (`/admin/crm-explorer`) and franchise lookup tester for troubleshooting.
- **Premium UI**: Glassmorphism design with micro-animations.
- **Production-Ready**: PostgreSQL backend, Gunicorn with gthread workers, Nginx reverse proxy, full systemd service management.

---

## Table of Contents

1. [Zoho API Setup](#1-zoho-api-setup)
2. [Standalone Ubuntu Deployment](#2-standalone-ubuntu-deployment-developmentstaging)
3. [Production AWS Deployment](#3-production-aws-deployment)
4. [Security Hardening — Franchise Filtering](#4-security-hardening--franchise-filtering)
5. [Admin Token Setup (ZOHO_REFRESH_TOKEN)](#5-admin-token-setup--zoho_refresh_token)
6. [Ongoing Operations](#6-ongoing-operations)

---

## 1. Zoho API Setup

These steps are required for **both** deployment methods.

### 1.1 Create a Server-Based Application

1. Go to the [Zoho API Console](https://api-console.zoho.com/).
2. Click **+ Add Client** → **Server-based Applications**.
3. Set the **Redirect URI** to your server's callback URL:
   - Standalone: `https://your-ubuntu-ip-or-domain.com/callback`
   - AWS: `https://your-alb-domain.com/callback`
4. Note the **Client ID** and **Client Secret** — these go in `ZOHO_CLIENT_ID` / `ZOHO_CLIENT_SECRET`.

### 1.2 Required OAuth Scopes

When logging in for the first time, the following scopes are requested automatically:

```
ZohoCRM.modules.ALL
ZohoCRM.settings.ALL
ZohoCRM.users.READ
ZohoCRM.coql.READ
```

### 1.3 Disable API Access for Non-Admin Profiles (Security)

To prevent team users from creating their own API clients and bypassing franchise filtering:

1. In Zoho CRM → **Settings → Users and Control → Profiles**.
2. For every non-administrator profile, edit it and **disable "Access to API"**.
3. The ZohoMap server uses its own admin token for all data fetches — team users do not need API access.

---

## 2. Standalone Ubuntu Deployment (Development/Staging)

Use this method for a single Ubuntu VM running all components locally (Nginx + Gunicorn + Flask + PostgreSQL on one machine). This mirrors the current HyperV server setup.

### 2.1 Prerequisites

```bash
sudo apt update
sudo apt install python3-pip python3-venv python3-dev libpq-dev gcc nginx git \
                 postgresql postgresql-contrib -y
```

### 2.2 Clone the Repository

```bash
sudo mkdir -p /var/www/zohomap
sudo chown $USER:$USER /var/www/zohomap
git clone https://github.com/PIRTEKUS/ZohoMaps.git /var/www/zohomap
cd /var/www/zohomap
```

### 2.3 Python Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2.4 PostgreSQL Database

Run the provided setup script to create the local database:

```bash
chmod +x setup_local_postgres.sh
./setup_local_postgres.sh
```

This creates database `zohomap` with user `zohouser` / password `zohopassword123!`. Edit the script before running if you prefer different credentials.

### 2.5 Configure Secrets via Systemd (Recommended)

All secrets are stored **only** in the systemd service file (readable by root only — never in `config.ini` or environment files that could be git-committed):

```bash
sudo chmod +x setup_secrets.sh
sudo ./setup_secrets.sh
```

The script interactively prompts for each secret and writes them to `/etc/systemd/system/zohomap.service`. You will need:

| Secret | Description |
|---|---|
| `ZOHO_CLIENT_ID` | From Zoho API Console |
| `ZOHO_CLIENT_SECRET` | From Zoho API Console |
| `ZOHO_REFRESH_TOKEN` | Permanent server-side token — see [Section 5](#5-admin-token-setup--zoho_refresh_token) |
| `GOOGLE_MAPS_API_KEY` | Google Maps API key (Maps JS + Geocoding APIs enabled) |
| `APP_SECRET_KEY` | Random string: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URI` | `postgresql://zohouser:zohopassword123!@localhost/zohomap` |
| `TOKEN_ENCRYPTION_KEY` | Auto-generated Fernet key (auto-created by `setup_secrets.sh`) |

The resulting service file looks like:

```ini
[Unit]
Description=Gunicorn instance to serve ZohoMap
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/zohomap
Environment="PATH=/var/www/zohomap/venv/bin"
Environment="FLASK_ENV=production"
Environment="ZOHO_CLIENT_ID=1000.xxxx"
Environment="ZOHO_CLIENT_SECRET=xxxx"
Environment="ZOHO_REFRESH_TOKEN=1000.xxxx"
Environment="GOOGLE_MAPS_API_KEY=AIza..."
Environment="APP_SECRET_KEY=xxxx"
Environment="DATABASE_URI=postgresql://zohouser:pass@localhost/zohomap"
Environment="TOKEN_ENCRYPTION_KEY=xxxx="
ExecStart=/var/www/zohomap/venv/bin/gunicorn \
    --workers 4 --worker-class gthread --threads 8 \
    --timeout 120 --bind unix:zohomap.sock -m 007 app:app

[Install]
WantedBy=multi-user.target
```

### 2.6 SSL Certificate (Self-Signed for Development)

```bash
openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem \
    -days 3650 -subj "/CN=yourdomain.com"
sudo chown www-data:www-data cert.pem key.pem
```

### 2.7 Nginx Configuration

```bash
sudo cp zohomap.nginx.conf /etc/nginx/sites-available/zohomap
# Edit the server_name to match your IP or domain:
sudo nano /etc/nginx/sites-available/zohomap
sudo ln -s /etc/nginx/sites-available/zohomap /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 2.8 Start the Service

```bash
sudo chown -R www-data:www-data /var/www/zohomap
sudo chmod +x *.sh
sudo systemctl daemon-reload
sudo systemctl enable zohomap
sudo systemctl start zohomap
```

### 2.9 Verify

```bash
sudo systemctl status zohomap
curl -sk https://localhost/health
```

### 2.10 Updating the Application

```bash
sudo ./update.sh
```

This script pulls the latest code from GitHub, installs/updates dependencies, fixes permissions, and restarts the service.

> [!IMPORTANT]
> **Switching from IP to Domain Name:** Update three locations: (1) `server_name` in `/etc/nginx/sites-available/zohomap`, (2) `redirect_uri` in `config.ini`, and (3) the authorised redirect URI in the Zoho API Console.

---

## 3. Production AWS Deployment

### 3.1 Architecture Overview

```
PIRTEK USA USERS  (1,200+/day → 3,600+/day)
         │ HTTPS port 443  (ACM trusted cert)
         ▼
  [ Route 53 DNS ]  →  [ Application Load Balancer + ACM SSL ]
         │  AZ-a                              │  AZ-b
         ▼                                   ▼
[ EC2 t3.small                      [ EC2 t3.small
  Nginx + Gunicorn + Flask ]          Nginx + Gunicorn + Flask ]
  (Private Subnet AZ-a)               (Private Subnet AZ-b)
         │                                   │
         └──────────────┬────────────────────┘
                        ▼
     [ Amazon RDS PostgreSQL — Multi-AZ ]
       Primary AZ-a  /  Standby AZ-b
       Auto backups │ 7-day retention │ Encrypted at rest

[ Zoho CRM API ]  [ AWS Secrets Manager ]  [ S3 Backups ]  [ CloudWatch ]
```

### 3.2 AWS Services Used

| Service | Purpose |
|---|---|
| **EC2 t3.small** (×2) | Flask + Gunicorn + Nginx in private subnets |
| **Application Load Balancer** | HTTPS termination, health checks, distributes traffic across AZs |
| **ACM (AWS Certificate Manager)** | Free, auto-renewing TLS certificate — replaces self-signed cert |
| **Route 53** | DNS — points your domain to the ALB |
| **RDS PostgreSQL Multi-AZ** | Managed database with automatic failover, backups, encryption at rest |
| **AWS Secrets Manager** | Stores all secrets (Zoho tokens, DB credentials, API keys) |
| **S3** | Static assets and database backups |
| **CloudWatch** | Logs and alarms for EC2, ALB, and RDS metrics |

### 3.3 Step-by-Step AWS Setup

#### 3.3.1 VPC and Networking

1. Create a VPC with CIDR `10.0.0.0/16`.
2. Create **2 private subnets** (one per AZ, e.g., `10.0.1.0/24` AZ-a, `10.0.2.0/24` AZ-b) for EC2 and RDS.
3. Create **2 public subnets** for the ALB NAT Gateway.
4. Create a **NAT Gateway** in a public subnet so the private EC2s can reach the internet (Zoho API, GitHub for deploys).
5. Create an **Internet Gateway** and update the public subnet route table.

#### 3.3.2 RDS PostgreSQL Multi-AZ

```bash
# Via AWS Console or CLI:
aws rds create-db-instance \
  --db-instance-identifier zohomap-prod \
  --db-instance-class db.t3.small \
  --engine postgres \
  --master-username zohouser \
  --master-user-password 'YOUR_SECURE_PASSWORD' \
  --db-name zohomap \
  --multi-az \
  --storage-encrypted \
  --backup-retention-period 7 \
  --allocated-storage 20
```

The `DATABASE_URI` becomes:
```
postgresql://zohouser:YOUR_SECURE_PASSWORD@zohomap-prod.xxxx.rds.amazonaws.com:5432/zohomap
```

#### 3.3.3 AWS Secrets Manager

Store all secrets as a single JSON secret:

```bash
aws secretsmanager create-secret \
  --name zohomap/prod \
  --secret-string '{
    "ZOHO_CLIENT_ID": "1000.xxx",
    "ZOHO_CLIENT_SECRET": "xxx",
    "ZOHO_REFRESH_TOKEN": "1000.xxx",
    "GOOGLE_MAPS_API_KEY": "AIza...",
    "APP_SECRET_KEY": "xxx",
    "DATABASE_URI": "postgresql://zohouser:pass@rds-endpoint/zohomap",
    "TOKEN_ENCRYPTION_KEY": "xxx="
  }'
```

#### 3.3.4 EC2 Instance Setup (run on each instance)

Launch two **EC2 t3.small** with Amazon Linux 2023 or Ubuntu 22.04 in the private subnets. Use an IAM Instance Role with `secretsmanager:GetSecretValue` permission.

```bash
# Install dependencies
sudo apt update
sudo apt install python3-pip python3-venv python3-dev libpq-dev gcc nginx git awscli -y

# Clone repo
sudo mkdir -p /var/www/zohomap
sudo git clone https://github.com/PIRTEKUS/ZohoMaps.git /var/www/zohomap
cd /var/www/zohomap
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Fetch secrets from AWS Secrets Manager and write to systemd service file
SECRET=$(aws secretsmanager get-secret-value \
  --secret-id zohomap/prod \
  --query SecretString --output text)

ZOHO_CLIENT_ID=$(echo $SECRET | python3 -c "import sys,json; print(json.load(sys.stdin)['ZOHO_CLIENT_ID'])")
ZOHO_CLIENT_SECRET=$(echo $SECRET | python3 -c "import sys,json; print(json.load(sys.stdin)['ZOHO_CLIENT_SECRET'])")
ZOHO_REFRESH_TOKEN=$(echo $SECRET | python3 -c "import sys,json; print(json.load(sys.stdin)['ZOHO_REFRESH_TOKEN'])")
GOOGLE_MAPS_API_KEY=$(echo $SECRET | python3 -c "import sys,json; print(json.load(sys.stdin)['GOOGLE_MAPS_API_KEY'])")
APP_SECRET_KEY=$(echo $SECRET | python3 -c "import sys,json; print(json.load(sys.stdin)['APP_SECRET_KEY'])")
DATABASE_URI=$(echo $SECRET | python3 -c "import sys,json; print(json.load(sys.stdin)['DATABASE_URI'])")
TOKEN_ENCRYPTION_KEY=$(echo $SECRET | python3 -c "import sys,json; print(json.load(sys.stdin)['TOKEN_ENCRYPTION_KEY'])")

sudo tee /etc/systemd/system/zohomap.service > /dev/null <<EOF
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
Environment="ZOHO_REFRESH_TOKEN=${ZOHO_REFRESH_TOKEN}"
Environment="GOOGLE_MAPS_API_KEY=${GOOGLE_MAPS_API_KEY}"
Environment="APP_SECRET_KEY=${APP_SECRET_KEY}"
Environment="DATABASE_URI=${DATABASE_URI}"
Environment="TOKEN_ENCRYPTION_KEY=${TOKEN_ENCRYPTION_KEY}"
ExecStart=/var/www/zohomap/venv/bin/gunicorn \
    --workers 4 --worker-class gthread --threads 8 \
    --timeout 120 --bind unix:zohomap.sock -m 007 app:app

[Install]
WantedBy=multi-user.target
EOF

sudo chmod 600 /etc/systemd/system/zohomap.service
sudo chown -R www-data:www-data /var/www/zohomap
sudo systemctl daemon-reload
sudo systemctl enable zohomap
sudo systemctl start zohomap
```

#### 3.3.5 Nginx on EC2 (ALB terminates SSL — Nginx is HTTP only internally)

Since the ALB handles HTTPS termination, Nginx on each EC2 only needs to handle HTTP on port 80 and forward to Gunicorn:

```nginx
# /etc/nginx/sites-available/zohomap
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://unix:/var/www/zohomap/zohomap.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/zohomap /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx
```

#### 3.3.6 Application Load Balancer

1. Create an **ALB** in the two public subnets.
2. **Target Group**: HTTP on port 80, health check path `/health`, healthy threshold 2.
3. Register both EC2 instances as targets.
4. **Listener**: HTTPS 443 → forward to target group.
5. **ACM Certificate**: Request a certificate for your domain in ACM, attach to the HTTPS listener.
6. **HTTP 80 listener**: Redirect to HTTPS.

#### 3.3.7 Route 53

1. Create a hosted zone for your domain.
2. Add an **A record** (Alias) pointing to the ALB DNS name.

#### 3.3.8 Update Zoho API Console

After DNS is live, update the **Authorised Redirect URI** in the Zoho API Console to:
```
https://yourdomain.com/callback
```

#### 3.3.9 Database Migration from Existing Server

If you have existing data on the standalone Ubuntu server, migrate it to RDS:

```bash
# On the existing server — export
python3 migrate_rds.py --export zohomap_export.json

# On the AWS EC2 — import
python3 migrate_rds.py --import zohomap_export.json \
  --target "postgresql://zohouser:pass@rds-endpoint/zohomap"
```

### 3.4 CloudWatch Monitoring

Set up alarms for:
- EC2 CPU > 80% for 5 minutes → SNS notification
- RDS FreeStorageSpace < 2GB → SNS notification
- ALB `UnHealthyHostCount` > 0 → SNS notification
- ALB `5XXCount` > 10 in 5 minutes → SNS notification

### 3.5 Auto Scaling (Optional Growth Path)

Replace the two fixed EC2 instances with an **Auto Scaling Group** using a Launch Template that runs the EC2 setup script above on first boot. Set:
- Min: 2 (one per AZ for HA)
- Max: 6
- Scale-out policy: CPU > 70% for 3 minutes

---

## 4. Security Hardening — Franchise Filtering

This is the core data privacy mechanism introduced in May 2025.

### 4.1 How It Works

When a non-admin user triggers a sync, the server:

1. Resolves the user's **numeric Zoho CRM ID** at login (requires admin token).
2. Queries the `Franchises` module via **COQL** to find all franchise records where the user appears in `Franchise_Standard_Users` or `Franchise_Admin_User`.
3. Builds a CRM search criteria: `(Franchise.id:in:id1,id2,...)` for each module.
4. Fetches **only** records matching that criteria — using the admin token (so user profile API restrictions don't block the fetch).

### 4.2 Franchise Field Mapping (Confirmed from CRM Explorer)

| Module | Franchise Lookup Field |
|---|---|
| `Accounts` | `Franchise` (lookup → Franchises) |
| `Leads` | `Select_Your_Franchise1` (lookup → Franchises) |
| `Ship_To_Addresses` | `Franchise` (lookup → Franchises) |

### 4.3 Graceful Degradation

| State | Behaviour |
|---|---|
| User has franchise assignments | Only matching records synced |
| User has no assignments | 0 records (sync returns empty) |
| Admin token unavailable, cache valid | Uses stale cache (up to 4h) |
| Admin token unavailable, no cache | Skips filter, syncs owned records |
| User ID is email (token expired at login) | Skips filter, warns in log |

### 4.4 Admin vs Team User Behaviour

| User type | `is_admin` | Franchise filter |
|---|---|---|
| Administrator | `True` | **Skipped** — sees all records |
| Standard User | `False` | **Applied** — franchise records only |

---

## 5. Admin Token Setup — `ZOHO_REFRESH_TOKEN`

The application uses a **permanent server-side refresh token** to fetch CRM data on behalf of team users. This eliminates the need for any administrator to ever log in to the app to maintain the server's CRM access.

### 5.1 How to Get the Token (One-Time Setup)

1. Log in to ZohoMap as an **Administrator** once (browser OAuth flow).
2. Navigate to **`https://yourdomain.com/admin/refresh-token-setup`**.
3. Copy the refresh token shown in **"Section 1: Your Current Session Refresh Token"**.

### 5.2 Store in Systemd (Standalone) or Secrets Manager (AWS)

**Standalone:**
```bash
sudo nano /etc/systemd/system/zohomap.service
# Add inside [Service] block:
Environment="ZOHO_REFRESH_TOKEN=1000.your_token_here"

sudo systemctl daemon-reload
sudo systemctl restart zohomap
```

**AWS:** Update the `zohomap/prod` secret in Secrets Manager, then re-run the EC2 setup or update systemd manually on each instance.

### 5.3 Token Lifetime

The refresh token from a Zoho **Server-based Application** does not expire unless:
- A user explicitly revokes the app in their Zoho Account security settings.
- The Zoho OAuth app is deleted.

If the token stops working (`Admin token refresh failed: Access Denied` in logs), repeat the steps in 5.1 to generate a new one.

### 5.4 Token Priority in Code

`_get_admin_access_token()` checks in this order:
1. `ZOHO_REFRESH_TOKEN` environment variable (systemd / Secrets Manager)
2. Encrypted token stored in the database (set when any admin logs in via browser)

---

## 6. Ongoing Operations

### 6.1 Deploying Updates

**Standalone:**
```bash
cd /var/www/zohomap
sudo ./update.sh
```

**AWS (both EC2 instances):**
```bash
ssh ec2-user@<instance-ip>
cd /var/www/zohomap
sudo git pull origin main
pip install -r requirements.txt
sudo systemctl restart zohomap
```

For zero-downtime deploys with an ALB, update one instance at a time and wait for it to pass health checks before updating the second.

### 6.2 Viewing Logs

```bash
# In-app debug console:
# Navigate to https://yourdomain.com/admin  (admin users only)

# File-based log:
tail -f /var/www/zohomap/debug.log

# Systemd journal:
sudo journalctl -u zohomap -f
```

### 6.3 Admin Diagnostic Tools

| URL | Description |
|---|---|
| `/admin/crm-explorer` | Browse CRM modules, fields, territories, and users |
| `/admin/refresh-token-setup` | View and export the current refresh token for systemd |
| `/api/admin/test-franchise-lookup` | Test franchise resolution for any user ID |

### 6.4 Updating the Refresh Token

If the server loses CRM access (token revoked):
1. Log in to ZohoMap as Administrator.
2. Visit `/admin/refresh-token-setup` and copy the new token.
3. Update `ZOHO_REFRESH_TOKEN` in systemd or Secrets Manager.
4. Restart the service.

### 6.5 First Login After Fresh Deployment

1. Navigate to the app URL.
2. Log in as **Administrator** — this seeds the admin refresh token in the database as a fallback.
3. Visit `/admin/refresh-token-setup` and add `ZOHO_REFRESH_TOKEN` to systemd/Secrets Manager for permanence.
4. Team users can now log in — their franchise memberships are resolved and cached at login time.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `Admin token refresh failed: Access Denied` in logs | Refresh token revoked | Follow Section 5.1 to get a new token |
| Team user sees 0 records | No franchise assignments, or token was expired at login | Check `/api/admin/test-franchise-lookup?user_id=...`; ensure admin token is valid |
| Team user `user_id` shows as email in logs | Admin token was expired when user logged in → ID not resolved | Fix admin token first, then have team user log out and back in |
| `No records found in bounds` on map | Sync has not run yet, or franchise filter is active | Click **Sync All** as the team user; check debug log |
| RDS connection refused | Security group missing EC2→RDS inbound rule on port 5432 | Add inbound rule: port 5432, source = EC2 security group |
| ALB health checks failing | Gunicorn not running, or `/health` endpoint error | Check `sudo systemctl status zohomap`; check debug log |

---

*Geocoded addresses are cached in the database. Subsequent map loads are significantly faster after the first sync.*
