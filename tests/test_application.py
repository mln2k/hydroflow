"""Интеграционные проверки бизнес-правил и HTTP-границы."""
import base64
import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from hydroflow.db import migrate, transaction
from hydroflow.security import hash_password, now, verify_password
from hydroflow.server import make_server, ATTEMPTS
from hydroflow import services as s

PASSWORD='Test-only-password-2468'
HASH=hash_password(PASSWORD)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.url=os.getenv('TEST_DATABASE_URL') or 'sqlite:///'+str(Path(self.temp.name)/'test.db')
        migrate(self.url)
        with transaction(self.url) as db:
            # TEST_DATABASE_URL должен указывать только на выделенную тестовую БД.
            for table in ('audit_log','comments','document_versions','documents','task_assignments','tasks',
                          'requirement_versions','requirements','stages','project_members','projects','sessions','users'):
                db.execute(f'DELETE FROM {table}')
            self.users={}
            for role in s.ROLES:
                uid=db.insert('users',dict(email=role.lower()+'@example.local',full_name=role,
                              password_hash=HASH,role=role,active=1,created_at=now()))
                self.users[role]={'id':uid,'role':role}
            self.admin=self.users['ADMIN']
            self.pid=s.save_project(db,self.admin,dict(name='Учебный проект',start_date='2026-01-01',end_date='2026-12-31'))
            for role in s.ROLES[1:]:
                s.membership(db,self.admin,self.pid,dict(user_id=self.users[role]['id'],role=role))

    def tearDown(self):
        self.temp.cleanup()

    def create_req(self,db,**kw):
        return s.save_entity(db,self.admin,self.pid,'requirements',dict(code='REQ-1',title='Требование',description='Описание',**kw))

    def create_task(self,db,**kw):
        return s.save_entity(db,self.admin,self.pid,'tasks',dict(title='Задача',**kw))


