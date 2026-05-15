#!/bin/bash

echo "=========================================="
echo "    ZohoMap PostgreSQL Setup Script"
echo "=========================================="

echo "1. Installing PostgreSQL..."
sudo apt-get update
sudo apt-get install -y postgresql postgresql-contrib

echo "2. Securing and Configuring PostgreSQL..."
DB_USER="zohouser"
DB_PASS="zohopassword123!"
DB_NAME="zohomap"

# Run psql commands as the postgres user
sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;"
sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';"
sudo -u postgres psql -c "ALTER ROLE $DB_USER SET client_encoding TO 'utf8';"
sudo -u postgres psql -c "ALTER ROLE $DB_USER SET default_transaction_isolation TO 'read committed';"
sudo -u postgres psql -c "ALTER ROLE $DB_USER SET timezone TO 'UTC';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"

# Grant schema privileges (required in Postgres 15+)
sudo -u postgres psql -d $DB_NAME -c "GRANT ALL ON SCHEMA public TO $DB_USER;"

echo "=========================================="
echo "    PostgreSQL Setup Complete!"
echo "=========================================="
echo "Please update your config.ini with the following database_uri:"
echo "database_uri = postgresql://$DB_USER:$DB_PASS@localhost/$DB_NAME"
echo ""
echo "Then, activate your virtual environment and run the migration script:"
echo "source venv/bin/activate"
echo "python migrate_rds.py"
echo "sudo systemctl restart zohomap"
