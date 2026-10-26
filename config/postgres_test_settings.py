"""Real PostgreSQL tests in a fresh isolated schema, without CREATEDB rights."""
import uuid
from .settings import *  # noqa: F403
QA_SCHEMA = 'hotelfood_qa_' + uuid.uuid4().hex[:12]
DATABASES['default']['OPTIONS']['options'] = '-c search_path=' + QA_SCHEMA  # noqa: F405
DATABASES['default']['CONN_MAX_AGE'] = 0  # noqa: F405
TEST_RUNNER = 'config.pg_schema_runner.SchemaTestRunner'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