class ApplicationTests(Fixture):
    def test_password_hash_and_validation(self):
        self.assertTrue(verify_password(PASSWORD,HASH))
        self.assertFalse(verify_password('incorrect',HASH))
        with self.assertRaises(ValueError):
            hash_password('short')

    def test_viewer_cannot_mutate_any_entity(self):
        with transaction(self.url) as db:
            for entity in s.ENTITIES:
                with self.assertRaises(s.Error) as error:
                    s.save_entity(db,self.users['VIEWER'],self.pid,entity,{'title':'Attack'})
                self.assertEqual(error.exception.status,403)

    def test_project_isolation(self):
        with transaction(self.url) as db:
            other=s.save_project(db,self.admin,dict(name='Закрытый проект',start_date='2026-01-01'))
            with self.assertRaises(s.Error) as error:
                s.project_detail(db,self.users['DEV'],other)
            self.assertEqual(error.exception.status,403)
            self.assertEqual(len(s.list_projects(db,self.users['DEV'])),1)

    def test_only_pm_or_admin_create_projects(self):
        with transaction(self.url) as db:
            with self.assertRaises(s.Error):
                s.save_project(db,self.users['ANALYST'],dict(name='Проект',start_date='2026-01-01'))

    def test_requirement_version_history_and_conflict(self):
        with transaction(self.url) as db:
            rid=self.create_req(db)
            s.save_entity(db,self.users['ANALYST'],self.pid,'requirements',dict(title='Новая редакция',version=1,reason='Уточнение'),rid)
            row=s.get_entity(db,'requirements',rid,self.pid)
            self.assertEqual(row['version'],2)
            history=db.all('SELECT * FROM requirement_versions WHERE requirement_id=? ORDER BY version',(rid,))
            self.assertEqual(len(history),2)
            self.assertEqual(json.loads(history[0]['snapshot'])['title'],'Требование')
            with self.assertRaises(s.Error) as error:
                s.save_entity(db,self.admin,self.pid,'requirements',dict(title='Устаревшая правка',version=1),rid)
            self.assertEqual(error.exception.status,409)

    def test_analyst_cannot_approve_requirement(self):
        with transaction(self.url) as db:
            rid=self.create_req(db)
            with self.assertRaises(s.Error):
                s.save_entity(db,self.users['ANALYST'],self.pid,'requirements',dict(status='approved',version=1),rid)

    def test_approved_requirement_edit_requires_new_review(self):
        with transaction(self.url) as db:
            rid=self.create_req(db,status='approved')
            s.save_entity(db,self.users['ANALYST'],self.pid,'requirements',dict(version=1,title='Уточнение'),rid)
            self.assertEqual(s.get_entity(db,'requirements',rid,self.pid)['status'],'draft')

    def test_duplicate_requirement_code(self):
        with transaction(self.url) as db:
            self.create_req(db)
            with self.assertRaises(s.Error) as error:
                self.create_req(db)
            self.assertEqual(error.exception.status,409)

    def test_cross_project_requirement_link_rejected(self):
        with transaction(self.url) as db:
            rid=self.create_req(db)
            pid=s.save_project(db,self.admin,dict(name='Другой',start_date='2026-01-01'))
            with self.assertRaises(s.Error):
                s.save_entity(db,self.admin,pid,'tasks',dict(title='Неверная связь',requirement_id=rid))

    def test_cross_project_stage_link_rejected(self):
        with transaction(self.url) as db:
            stage=s.save_entity(db,self.admin,self.pid,'stages',dict(title='Этап',start_date='2026-01-01',end_date='2026-02-01'))
            pid=s.save_project(db,self.admin,dict(name='Другой',start_date='2026-01-01'))
            with self.assertRaises(s.Error):
                s.save_entity(db,self.admin,pid,'tasks',dict(title='Неверная связь',stage_id=stage))

    def test_developer_can_only_change_assigned_task_status(self):
        with transaction(self.url) as db:
            tid=self.create_task(db)
            developer=self.users['DEV']
            with self.assertRaises(s.Error):
                s.save_entity(db,developer,self.pid,'tasks',dict(status='work'),tid)
            s.assign(db,self.admin,self.pid,tid,dict(user_ids=[developer['id']]))
            s.save_entity(db,developer,self.pid,'tasks',dict(status='done'),tid)
            row=s.get_entity(db,'tasks',tid,self.pid)
            self.assertIsNotNone(row['actual_start']); self.assertIsNotNone(row['actual_end'])
            with self.assertRaises(s.Error):
                s.save_entity(db,developer,self.pid,'tasks',dict(title='Overwrite'),tid)
            s.save_entity(db,developer,self.pid,'tasks',dict(status='work'),tid)
            self.assertIsNone(s.get_entity(db,'tasks',tid,self.pid)['actual_end'])

    def test_developer_creates_only_own_work_type(self):
        with transaction(self.url) as db:
            with self.assertRaises(s.Error):
                s.save_entity(db,self.users['DEV'],self.pid,'tasks',dict(title='Тестирование',type='test'))
            tid=s.save_entity(db,self.users['DEV'],self.pid,'tasks',dict(title='Разработка',type='dev'))
            self.assertTrue(db.one('SELECT id FROM task_assignments WHERE task_id=?',(tid,)))

    def test_assignment_to_nonmember_and_viewer_rejected(self):
        with transaction(self.url) as db:
            tid=self.create_task(db)
            for uid in (999999,self.users['VIEWER']['id']):
                with self.assertRaises(s.Error):
                    s.assign(db,self.admin,self.pid,tid,dict(user_ids=[uid]))

    def test_member_with_assigned_work_cannot_be_removed(self):
        with transaction(self.url) as db:
            tid=self.create_task(db)
            uid=self.users['DEV']['id']
            s.assign(db,self.admin,self.pid,tid,dict(user_ids=[uid]))
            with self.assertRaises(s.Error):
                s.membership(db,self.admin,self.pid,dict(user_id=uid),remove=True)

    def test_bad_date_range(self):
        with transaction(self.url) as db:
            with self.assertRaises(s.Error):
                self.create_task(db,planned_start='2026-05-02',planned_end='2026-05-01')

    def test_file_versions_preserve_original_bytes(self):
        with transaction(self.url) as db:
            did=s.save_entity(db,self.admin,self.pid,'documents',dict(title='ТЗ',filename='spec.txt',file_base64=base64.b64encode('Версия 1'.encode()).decode()))
            s.save_entity(db,self.admin,self.pid,'documents',dict(version=1,content='Описание версии 2'),did)
            row=db.one('SELECT snapshot FROM document_versions WHERE document_id=? AND version=1',(did,))
            self.assertEqual(base64.b64decode(json.loads(row['snapshot'])['file_base64']).decode(),'Версия 1')
            with self.assertRaises(s.Error):
                s.save_entity(db,self.admin,self.pid,'documents',dict(title='Плохой',filename='../escape',file_base64='eA=='))

    def test_comment_target_must_exist_in_project(self):
        with transaction(self.url) as db:
            with self.assertRaises(s.Error):
                s.comment(db,self.admin,self.pid,dict(entity_type='tasks',entity_id=99999,text='Test'))

    def test_report_tracks_requirement_changes(self):
        with transaction(self.url) as db:
            rid=self.create_req(db)
            tid=self.create_task(db,requirement_id=rid,status='done')
            s.save_entity(db,self.admin,self.pid,'requirements',dict(title='Изменённое',version=1),rid)
            result=s.report(db,self.users['VIEWER'],self.pid)
            self.assertEqual(result['progress'],100)
            self.assertEqual(result['impact'][0]['completed_task_ids'],[tid])

    def test_transaction_rolls_back_all_changes(self):
        try:
            with transaction(self.url) as db:
                self.create_task(db)
                raise RuntimeError('rollback')
        except RuntimeError:
            pass
        with transaction(self.url) as db:
            self.assertFalse(db.one('SELECT id FROM tasks'))


