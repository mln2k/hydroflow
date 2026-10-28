"""CLI на одноразовой SQLite БД: init/demo, backup и восстановление."""
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class OperationsTests(unittest.TestCase):
    def test_demo_generator_all_roles_and_no_overwrite(self):
        from hydroflow.server import create_app
        accounts = self.root/'accounts.txt'
        root = Path(__file__).resolve().parents[1]
        command = [sys.executable, str(root/'scripts/create_demo.py'), '--database', str(self.source), '--accounts', str(accounts)]
        result = subprocess.run(command,cwd=root,capture_output=True,env=self.env,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        client = create_app({'DATABASE_URL':'sqlite:///'+str(self.source)}).test_client()
        roles = []
        for line in accounts.read_text(encoding='utf-8').splitlines():
            if '  пароль: ' not in line:
                continue
            identity,password = line.split('  пароль: ',1)
            role,email = identity.split(': ',1)
            response = client.post('/api/login',json={'email':email,'password':password})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['user']['role'],role)
            roles.append(role)
        self.assertEqual(set(roles),{'ADMIN','PM','ANALYST','DEV','QA','VIEWER'})
        original = accounts.read_bytes()
        second = subprocess.run(command,cwd=root,capture_output=True,env=self.env,timeout=30)
        self.assertNotEqual(second.returncode,0)
        self.assertEqual(accounts.read_bytes(),original)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'source.db'
        self.env={**os.environ,'DATABASE_URL':'sqlite:///'+str(self.source),
                  'HYDROFLOW_ADMIN_PASSWORD':'Operations-test-only-2468','PYTHONIOENCODING':'utf-8'}

    def cli(self,*args,success=True):
        result=subprocess.run([sys.executable,'-m','hydroflow',*args],env=self.env,
                              capture_output=True,text=True,encoding='utf-8',timeout=30)
        if success:self.assertEqual(result.returncode,0,result.stderr)
        else:self.assertNotEqual(result.returncode,0)
        return result

    def test_missing_backup_source_does_not_create_empty_database(self):
        target=self.root/'backup.db'
        self.cli('backup',str(target),success=False)
        self.assertFalse(target.exists());self.assertFalse(self.source.exists())

    def test_init_demo_backup_restore_preserves_all_tables_and_attachments(self):
        self.cli('init');self.cli('init');self.cli('demo')
        self.cli('demo',success=False)
        with closing(sqlite3.connect(self.source)) as conn, conn:
            # Включаем вложение в проверку переноса, включая историю документа.
            conn.execute("UPDATE documents SET filename='test.txt',file_base64='eA=='")
            conn.execute("UPDATE document_versions SET snapshot=json_set(snapshot,'$.filename','test.txt','$.file_base64','eA==')")
        target=self.root/'restore.db';self.cli('backup',str(target))
        with closing(sqlite3.connect(self.source)) as source,closing(sqlite3.connect(target)) as restored:
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(restored.execute('PRAGMA foreign_key_check').fetchall(),[])
            for (table,) in source.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                self.assertEqual(source.execute('SELECT * FROM '+table).fetchall(),restored.execute('SELECT * FROM '+table).fetchall(),table)
        self.env['DATABASE_URL']='sqlite:///'+str(target)
        self.cli('init')
        before=target.read_bytes();self.cli('backup',str(target),success=False)
        self.assertEqual(target.read_bytes(),before)


if __name__=='__main__':unittest.main()
