"""Регрессии аудита: реальные HTTP-границы, транзакции и конкурентные записи."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import http.client
import threading
import unittest
from unittest.mock import patch

import test_application as base
from hydroflow import services as s
from hydroflow.db import migrate, transaction


class AccessTests(base.HTTPFixture):
    def test_concurrent_duplicate_code_returns_conflict(self):
        self.login()
        barrier=threading.Barrier(2)
        def create(_):
            barrier.wait(timeout=10)
            return self.request(f'/projects/{self.pid}/requirements','POST',dict(code='SAME',title='Concurrent',description='Test'))[0]
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(create,range(2))),[201,409])
        with transaction(self.url) as db:
            self.assertEqual(len(db.all('SELECT * FROM requirements')),1)
            self.assertEqual(len(db.all('SELECT * FROM requirement_versions')),1)

    def test_concurrent_comment_and_delete_never_leaves_orphan(self):
        self.login()
        for _ in range(4):
            with transaction(self.url) as db:
                tid=self.create_task(db)
            barrier=threading.Barrier(2)
            def act(method):
                barrier.wait(timeout=10)
                if method=='DELETE':return self.request(f'/projects/{self.pid}/tasks/{tid}',method,{})[0]
                return self.request(f'/projects/{self.pid}/comments',method,dict(entity_type='tasks',entity_id=tid,text='Race'))[0]
            with ThreadPoolExecutor(max_workers=2) as executor:
                deleted,commented=executor.map(act,('DELETE','POST'))
            self.assertEqual(deleted,200);self.assertIn(commented,(201,404))
            with transaction(self.url) as db:
                self.assertFalse(db.one('SELECT id FROM comments WHERE entity_id=?',(tid,)))

    def test_concurrent_assignment_and_member_removal_stay_consistent(self):
        self.login()
        uid=self.users['DEV']['id']
        with transaction(self.url) as db:
            tid=self.create_task(db)
        barrier=threading.Barrier(2)
        def act(action):
            barrier.wait(timeout=10)
            if action=='assign':return self.request(f'/projects/{self.pid}/tasks/{tid}/assignments','POST',dict(user_ids=[uid]))[0]
            return self.request(f'/projects/{self.pid}/members','DELETE',dict(user_id=uid))[0]
        with ThreadPoolExecutor(max_workers=2) as executor:
            assigned,removed=executor.map(act,('assign','remove'))
        self.assertIn((assigned,removed),((200,409),(400,200)))
        with transaction(self.url) as db:
            member=db.one('SELECT id FROM project_members WHERE project_id=? AND user_id=?',(self.pid,uid))
            assignment=db.one('SELECT id FROM task_assignments WHERE task_id=? AND user_id=?',(tid,uid))
            self.assertEqual(bool(member),bool(assignment))

    def test_malformed_json_and_oversized_ids_are_client_errors(self):
        self.login()
        for body in ('{"title":NaN}', '{"title":"\\ud800"}', '['*1100+'0'+']'*1100, '[]'):
            conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
            conn.request('POST',f'/api/projects/{self.pid}/tasks',body,{'Content-Type':'application/json','Cookie':self.cookie,'X-CSRF-Token':self.csrf})
            response=conn.getresponse();response.read();conn.close()
            self.assertEqual(response.status,400)
        self.assertEqual(self.request('/projects/'+str(2**100))[0],400)
        self.assertEqual(self.request(f'/projects/{self.pid}/tasks','POST',dict(title='Huge ID',requirement_id=2**100))[0],400)

    def test_project_pm_can_select_members_without_system_pm_privilege(self):
        with transaction(self.url) as db:
            s.membership(db,self.admin,self.pid,dict(user_id=self.users['DEV']['id'],role='PM'))
        self.login('DEV')
        self.assertEqual(self.request('/users')[0],403)
        status,users,_=self.request(f'/projects/{self.pid}/member-candidates')
        self.assertEqual(status,200)
        self.assertIn(self.users['QA']['id'],[u['id'] for u in users])
        self.assertFalse(any('password_hash' in u for u in users))
        self.assertEqual(self.request(f'/projects/{self.pid}/members','POST',dict(user_id=self.users['QA']['id'],role='DEV'))[0],200)

    def test_assigned_member_cannot_be_demoted_to_viewer(self):
        with transaction(self.url) as db:
            tid=self.create_task(db)
            s.assign(db,self.admin,self.pid,tid,dict(user_ids=[self.users['DEV']['id']]))
        self.login('PM')
        self.assertEqual(self.request(f'/projects/{self.pid}/members','POST',dict(user_id=self.users['DEV']['id'],role='VIEWER'))[0],409)
        with transaction(self.url) as db:
            self.assertEqual(s.project_role(db,self.users['DEV'],self.pid),'DEV')

    def test_inactive_member_removal_after_unassignment(self):
        with transaction(self.url) as db:
            tid=self.create_task(db)
            uid=self.users['DEV']['id']
            s.assign(db,self.admin,self.pid,tid,dict(user_ids=[uid]))
        self.login()
        self.assertEqual(self.request(f'/users/{uid}','PATCH',dict(active=False))[0],200)
        self.assertEqual(self.request(f'/projects/{self.pid}/members','DELETE',dict(user_id=uid))[0],409)
        self.assertEqual(self.request(f'/projects/{self.pid}/tasks/{tid}/assignments','POST',dict(user_ids=[uid]))[0],400)
        self.assertEqual(self.request(f'/projects/{self.pid}/tasks/{tid}/assignments','POST',dict(user_ids=[]))[0],200)
        self.assertEqual(self.request(f'/projects/{self.pid}/members','DELETE',dict(user_id=uid))[0],200)

    def test_private_objects_versions_and_reports_are_isolated(self):
        with transaction(self.url) as db:
            private=s.save_project(db,self.admin,dict(name='Private',start_date='2026-01-01'))
            did=s.save_entity(db,self.admin,private,'documents',dict(title='Secret',filename='secret.txt',file_base64='eA=='))
            rid=s.save_entity(db,self.admin,private,'requirements',dict(code='SECRET',title='Secret',description='Private'))
            sid=s.save_entity(db,self.admin,private,'stages',dict(title='Secret',start_date='2026-01-01',end_date='2026-02-01'))
        self.login('DEV')
        for suffix in ('',f'/documents/{did}',f'/documents/{did}/versions',f'/requirements/{rid}/versions','/report','/report.csv','/member-candidates'):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.request(f'/projects/{private}'+suffix)[0],403)
        for suffix in (f'/documents/{did}',f'/documents/{did}/versions',f'/requirements/{rid}/versions'):
            self.assertEqual(self.request(f'/projects/{self.pid}'+suffix)[0],404)
        self.assertEqual(self.request(f'/projects/{self.pid}/tasks','POST',dict(title='Attack',type='dev',requirement_id=rid))[0],404)
        self.assertEqual(self.request(f'/projects/{self.pid}/tasks','POST',dict(title='Attack',type='dev',stage_id=sid))[0],404)

    def test_role_matrix_on_http_create_and_comments(self):
        allowed={'requirements':{'ADMIN','PM','ANALYST'},'tasks':set(s.ROLES)-{'VIEWER'},
                 'documents':{'ADMIN','PM','ANALYST','DEV'},'stages':{'ADMIN','PM'}}
        with transaction(self.url) as db:
            tid=self.create_task(db)
        for role in s.ROLES:
            self.login(role)
            for entity in s.ENTITIES:
                with self.subTest(role=role,entity=entity):
                    data=dict(title=role,description='Description',code=role,type='test' if role=='QA' else 'dev',start_date='2026-01-01',end_date='2026-02-01')
                    self.assertEqual(self.request(f'/projects/{self.pid}/{entity}','POST',data)[0],201 if role in allowed[entity] else 403)
            self.assertEqual(self.request(f'/projects/{self.pid}/comments','POST',dict(entity_type='tasks',entity_id=tid,text=role))[0],403 if role=='VIEWER' else 201)
            self.assertEqual(self.request(f'/projects/{self.pid}/member-candidates')[0],200 if role in ('ADMIN','PM') else 403)

    def test_task_status_permissions_for_dev_and_qa(self):
        with transaction(self.url) as db:
            tid=self.create_task(db)
        for role in ('DEV','QA'):
            self.login(role)
            path=f'/projects/{self.pid}/tasks/{tid}'
            self.assertEqual(self.request(path,'PATCH',dict(status='work'))[0],403)
            with transaction(self.url) as db:
                s.assign(db,self.admin,self.pid,tid,dict(user_ids=[self.users[role]['id']]))
            self.assertEqual(self.request(path,'PATCH',dict(status='done'))[0],200)
            self.assertEqual(self.request(path,'PATCH',dict(title='Forbidden'))[0],403)
            self.assertEqual(self.request(path,'PATCH',dict(status='work'))[0],200)
            row=self.request(path)[1]
            self.assertTrue(row['actual_start']); self.assertIsNone(row['actual_end'])

    def test_approval_cycle_and_strict_version(self):
        with transaction(self.url) as db:
            rid=self.create_req(db)
        path=f'/projects/{self.pid}/requirements/{rid}'
        self.login('ANALYST')
        self.assertEqual(self.request(path,'PATCH',dict(status='approved',version=1))[0],403)
        self.login('PM')
        for version in (True,1.0,'1'):
            self.assertEqual(self.request(path,'PATCH',dict(status='approved',version=version))[0],400)
        self.assertEqual(self.request(path,'PATCH',dict(status='approved',version=1))[0],200)
        self.login('ANALYST')
        self.assertEqual(self.request(path,'PATCH',dict(title='Changed',version=2))[0],200)
        self.assertEqual(self.request(path)[1]['status'],'draft')
        self.login('PM')
        self.assertEqual(self.request(path,'PATCH',dict(status='approved',version=3))[0],200)
        self.assertEqual(len(self.request(path+'/versions')[1]),4)

    def test_delete_links_comments_versions_and_assignments(self):
        with transaction(self.url) as db:
            rid=self.create_req(db)
            sid=s.save_entity(db,self.admin,self.pid,'stages',dict(title='Stage',start_date='2026-01-01',end_date='2026-02-01'))
            tid=self.create_task(db,requirement_id=rid,stage_id=sid)
            s.assign(db,self.admin,self.pid,tid,dict(user_ids=[self.users['DEV']['id']]))
            s.comment(db,self.admin,self.pid,dict(entity_type='tasks',entity_id=tid,text='Comment'))
        self.login('PM')
        self.assertEqual(self.request(f'/projects/{self.pid}/tasks/{tid}','DELETE',{})[0],403)
        self.login()
        for entity,eid in (('requirements',rid),('stages',sid)):
            self.assertEqual(self.request(f'/projects/{self.pid}/{entity}/{eid}','DELETE',{})[0],409)
        for entity,eid in (('tasks',tid),('requirements',rid),('stages',sid)):
            self.assertEqual(self.request(f'/projects/{self.pid}/{entity}/{eid}','DELETE',{})[0],200)
        with transaction(self.url) as db:
            for table in ('comments','task_assignments','requirement_versions'):
                self.assertEqual(db.all('SELECT * FROM '+table),[])

    def test_password_change_revokes_all_sessions_and_old_password(self):
        self.login('DEV'); old_cookie=self.cookie
        self.login('DEV')
        self.assertEqual(self.request('/password','POST',dict(current_password=base.PASSWORD,password='New-test-password-2468'))[0],200)
        self.assertEqual(self.request('/me')[0],401)
        self.cookie=old_cookie
        self.assertEqual(self.request('/me')[0],401)
        self.assertEqual(self.request('/login','POST',dict(email='dev@example.local',password=base.PASSWORD))[0],401)

    def test_rate_limit_and_non_ascii_csrf(self):
        self.login()
        self.csrf='é'
        self.assertEqual(self.request('/logout','POST',{})[0],403)
        for _ in range(15):
            self.assertEqual(self.request('/login','POST',dict(email='none@example.local',password='wrong'))[0],401)
        self.assertEqual(self.request('/login','POST',dict(email='none@example.local',password='wrong'))[0],429)


class IntegrityTests(base.Fixture):
    def test_concurrent_version_updates_have_one_winner_and_no_extra_history(self):
        for entity in ('requirements','documents'):
            with self.subTest(entity=entity):
                with transaction(self.url) as db:
                    eid=(self.create_req(db) if entity=='requirements' else
                         s.save_entity(db,self.admin,self.pid,entity,dict(title='Document')))
                barrier=threading.Barrier(2)
                def change(title):
                    barrier.wait(timeout=10)
                    try:
                        with transaction(self.url) as db:
                            s.save_entity(db,self.admin,self.pid,entity,dict(title=title,version=1),eid)
                        return 200
                    except s.Error as error:
                        return error.status
                with ThreadPoolExecutor(max_workers=2) as executor:
                    self.assertEqual(sorted(executor.map(change,('First','Second'))),[200,409])
                with transaction(self.url) as db:
                    self.assertEqual(s.get_entity(db,entity,eid,self.pid)['version'],2)
                    table,fk=('requirement_versions','requirement_id') if entity=='requirements' else ('document_versions','document_id')
                    self.assertEqual(len(db.all(f'SELECT * FROM {table} WHERE {fk}=?',(eid,))),2)
                    self.assertEqual(len(db.all("SELECT * FROM audit_log WHERE entity_type=? AND entity_id=? AND action='update'",(entity,eid))),1)

    def test_snapshot_failure_rolls_back_row_history_and_audit(self):
        with transaction(self.url) as db:
            rid=self.create_req(db)
        with self.assertRaises(RuntimeError):
            with transaction(self.url) as db:
                with patch.object(s,'audit',side_effect=RuntimeError('injected failure')):
                    s.save_entity(db,self.admin,self.pid,'requirements',dict(title='Lost',version=1),rid)
        with transaction(self.url) as db:
            self.assertEqual(s.get_entity(db,'requirements',rid,self.pid)['version'],1)
            self.assertEqual(len(db.all('SELECT * FROM requirement_versions')),1)
            self.assertFalse(db.one("SELECT id FROM audit_log WHERE action='update'"))

    def test_migrate_is_idempotent_and_keeps_data(self):
        with transaction(self.url) as db:
            self.create_req(db)
        migrate(self.url); migrate(self.url)
        with transaction(self.url) as db:
            self.assertEqual(len(db.all('SELECT * FROM requirements')),1)
            self.assertEqual(len(db.all('SELECT * FROM requirement_versions')),1)


if __name__=='__main__':
    unittest.main()
