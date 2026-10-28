"""Создать отдельную учебную SQLite БД и отдельную памятку случайных паролей."""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--accounts', required=True, type=Path)
    args = parser.parse_args()
    database, accounts = args.database.resolve(), args.accounts.resolve()
    if database == accounts or database.exists() or accounts.exists():
        parser.error('Нужны два разных новых пути. Существующие файлы не изменяются.')
    database.parent.mkdir(parents=True, exist_ok=True)
    accounts.parent.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(24)
    env = {**os.environ, 'DATABASE_URL':'sqlite:///' + str(database),
           'HYDROFLOW_ADMIN_PASSWORD':password, 'PYTHONIOENCODING':'utf-8'}
    root = Path(__file__).resolve().parents[1]
    # Эксклюзивно резервируем оба имени, чтобы не затронуть существующую установку.
    with database.open('xb'):
        pass
    with accounts.open('x', encoding='utf-8') as output:
        output.write('Только синтетическая учебная установка HydroFlow. Не использовать эти пароли в рабочей системе.\n')
        output.write(f'База: {database}\nADMIN: admin@example.local  пароль: {password}\n')
        for command in ['init', 'demo']:
            result = subprocess.run([sys.executable, '-m', 'hydroflow', command], cwd=root,
                                    env=env, text=True, encoding='utf-8', capture_output=True)
            if result.returncode:
                raise SystemExit('Создание не завершено; проверяйте только новые выходные файлы: ' + result.stderr)
            output.write(result.stdout)
    print(f'Учебная БД: {database}\nОтдельная памятка доступа: {accounts}')


if __name__ == '__main__':
    main()