class HTTPTests(Fixture):
    def setUp(self):
        super().setUp()
        ATTEMPTS.clear()
        self.server=make_server(port=0,db_url=self.url)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.port=self.server.server_address[1]
        self.cookie=''; self.csrf=''

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        super().tearDown()

    def request(self,path,method='GET',data=None,csrf=True,origin=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
        headers={'Content-Type':'application/json','Cookie':self.cookie}
        if csrf: headers['X-CSRF-Token']=self.csrf
        if origin: headers['Origin']=origin
        conn.request(method,'/api'+path,None if data is None else json.dumps(data),headers)
        response=conn.getresponse(); raw=response.read()
        result=json.loads(raw) if 'application/json' in response.getheader('Content-Type','') else raw
        status=response.status; returned_headers=dict(response.getheaders());conn.close()
        return status,result,returned_headers

    def login(self,role='ADMIN'):
        status,result,headers=self.request('/login','POST',dict(email=role.lower()+'@example.local',password=PASSWORD))
        self.assertEqual(status,200)
        self.cookie=headers['Set-Cookie'].split(';')[0];self.csrf=result['csrf']
        return headers

    def test_http_authentication_csrf_logout(self):
        self.assertEqual(self.request('/projects')[0],401)
        headers=self.login()
        self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        self.assertEqual(self.request('/projects','POST',{},csrf=False)[0],403)
        self.assertEqual(self.request('/projects','POST',{},origin='https://attacker.invalid')[0],403)
        self.assertEqual(self.request('/projects')[0],200)
        self.assertEqual(self.request('/logout','POST',{})[0],200)
        self.assertEqual(self.request('/me')[0],401)

    def test_http_wrong_password(self):
        self.assertEqual(self.request('/login','POST',dict(email='admin@example.local',password='wrong'))[0],401)

    def test_http_deactivation_revokes_session(self):
        self.login('DEV'); developer_cookie=self.cookie; developer_csrf=self.csrf
        self.login()
        self.assertEqual(self.request('/users/'+str(self.users['DEV']['id']),'PATCH',dict(active=False))[0],200)
        self.cookie=developer_cookie;self.csrf=developer_csrf
        self.assertEqual(self.request('/me')[0],401)

    def test_http_viewer_write_denied(self):
        self.login('VIEWER')
        self.assertEqual(self.request('/projects/'+str(self.pid)+'/tasks','POST',dict(title='Attack'))[0],403)

    def test_http_json_report_and_csv_formula_escape(self):
        with transaction(self.url) as db:
            s.save_entity(db,self.admin,self.pid,'tasks',dict(title='=1+1'))
        self.login()
        self.assertEqual(self.request('/projects/'+str(self.pid)+'/report')[0],200)
        status,raw,_=self.request('/projects/'+str(self.pid)+'/report.csv')
        self.assertEqual(status,200);self.assertIn("'=1+1",raw.decode('utf-8-sig'))

    def test_http_sql_injection_and_xss_stored_as_text(self):
        self.login()
        payload="<img src=x onerror=alert(1)> '); DROP TABLE users;--"
        status,result,_=self.request('/projects/'+str(self.pid)+'/tasks','POST',dict(title=payload))
        self.assertEqual(status,201)
        status,row,_=self.request('/projects/'+str(self.pid)+'/tasks/'+str(result['id']))
        self.assertEqual(row['title'],payload)
        self.assertEqual(self.request('/users')[0],200)


if __name__=='__main__':
    unittest.main()
