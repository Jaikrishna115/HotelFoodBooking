"""Local interactive setup; passwords are read without echoing to the terminal."""
from getpass import getpass
from pathlib import Path
import secrets
import sys
import psycopg
from dotenv import dotenv_values, set_key

root = Path(__file__).resolve().parent.parent
path = root / '.env'
if not path.exists():
    path.write_text('', encoding='utf-8')
values = dotenv_values(path)
defaults = {
    'DJANGO_SECRET_KEY': secrets.token_urlsafe(64), 'DJANGO_DEBUG': '1',
    'DJANGO_ALLOWED_HOSTS': '127.0.0.1,localhost', 'DB_NAME': 'hotelfood_db',
    'DB_HOST': '127.0.0.1', 'DB_PORT': '5432',
}
for key, value in defaults.items():
    if not values.get(key) or values.get(key) == 'replace-with-a-long-random-secret':
        set_key(path, key, value)
values = dotenv_values(path)
username = values.get('DB_USER', '')
password = values.get('DB_PASSWORD', '')
if not username or username.startswith('YOUR_'):
    username = input('PostgreSQL username (the login used in pgAdmin): ').strip()
if not password or password.startswith('YOUR_'):
    password = getpass('PostgreSQL password (hidden while typing): ')
if not username or not password:
    sys.exit('Username and password are required. Nothing was connected.')
try:
    with psycopg.connect(dbname=values['DB_NAME'], user=username, password=password,
                         host=values['DB_HOST'], port=values['DB_PORT'], connect_timeout=5) as conn:
        conn.execute('SELECT 1')
except psycopg.Error:
    sys.exit('Connection failed. Check PostgreSQL is running, database name, username, password and permissions. No password was printed.')
set_key(path, 'DB_USER', username)
set_key(path, 'DB_PASSWORD', password)
print('Connected to PostgreSQL. Connection details saved only in your local .env file.')
