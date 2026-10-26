"""Run real PostgreSQL tests without modifying the application's public tables.

Each run exclusively creates a random schema. Its connections have ONLY that
schema in search_path, so missing tables cannot fall back to production tables.
Cleanup is restricted to the schema this runner successfully created.
"""
import re
from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.test.runner import DiscoverRunner


class SchemaTestRunner(DiscoverRunner):
    created_schema = None

    def setup_databases(self, **kwargs):
        schema = settings.QA_SCHEMA
        if not re.fullmatch(r'hotelfood_qa_[0-9a-f]{12}', schema):
            raise ValueError('Invalid isolated test schema name.')
        connection = connections['default']
        if connection.vendor != 'postgresql':
            raise ValueError('This runner requires PostgreSQL.')
        expected = '-c search_path=' + schema
        if connection.settings_dict.get('OPTIONS', {}).get('options') != expected:
            raise ValueError('The test connection must exclude the public schema.')
        with connection.cursor() as cursor:
            cursor.execute('CREATE SCHEMA ' + connection.ops.quote_name(schema))
        self.created_schema = schema
        try:
            call_command('migrate', verbosity=0, interactive=False)
        except Exception:
            self.teardown_databases(None)
            raise
        print('Tests use an isolated PostgreSQL schema; application data is excluded.')
        return None

    def teardown_databases(self, old_config, **kwargs):
        if self.created_schema is None:
            return
        schema = self.created_schema
        self.created_schema = None
        connections.close_all()
        connection = connections['default']
        with connection.cursor() as cursor:
            cursor.execute('DROP SCHEMA ' + connection.ops.quote_name(schema) + ' CASCADE')
        connection.close()
