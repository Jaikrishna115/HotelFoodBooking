"""Test the configured database without displaying credentials."""
from pathlib import Path
import sys
import psycopg
from dotenv import dotenv_values

values = dotenv_values(Path(__file__).resolve().parent.parent / '.env')
if not values.get('DB_USER') or values['DB_USER'].startswith('YOUR_') or not values.get('DB_PASSWORD') or values['DB_PASSWORD'].startswith('YOUR_'):
    sys.exit('Fill DB_USER and DB_PASSWORD in .env. The database name is hotelfood_db.')
try:
    with psycopg.connect(dbname=values.get('DB_NAME', 'hotelfood_db'),
                         user=values['DB_USER'], password=values['DB_PASSWORD'],
                         host=values.get('DB_HOST', '127.0.0.1'), port=values.get('DB_PORT', '5432'),
                         connect_timeout=5) as conn:
        conn.execute('SELECT 1')
except psycopg.Error:
    sys.exit('Cannot connect to PostgreSQL. Check the local .env login details and that the database service is running.')
print('PostgreSQL connection successful.')
