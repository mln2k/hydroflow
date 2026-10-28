"""Поведение Flask, маршрутов, профиля, обращений и обновления схемы."""
import base64
import concurrent.futures
import json
import threading
import uuid
from unittest import mock
from test_application import Fixture, HTTPFixture
from hydroflow import services as s
from hydroflow.db import migrate, transaction
from hydroflow.server import create_app


class PagesTests(HTTPFixture):
    def test_head_requests_never_mutate_records_or_audit(self):
        with transaction(self.url) as db:
            rid = self.create_req(db)
            tid = self.create_task(db)
            before = {t:db.all(f'SELECT * FROM {t} ORDER BY id') for t in ['projects','requirements','tasks','requirement_versions','audit_log','users']}
        self.login()
        client = create_app({'DATABASE_URL':self.url}).test_client()
        client.set_cookie('hf_session',self.cookie.split('=',1)[1])
        for url in ['/api/projects','/api/users',f'/api/projects/{self.pid}',f'/api/projects/{self.pid}/requirements/{rid}',f'/api/projects/{self.pid}/tasks/{tid}']:
            response = client.head(url)
            with self.subTest(url=url):
                self.assertEqual(response.status_code,200,url)
                self.assertEqual(response.data,b'')
        with transaction(self.url) as db:
            self.assertEqual(before,{t:db.all(f'SELECT * FROM {t} ORDER BY id') for t in before})

    def test_successful_logins_do_not_exhaust_failed_attempt_budget(self):
        for _ in range(16):
            self.login('VIEWER')

    def page(self, path):
        client = create_app({'DATABASE_URL': self.url}).test_client()
        if self.cookie:
            client.set_cookie('hf_session', self.cookie.split('=', 1)[1])
        return client.get(path)

    def test_all_pages_direct_reload_and_permissions(self):
        paths = ['/projects', '/account', '/feedback', '/help', '/admin/users', '/admin/feedback']
        paths += [f'/projects/{self.pid}/{name}' for name in
                  ('overview', 'requirements', 'tasks', 'stages', 'documents', 'members', 'reports', 'activity')]
        self.assertEqual(self.page('/login').status_code, 200)
        self.assertEqual(self.page('/account').status_code, 302)
        self.login()
        for path in paths:
            with self.subTest(path=path):
                for _ in range(2):
                    response = self.page(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('text/html', response.content_type)
                    self.assertIn(b'/pages.js', response.data)
        for role in s.ROLES[1:]:
            self.login(role)
            for path in ['/admin/users', '/admin/feedback']:
                self.assertEqual(self.page(path).status_code, 403)
            self.assertEqual(self.page('/account').status_code, 200)
        with transaction(self.url) as db:
            other = s.save_project(db, self.admin, {'name': 'Private', 'start_date': '2026-01-01'})
        self.assertEqual(self.page(f'/projects/{other}/documents').status_code, 403)
        self.assertEqual(self.page(f'/projects/{self.pid}/unknown').status_code, 404)

    def test_profile_fields_and_assigned_tasks(self):
        with transaction(self.url) as db:
            tid = self.create_task(db)
            s.assign(db, self.admin, self.pid, tid, {'user_ids': [self.users['DEV']['id']]})
        self.login('DEV')
        status, account, _ = self.request('/account')
        self.assertEqual(status, 200)
        self.assertEqual([t['id'] for t in account['tasks']], [tid])
        self.assertNotIn('password_hash', account['user'])
        for field, value in [('role', 'ADMIN'), ('active', False), ('email', 'new@example.local')]:
            self.assertEqual(self.request('/account', 'PATCH', {field: value})[0], 403)
        self.assertEqual(self.request('/account', 'PATCH', {'full_name': ''})[0], 400)
        self.assertEqual(self.request('/account', 'PATCH', {'full_name': 'Имя <script>'})[0], 200)
        self.assertEqual(self.request('/account')[1]['user']['full_name'], 'Имя <script>')
        self.assertEqual(self.request('/account', 'PATCH', {'full_name': 'CSRF'}, csrf=False)[0], 403)

    def test_flask_host_origin_and_request_limits(self):
        app = create_app({'DATABASE_URL': self.url, 'TRUSTED_HOSTS': ['example.local']})
        self.assertEqual(app.test_client().get('/login', base_url='https://evil.local').status_code, 400)
        client = create_app({'DATABASE_URL': self.url, 'MAX_CONTENT_LENGTH': 30}).test_client()
        self.assertEqual(client.post('/api/login', data='x'*31, content_type='application/json').status_code, 413)
        self.assertEqual(client.post('/api/login', data='{}', content_type='text/plain').status_code, 415)
        self.assertEqual(client.post('/api/login', data='{"x":NaN}', content_type='application/json').status_code, 400)
        self.assertEqual(client.post('/api/login', json={}, headers={'Origin': 'https://evil.local'}).status_code, 403)
        self.assertEqual(client.get('/api/no-such-resource').status_code, 404)


class FeedbackTests(HTTPFixture):
    def payload(self, **extra):
        return dict(subject='Вопрос', category='question', body='Тест обращения', request_key=uuid.uuid4().hex, **extra)

    def test_feedback_owner_admin_reply_and_conflict(self):
        self.login('VIEWER')
        data = self.payload(user_id=self.admin['id'], created_at='forged', status='closed')
        status, result, _ = self.request('/feedback', 'POST', data)
        self.assertEqual(status, 201)
        fid = result['id']
        saved = self.request(f'/feedback/{fid}')[1]
        self.assertEqual(saved['user_id'], self.users['VIEWER']['id'])
        self.assertEqual(saved['status'], 'new')
        self.assertNotEqual(saved['created_at'], 'forged')
        self.login('DEV')
        self.assertEqual(self.request(f'/feedback/{fid}')[0], 404)
        self.assertEqual(self.request('/feedback')[1], [])
        for role in s.ROLES[1:]:
            self.login(role)
            self.assertEqual(self.request('/admin/feedback')[0], 403)
            self.assertEqual(self.request(f'/admin/feedback/{fid}', 'PATCH', {'reply':'forged','version':1})[0], 403)
        self.login()
        self.assertEqual(len(self.request('/admin/feedback')[1]), 1)
        self.assertEqual(self.request(f'/admin/feedback/{fid}', 'PATCH', {'reply':'Ответ','status':'work','version':1})[0], 200)
        self.assertEqual(self.request(f'/admin/feedback/{fid}', 'PATCH', {'reply':'Lost','version':1})[0], 409)
        self.login('VIEWER')
        saved = self.request(f'/feedback/{fid}')[1]
        self.assertEqual((saved['reply'], saved['version']), ('Ответ', 2))
        with transaction(self.url) as db:
            logs = db.all("SELECT detail FROM audit_log WHERE entity_type='feedback'")
            self.assertEqual(len(logs), 2)
            self.assertTrue(all('Ответ' not in r['detail'] and 'Тест обращения' not in r['detail'] for r in logs))

    def test_validation_csrf_idempotency_and_rate_limit(self):
        self.login('VIEWER')
        data = self.payload()
        self.assertEqual(self.request('/feedback', 'POST', data, csrf=False)[0], 403)
        self.assertEqual(self.request('/feedback', 'POST', data, origin='https://evil.local')[0], 403)
        for patch in [{'subject':''}, {'subject':'x'*161}, {'body':'x'*10001}, {'category':'other'}, {'request_key':'short'}]:
            self.assertEqual(self.request('/feedback', 'POST', data | patch)[0], 400)
        first = self.request('/feedback', 'POST', data)
        second = self.request('/feedback', 'POST', data)
        self.assertEqual((first[0], second[0]), (201, 200))
        self.assertEqual(first[1]['id'], second[1]['id'])
        self.assertEqual(self.request('/feedback', 'POST', data | {'body':'different'})[0], 409)
        for _ in range(4):
            self.assertEqual(self.request('/feedback', 'POST', self.payload())[0], 201)
        self.assertEqual(self.request('/feedback', 'POST', self.payload())[0], 429)
        self.assertEqual(self.request('/feedback', 'POST', data)[0], 200)


class NewIntegrityTests(Fixture):
    def parallel(self, operation):
        barrier = threading.Barrier(2)
        def run(index):
            barrier.wait()
            try:
                with transaction(self.url) as db:
                    return operation(db, index)
            except s.Error as error:
                return error.status
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            return list(pool.map(run, range(2)))

    def test_concurrent_feedback_replay_creates_one_row_and_audit(self):
        data = dict(subject='Race', category='bug', body='One', request_key=uuid.uuid4().hex)
        results = self.parallel(lambda db, _: s.create_feedback(db, self.admin, data))
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(sorted(r[1] for r in results), [False, True])
        with transaction(self.url) as db:
            self.assertEqual(db.one('SELECT COUNT(*) n FROM feedback')['n'], 1)
            self.assertEqual(db.one("SELECT COUNT(*) n FROM audit_log WHERE entity_type='feedback'")['n'], 1)

    def test_concurrent_administrators_cannot_disable_each_other(self):
        second = self.users['PM'] | {'role':'ADMIN'}
        with transaction(self.url) as db:
            s.update(db, 'users', second['id'], {'role':'ADMIN'})
        actors = [self.admin, second]
        def operation(db, index):
            s.manage_user(db, actors[index], actors[1-index]['id'], {'active':False})
            return 200
        self.assertEqual(sorted(self.parallel(operation)), [200, 403])
        with transaction(self.url) as db:
            self.assertEqual(db.one("SELECT COUNT(*) n FROM users WHERE role='ADMIN' AND active=1")['n'], 1)
            with self.assertRaises(s.Error):
                s.manage_user(db, self.admin, self.admin['id'], {'role':'VIEWER'})

    def test_feedback_failure_rolls_back(self):
        with mock.patch.object(s, 'audit', side_effect=RuntimeError('rollback')):
            with self.assertRaises(RuntimeError), transaction(self.url) as db:
                s.create_feedback(db, self.admin, dict(subject='Atomic',category='bug',body='Text',request_key=uuid.uuid4().hex))
        with transaction(self.url) as db:
            self.assertEqual(db.all('SELECT * FROM feedback'), [])

    def test_v1_upgrade_preserves_every_existing_table_and_attachment(self):
        # Reconstruct exact v1 schema from the pre-migration fixture; no application data is removed.
        with transaction(self.url) as db:
            db.execute('DROP TABLE feedback')
            db.execute('DROP TABLE system_locks')
            db.execute('DELETE FROM schema_migrations WHERE version=2')
            rid = self.create_req(db)
            tid = self.create_task(db, requirement_id=rid)
            s.assign(db,self.admin,self.pid,tid,{'user_ids':[self.users['DEV']['id']]})
            did = s.save_entity(db,self.admin,self.pid,'documents',dict(title='Attachment',content='v1',filename='sample.txt',file_base64=base64.b64encode(b'old bytes').decode()))
            s.save_entity(db,self.admin,self.pid,'documents',dict(content='v2',version=1),did)
            s.comment(db,self.admin,self.pid,dict(entity_type='tasks',entity_id=tid,text='Comment'))
            tables = ['users','projects','project_members','stages','requirements','requirement_versions','tasks','task_assignments','documents','document_versions','comments','audit_log','sessions']
            before = {t:db.all(f'SELECT * FROM {t} ORDER BY id') for t in tables}
        migrate(self.url)
        migrate(self.url)
        with transaction(self.url) as db:
            self.assertEqual(before, {t:db.all(f'SELECT * FROM {t} ORDER BY id') for t in tables})
            self.assertEqual(db.all('SELECT version FROM schema_migrations ORDER BY version'), [{'version':1},{'version':2}])
            self.assertEqual(json.loads(before['document_versions'][0]['snapshot'])['file_base64'], base64.b64encode(b'old bytes').decode())

    def test_concurrent_migration_is_idempotent(self):
        with transaction(self.url) as db:
            db.execute('DROP TABLE feedback')
            db.execute('DROP TABLE system_locks')
            db.execute('DELETE FROM schema_migrations WHERE version=2')
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda _:migrate(self.url), range(2)))
        with transaction(self.url) as db:
            self.assertEqual(db.one('SELECT COUNT(*) n FROM schema_migrations')['n'], 2)
