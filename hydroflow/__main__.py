import argparse
import getpass
import logging
import os
import secrets
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from .db import migrate, transaction
from .security import now, hash_password
from .server import make_server
from . import services as s


def main():
    parser=argparse.ArgumentParser(description='HydroFlow — управление разработкой ПО')
    sub=parser.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init',help='Миграции и создание администратора')
    init.add_argument('--email',default='admin@example.local')
    init.add_argument('--name',default='Администратор')
    sub.add_parser('demo',help='Добавить вымышленные данные в пустую БД')
    run=sub.add_parser('serve',help='Запустить HTTP-сервер')
    run.add_argument('--host',default='127.0.0.1'); run.add_argument('--port',type=int,default=8000)
    backup=sub.add_parser('backup',help='Согласованная резервная копия SQLite')
    backup.add_argument('destination')
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    if args.command=='backup':
        url=os.getenv('DATABASE_URL','sqlite:///data/hydroflow.db')
        if not url.startswith('sqlite:///'):
            parser.error('Для PostgreSQL используйте pg_dump; см. docs/operations.md')
        target=Path(args.destination)
        if target.exists():
            parser.error('Файл назначения уже существует')
        target.parent.mkdir(parents=True,exist_ok=True)
        source=sqlite3.connect(url.removeprefix('sqlite:///'))
        destination=sqlite3.connect(target)
        source.backup(destination); destination.close(); source.close()
        print(f'Резервная копия: {target}')
        return
    migrate()
    if args.command=='init':
        with transaction() as db:
            if db.one('SELECT id FROM users LIMIT 1'):
                print('База уже инициализирована; миграции применены.'); return
            password=os.getenv('HYDROFLOW_ADMIN_PASSWORD') or getpass.getpass('Пароль администратора (12–128 символов): ')
            # Используем ту же валидацию учётных записей, что и в API.
            s.create_user(db,{'role':'ADMIN','bootstrap':True},dict(email=args.email,full_name=args.name,role='ADMIN',password=password))
            print(f'Создан администратор: {args.email}')
    elif args.command=='demo':
        with transaction() as db:
            admin=db.one("SELECT * FROM users WHERE role='ADMIN' ORDER BY id LIMIT 1")
            if not admin:
                parser.error('Сначала выполните python -m hydroflow init')
            if db.one('SELECT id FROM projects LIMIT 1'):
                parser.error('Демонстрационные данные добавляются только в БД без проектов')
            people=[]
            for role,name in [('PM','Елена Волкова'),('ANALYST','Алексей Морозов'),('DEV','Мария Соколова'),('QA','Иван Лебедев'),('VIEWER','Заказчик')]:
                password=secrets.token_urlsafe(15)
                email=role.lower()+'@example.local'
                uid=s.create_user(db,admin,dict(email=email,full_name=name,role=role,password=password))
                people.append((uid,role))
                print(f'{role}: {email}  пароль: {password}')
            today=date.today()
            pid=s.save_project(db,admin,dict(name='Система мониторинга гидроузла',customer='Учебный заказчик',
                description='Учебный проект разработки ПО для регистрации наблюдений и подготовки отчётов. Все данные вымышлены.',
                start_date=str(today-timedelta(days=14)),end_date=str(today+timedelta(days=45)),status='active'))
            for uid,role in people:
                s.membership(db,admin,pid,dict(user_id=uid,role=role))
            stage=s.save_entity(db,admin,pid,'stages',dict(title='Разработка первой версии',start_date=str(today-timedelta(days=7)),end_date=str(today+timedelta(days=30))))
            for i,(title,desc) in enumerate([
                ('Журнал наблюдений','Пользователь регистрирует дату, участок, показатель и примечание.'),
                ('Согласование отчёта','Руководитель проверяет отчёт перед передачей заказчику.'),
                ('Роли и доступ','Наблюдатель читает данные, участники работают в пределах своих ролей.')],1):
                rid=s.save_entity(db,admin,pid,'requirements',dict(code=f'REQ-{i:03}',title=title,description=desc,status='approved' if i<3 else 'review',priority='high'))
                tid=s.save_entity(db,admin,pid,'tasks',dict(title=['Спроектировать журнал наблюдений','Реализовать согласование отчёта','Проверить разграничение доступа'][i-1],
                    requirement_id=rid,stage_id=stage,type='test' if i==3 else 'dev',status=['done','work','new'][i-1],priority='high',
                    planned_start=str(today-timedelta(days=5)),planned_end=str(today+timedelta(days=i*3-5))))
                s.assign(db,admin,pid,tid,dict(user_ids=[people[3 if i==3 else 2][0]]))
            s.save_entity(db,admin,pid,'documents',dict(title='Техническое задание',doc_type='TZ',content='Учебная версия. Цель: разработать журнал наблюдений, согласование отчётов и разграничение доступа.'))
            print('Демонстрационный проект создан.')
    else:
        server=make_server(args.host,args.port)
        print(f'HydroFlow: http://{args.host}:{args.port}',flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__=='__main__':
    try:
        main()
    except (s.Error, ValueError) as error:
        logging.error('%s',error)
        raise SystemExit(1) from None
