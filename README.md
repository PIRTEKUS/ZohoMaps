# ZohoMap

ZohoMap is a Python/Flask web application that integrates with Zoho CRM and Google Maps. It provides a dynamic, self-service portal where you can authenticate via Zoho OAuth 2.0, map records from any Zoho Module (e.g., Accounts, Leads), and visualize them geographically based on user access permissions.

## Features

- **Zoho OAuth 2.0 Integration**: Ensures users only see records they have permission to access.
- **Dynamic Module Settings**: Configure which Zoho modules to display directly from the admin UI.
- **Address or Coordinate Mapping**: Map records using text fields (Address, City, State, etc.) or precise Latitude/Longitude fields.
- **Smart Geocoding**: Automatically converts addresses to coordinates using the Google Maps Geocoding API and caches them locally (SQLite) to reduce API costs and improve performance.
- **Customizable Map Markers**: Select custom colors for different modules to distinguish records easily on the map.
- **Modern User Interface**: A premium "Glassmorphism" UI with dynamic micro-animations.

---

## Deployment on Ubuntu Server

The following instructions will guide you through deploying this application on a production Ubuntu server using Gunicorn and Nginx.

### 1. Prerequisites

Ensure your Ubuntu server has Python 3, `pip`, `venv`, and `nginx` installed:

```bash
sudo apt update
sudo apt install python3-pip python3-venv nginx git -y
```

### 2. Clone the Repository

Clone this repository into your desired directory (e.g., `/var/www/zohomap`):

```bash
sudo mkdir -p /var/www/zohomap
sudo chown $USER:$USER /var/www/zohomap
git clone https://github.com/PIRTEKUS/ZohoMaps.git /var/www/zohomap
cd /var/www/zohomap
```

### 3. Setup the Python Virtual Environment

Create and activate a virtual environment, then install the required dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn  # Required for production serving
```

### 4. Configuration (`config.ini`)

Copy the example configuration file and fill in your actual credentials:

```bash
cp config.ini.example config.ini
nano config.ini
```

**Required Configuration Values:**
- `client_id` & `client_secret`: Obtain these by creating a "Server-based Application" in the [Zoho Developer Console](https://api-console.zoho.com/).
- `redirect_uri`: Must match exactly what is registered in the Zoho Developer Console (e.g., `https://yourdomain.com/callback`).
- `maps_api_key`: Your Google Maps API Key with **Maps JavaScript API** and **Geocoding API** enabled.
- `secret_key`: A random string used for securing Flask sessions. (e.g., generate one with `python3 -c "import secrets; print(secrets.token_hex(24))"`).

### 5. Setup Gunicorn Systemd Service

Create a systemd service file to keep the application running in the background:

```bash
sudo nano /etc/systemd/system/zohomap.service
```

Paste the following configuration (adjust user and paths if necessary):

```ini
[Unit]
Description=Gunicorn instance to serve ZohoMap
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/zohomap
Environment="PATH=/var/www/zohomap/venv/bin"
ExecStart=/var/www/zohomap/venv/bin/gunicorn --workers 3 --bind unix:zohomap.sock -m 007 app:app

[Install]
WantedBy=multi-user.target
```

Start and enable the service:

```bash
sudo chown -R www-data:www-data /var/www/zohomap
sudo systemctl start zohomap
sudo systemctl enable zohomap
```

### 6. Configure Nginx

Create a new Nginx server block:

```bash
sudo nano /etc/nginx/sites-available/zohomap
```

Add the following configuration (replace `yourdomain.com` with your actual domain or IP address):

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        include proxy_params;
        proxy_pass http://unix:/var/www/zohomap/zohomap.sock;
    }
}
```

Enable the configuration and restart Nginx:

```bash
sudo ln -s /etc/nginx/sites-available/zohomap /etc/nginx/sites-enabled
sudo nginx -t
sudo systemctl restart nginx
```

> [!IMPORTANT]
> **Switching from IP to Domain Name:** If you initially set up the app using the server's IP address and later map a DNS name (domain) to it, you **must** update the `server_name` directive in `/etc/nginx/sites-available/zohomap` to match your new domain name (e.g., `server_name maps.yourdomain.com;`). After editing, always run `sudo systemctl restart nginx`. If you forget this, accessing via the domain name will show the default "Welcome to Nginx" page instead of the app.

### 7. Usage

1. Navigate to your server's domain/IP.
2. Click **Connect with Zoho** to authorize your account.
3. Once logged in, go to **Settings** in the top navigation bar.
4. Select a Zoho Module from the dropdown (e.g., Accounts).
5. Choose your **Marker Color**.
6. Select **Location Type**:
   - **Address Fields**: Map your Zoho Street, City, State, and Zip fields. The backend will automatically geocode these into coordinates.
   - **Latitude/Longitude**: If you already have precise coordinates stored in your Zoho records, map those fields directly.
7. Click **Save Mapping**.
8. Navigate back to the **Map View** to see your data mapped!

---
*Note: Geocoded addresses are automatically cached in the local `database.db` file to save on Google Maps API calls. Subsequent map loads will be significantly faster.*
