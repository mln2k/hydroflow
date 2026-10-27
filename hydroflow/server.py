"""HTTP API; каждый запрос выполняется в отдельной транзакции."""
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .db import transaction, Conflict
from .security import now, future, token_hash, verify_password, hash_password
from . import services as s

STATIC = Path(__file__).resolve().parent.parent / 'static'
LOG = logging.getLogger('hydroflow')
LOGIN_LOCK = threading.Lock()
ATTEMPTS = {}
DUMMY_PASSWORD = hash_password('dummy-password-for-timing-only')


class Handler(BaseHTTPRequestHandler):
    server_version = 'HydroFlow'

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, fmt, *args):
        LOG.info('%s %s', self.client_address[0], fmt % args)

    def send(self, status, value, content_type='application/json; charset=utf-8', headers=None):
        raw = json.dumps(value, ensure_ascii=False).encode() if content_type.startswith('application/json') else value
        self.send_response(status)
        for key, val in {'Content-Type':content_type, 'Content-Length':str(len(raw)), 'Cache-Control':'no-store',
                         'X-Content-Type-Options':'nosniff', 'X-Frame-Options':'DENY', 'Referrer-Policy':'same-origin',
                         'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
                         **(headers or {})}.items():
            self.send_header(key,val)
        self.end_headers()
        self.wfile.write(raw)

    def body(self):
        if 'application/json' not in self.headers.get('Content-Type',''):
            raise s.Error('Ожидается application/json',415)
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 7_500_000:
                raise s.Error('Недопустимый размер запроса',413)
            raw = self.rfile.read(length)
            # Не принимаем NaN/Infinity и суррогаты, которые не кодируются в UTF-8.
            def invalid_constant(value):
                raise ValueError(value)
            data = json.loads(raw, parse_constant=invalid_constant)
            json.dumps(data, ensure_ascii=False).encode('utf-8')
        except (ValueError, UnicodeError, RecursionError):
            raise s.Error('Некорректный JSON') from None
        if not isinstance(data,dict):
            raise s.Error('Ожидается JSON-объект')
        return data

    def cookie(self, token='', clear=False):
        secure = '; Secure' if os.getenv('COOKIE_SECURE') == '1' else ''
        return f'hf_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={0 if clear else 43200}{secure}'

    def session(self, db):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie',''))
            token = cookies['hf_session'].value if 'hf_session' in cookies else ''
        except Exception:
            token = ''
        row = db.one('''SELECT u.id,u.email,u.full_name,u.role,u.active,se.csrf,se.token_hash FROM sessions se
             JOIN users u ON u.id=se.user_id WHERE se.token_hash=? AND se.expires_at>? AND u.active=1''', (token_hash(token),now()))
        if not row:
            raise s.Error('Войдите в систему',401)
        return row

    def check_origin(self):
        origin = self.headers.get('Origin')
        if origin and origin != os.getenv('PUBLIC_ORIGIN', 'http://' + self.headers.get('Host','')):
            raise s.Error('Недопустимый источник запроса',403)

    def do_GET(self):
        self.handle_request('GET')

    def do_POST(self):
        self.handle_request('POST')

    def do_PATCH(self):
        self.handle_request('PATCH')

    def do_DELETE(self):
        self.handle_request('DELETE')

    def handle_request(self, method):
        try:
            path = urlsplit(self.path).path
            if method=='GET' and path in ('/','/app.js','/app.css'):
                filename = {'/':'index.html','/app.js':'app.js','/app.css':'app.css'}[path]
                ctype = {'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/app.css':'text/css; charset=utf-8'}[path]
                return self.send(200,(STATIC/filename).read_bytes(),ctype)
            if path=='/api/health' and method=='GET':
                with transaction(self.server.db_url) as db:
                    db.execute('SELECT 1')
                return self.send(200,{'ok':True})
            if method != 'GET':
                self.check_origin()
            # Не держим блокировку SQLite, пока клиент передаёт тело запроса.
            data = self.body() if method in ('POST','PATCH','DELETE') else {}
            with transaction(self.server.db_url) as db:
                status,value,ctype,headers = self.api(db,method,path,data)
            self.send(status,value,ctype,headers)
        except s.Error as e:
            self.send(e.status,{'error':str(e)})
        except Conflict as e:
            self.send(409,{'error':str(e)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            LOG.exception('Ошибка запроса')
            self.send(500,{'error':'Внутренняя ошибка сервера'})

    def api(self, db, method, path, data):
        ctype,headers = 'application/json; charset=utf-8',{}
        if path=='/api/login' and method=='POST':
            email = data.get('email','')
            if not isinstance(email,str) or len(email)>120:
                raise s.Error('Неверный email или пароль',401)
            key = self.client_address[0]
            with LOGIN_LOCK:
                current = time.monotonic()
                for ip, attempts in list(ATTEMPTS.items()):
                    recent = [t for t in attempts if current-t<900]
                    if recent:
                        ATTEMPTS[ip]=recent
                    else:
                        del ATTEMPTS[ip]
                bucket = ATTEMPTS.setdefault(key,[])
                if len(bucket)>=15:
                    raise s.Error('Слишком много попыток. Повторите через 15 минут',429)
                bucket.append(current)
            user = db.locked_one('SELECT * FROM users WHERE email=?',(email.lower().strip(),))
            valid = verify_password(data.get('password',''), user['password_hash'] if user else DUMMY_PASSWORD)
            if not user or not valid or not user['active']:
                raise s.Error('Неверный email или пароль',401)
            token,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires_at<=?',(now(),))
            db.insert('sessions',dict(token_hash=token_hash(token),user_id=user['id'],csrf=csrf,expires_at=future()))
            headers['Set-Cookie']=self.cookie(token)
            return 200,{'csrf':csrf,'user':{k:user[k] for k in ('id','email','full_name','role')}},ctype,headers
        user = self.session(db)
        if method!='GET' and not hmac.compare_digest(self.headers.get('X-CSRF-Token','').encode(),user['csrf'].encode()):
            raise s.Error('Ошибка CSRF. Обновите страницу',403)
        if path=='/api/me' and method=='GET':
            return 200,{'user':{k:user[k] for k in ('id','email','full_name','role')},'csrf':user['csrf']},ctype,headers
        if path=='/api/logout' and method=='POST':
            db.execute('DELETE FROM sessions WHERE token_hash=?',(user['token_hash'],))
            headers['Set-Cookie']=self.cookie(clear=True)
            return 200,{'ok':True},ctype,headers
        if path=='/api/password' and method=='POST':
            account=db.locked_one('SELECT password_hash FROM users WHERE id=?',(user['id'],))
            if not verify_password(data.get('current_password',''),account['password_hash']):
                raise s.Error('Текущий пароль указан неверно',403)
            try:
                encoded=hash_password(data.get('password'))
            except ValueError as e:
                raise s.Error(str(e)) from e
            db.execute('UPDATE users SET password_hash=? WHERE id=?',(encoded,user['id']))
            db.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
            headers['Set-Cookie']=self.cookie(clear=True)
            return 200,{'ok':True},ctype,headers
        if path=='/api/users':
            s.allow(user['role'],('ADMIN','PM'))
            if method=='GET':
                return 200,db.all('SELECT id,email,full_name,role,active FROM users ORDER BY full_name'),ctype,headers
            if method=='POST':
                return 201,{'id':s.create_user(db,user,data)},ctype,headers
        match=re.fullmatch(r'/api/users/(\d+)',path)
        if match and method=='PATCH':
            s.allow(user['role'],('ADMIN',))
            uid=s.number(match[1])
            if uid==user['id']:
                raise s.Error('Изменение собственной роли или активности запрещено')
            if not db.one('SELECT id FROM users WHERE id=?',(uid,)):
                raise s.Error('Пользователь не найден',404)
            values={}
            if 'active' in data:
                if type(data['active']) is not bool:
                    raise s.Error('active: ожидается boolean')
                values['active']=int(data['active'])
            if 'role' in data:
                values['role']=s.choice(data,'role',s.ROLES)
            if not values:
                raise s.Error('Нет изменений')
            s.update(db,'users',uid,values)
            db.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
            s.audit(db,user,None,'update','users',uid,json.dumps(values))
            return 200,{'ok':True},ctype,headers
        if path=='/api/projects':
            if method=='GET':
                return 200,s.list_projects(db,user),ctype,headers
            if method=='POST':
                return 201,{'id':s.save_project(db,user,data)},ctype,headers
        match=re.fullmatch(r'/api/projects/(\d+)(?:/(.*))?',path)
        if not match:
            raise s.Error('Метод не найден',404)
        pid=s.number(match[1]); tail=match[2] or ''
        role=s.project_role(db,user,pid,write=method!='GET')
        if tail=='member-candidates' and method=='GET':
            s.allow(role,('ADMIN','PM'))
            return 200,db.all('SELECT id,email,full_name,active FROM users WHERE active=1 ORDER BY full_name'),ctype,headers
        if not tail:
            if method=='GET':
                return 200,s.project_detail(db,user,pid),ctype,headers
            if method=='PATCH':
                return 200,{'id':s.save_project(db,user,data,pid)},ctype,headers
        if tail=='members' and method in ('POST','DELETE'):
            s.membership(db,user,pid,data,method=='DELETE')
            return 200,{'ok':True},ctype,headers
        if tail=='comments' and method=='POST':
            return 201,{'id':s.comment(db,user,pid,data)},ctype,headers
        if tail in ('report','report.csv') and method=='GET':
            result=s.report(db,user,pid)
            if tail.endswith('.csv'):
                output=io.StringIO(); writer=csv.writer(output)
                writer.writerow(['ID','Задача','Статус','Приоритет','Срок','Требование'])
                def cell(v):
                    value=str(v) if v is not None else ''
                    return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
                for t in result['tasks']:
                    writer.writerow([cell(t[k]) for k in ('id','title','status','priority','planned_end','requirement_id')])
                return 200,('\ufeff'+output.getvalue()).encode(),'text/csv; charset=utf-8',{'Content-Disposition':'attachment; filename="report.csv"'}
            return 200,result,ctype,headers
        match=re.fullmatch(r'(requirements|tasks|documents|stages)(?:/(\d+))?(?:/(versions|assignments))?',tail)
        if match:
            entity,eid,action=match.groups(); eid=s.number(eid) if eid else None
            if eid:
                record=s.get_entity(db,entity,eid,pid)
            if action=='assignments' and entity=='tasks' and method=='POST':
                s.assign(db,user,pid,eid,data)
                return 200,{'ok':True},ctype,headers
            if action=='versions' and entity in ('requirements','documents') and method=='GET':
                table,fk=('requirement_versions','requirement_id') if entity=='requirements' else ('document_versions','document_id')
                rows=db.all(f'SELECT * FROM {table} WHERE {fk}=? ORDER BY version DESC',(eid,))
                for row in rows:
                    row['snapshot']=json.loads(row['snapshot'])
                return 200,rows,ctype,headers
            if not action:
                if method=='GET' and eid:
                    return 200,record,ctype,headers
                if method=='POST' and not eid or method=='PATCH' and eid:
                    return 201 if method=='POST' else 200,{'id':s.save_entity(db,user,pid,entity,data,eid)},ctype,headers
                if method=='DELETE' and eid:
                    s.allow(s.project_role(db,user,pid),('ADMIN',))
                    if entity in ('requirements','stages'):
                        field='requirement_id' if entity=='requirements' else 'stage_id'
                        if db.one(f'SELECT id FROM tasks WHERE {field}=?',(eid,)):
                            raise s.Error('Сначала уберите связи с задачами',409)
                    if entity in ('requirements','tasks','documents'):
                        db.execute('DELETE FROM comments WHERE entity_type=? AND entity_id=?',(entity,eid))
                    db.execute(f'DELETE FROM {entity} WHERE id=?',(eid,))
                    s.audit(db,user,pid,'delete',entity,eid)
                    return 200,{'ok':True},ctype,headers
        raise s.Error('Метод не найден',404)


def make_server(host='127.0.0.1',port=8000,db_url=None):
    server=ThreadingHTTPServer((host,port),Handler)
    server.db_url=db_url
    return server
