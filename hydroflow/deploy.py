"""Идемпотентная подготовка PostgreSQL и запуск WSGI на хостинге."""
import os
from urllib.parse import urlsplit
from . import services as s
from .db import migrate, transaction
from .server import serve


def prepare():
    url = os.environ.get('DATABASE_URL', '')
    if not url.startswith(('postgresql://', 'postgres://')):
        raise ValueError('Для размещения требуется постоянная PostgreSQL DATABASE_URL')
    origin = os.environ.get('PUBLIC_ORIGIN') or os.environ.get('RENDER_EXTERNAL_URL', '')
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('PUBLIC_ORIGIN должен содержать HTTPS origin без пути и учётных данных')
    os.environ['PUBLIC_ORIGIN'] = origin.rstrip('/')
    os.environ['COOKIE_SECURE'] = '1'
    os.environ.setdefault('TRUSTED_HOSTS', parsed.hostname + ',127.0.0.1,localhost')
    migrate(url)
    with transaction(url) as db:
        db.locked_one("SELECT name FROM system_locks WHERE name='administrators'")
        if not db.one('SELECT id FROM users LIMIT 1'):
            password = os.environ.get('HYDROFLOW_ADMIN_PASSWORD')
            if not password:
                raise ValueError('Для первого запуска задайте HYDROFLOW_ADMIN_PASSWORD в секретах хостинга')
            s.create_user(db, {'role':'ADMIN', 'bootstrap':True}, {
                'email':os.environ.get('HYDROFLOW_ADMIN_EMAIL', 'admin@example.local'),
                'full_name':'Администратор учебной установки', 'role':'ADMIN', 'password':password,
            })


def main():
    try:
        prepare()
        serve('0.0.0.0', int(os.environ.get('PORT', '8000')))
    except (ValueError, s.Error) as error:
        raise SystemExit(str(error)) from None


if __name__ == '__main__':
    main()
