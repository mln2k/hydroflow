"""Один интерфейс транзакций для SQLite и PostgreSQL."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Conflict(Exception):
    """Нарушение ограничения БД; детали SQL не передаются клиенту."""


class DB:
    def __init__(self, url=None):
        self.url = url or os.getenv("DATABASE_URL", "sqlite:///data/hydroflow.db")
        self.pg = self.url.startswith(("postgres://", "postgresql://"))
        if self.pg:
            import psycopg
            from psycopg.rows import dict_row
            self.conn = psycopg.connect(self.url, row_factory=dict_row)
        else:
            if not self.url.startswith("sqlite:///"):
                raise ValueError("DATABASE_URL: ожидается sqlite:/// или postgresql://")
            path = self.url.removeprefix("sqlite:///")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(path, timeout=20)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("BEGIN IMMEDIATE")

    def execute(self, sql, params=()):
        return self.conn.execute(sql.replace("?", "%s") if self.pg else sql, params)

    def locked_one(self, sql, params=(), shared=False):
        suffix = (' FOR SHARE' if shared else ' FOR UPDATE') if self.pg else ''
        return self.one(sql + suffix, params)

    def all(self, sql, params=()):
        return [dict(r) for r in self.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        row = self.execute(sql, params).fetchone()
        return dict(row) if row else None

    def insert(self, table, values):
        fields = list(values)
        sql = f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)}) RETURNING id"
        return self.one(sql, tuple(values.values()))["id"]


@contextmanager
def transaction(url=None):
    db = DB(url)
    try:
        yield db
        db.conn.commit()
    except BaseException as error:
        db.conn.rollback()
        integrity_error = sqlite3.IntegrityError
        if db.pg:
            import psycopg
            integrity_error = psycopg.IntegrityError
        if isinstance(error, integrity_error):
            raise Conflict('Конфликт данных или связей. Обновите страницу') from error
        raise
    finally:
        db.conn.close()


SCHEMA = [
"""CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('ADMIN','PM','ANALYST','DEV','QA','VIEWER')),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_at TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS sessions (
 id INTEGER PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 csrf TEXT NOT NULL, expires_at TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS projects (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', customer TEXT NOT NULL DEFAULT '',
 manager_id INTEGER NOT NULL REFERENCES users(id), start_date TEXT NOT NULL, end_date TEXT,
 status TEXT NOT NULL CHECK(status IN ('planned','active','closed')), created_at TEXT NOT NULL,
 CHECK(end_date IS NULL OR end_date >= start_date))""",
"""CREATE TABLE IF NOT EXISTS project_members (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES users(id), role TEXT NOT NULL CHECK(role IN ('PM','ANALYST','DEV','QA','VIEWER')),
 UNIQUE(project_id,user_id))""",
"""CREATE TABLE IF NOT EXISTS stages (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 title TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('planned','active','done')), CHECK(end_date >= start_date))""",
"""CREATE TABLE IF NOT EXISTS requirements (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 code TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL, priority TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('draft','review','approved','rejected')),
 version INTEGER NOT NULL DEFAULT 1, created_by INTEGER NOT NULL REFERENCES users(id),
 updated_at TEXT NOT NULL, UNIQUE(project_id,code))""",
"""CREATE TABLE IF NOT EXISTS requirement_versions (
 id INTEGER PRIMARY KEY, requirement_id INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, snapshot TEXT NOT NULL, reason TEXT NOT NULL,
 changed_by INTEGER NOT NULL REFERENCES users(id), changed_at TEXT NOT NULL, UNIQUE(requirement_id,version))""",
"""CREATE TABLE IF NOT EXISTS tasks (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 requirement_id INTEGER REFERENCES requirements(id), stage_id INTEGER REFERENCES stages(id),
 title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', type TEXT NOT NULL CHECK(type IN ('analysis','dev','test','doc')),
 priority TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('new','work','review','done')),
 planned_start TEXT, planned_end TEXT, actual_start TEXT, actual_end TEXT,
 created_by INTEGER NOT NULL REFERENCES users(id), updated_at TEXT NOT NULL,
 CHECK(planned_start IS NULL OR planned_end IS NULL OR planned_end >= planned_start))""",
"""CREATE TABLE IF NOT EXISTS task_assignments (
 id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES users(id), assigned_by INTEGER NOT NULL REFERENCES users(id),
 assigned_at TEXT NOT NULL, UNIQUE(task_id,user_id))""",
"""CREATE TABLE IF NOT EXISTS documents (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 title TEXT NOT NULL, doc_type TEXT NOT NULL, content TEXT NOT NULL, filename TEXT NOT NULL DEFAULT '',
 file_base64 TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
 created_by INTEGER NOT NULL REFERENCES users(id), updated_at TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS document_versions (
 id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, snapshot TEXT NOT NULL, changed_by INTEGER NOT NULL REFERENCES users(id),
 changed_at TEXT NOT NULL, UNIQUE(document_id,version))""",
"""CREATE TABLE IF NOT EXISTS comments (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 entity_type TEXT NOT NULL CHECK(entity_type IN ('requirements','tasks','documents')),
 entity_id INTEGER NOT NULL, author_id INTEGER NOT NULL REFERENCES users(id), text TEXT NOT NULL, created_at TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
 actor_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL, entity_type TEXT NOT NULL,
 entity_id INTEGER NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL)""",
"CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id,status)",
"CREATE INDEX IF NOT EXISTS idx_requirements_project ON requirements(project_id)",
"CREATE INDEX IF NOT EXISTS idx_comments_entity ON comments(entity_type,entity_id)",
"CREATE INDEX IF NOT EXISTS idx_audit_project ON audit_log(project_id,id)",
"CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at)",
]


def migrate(url=None):
    with transaction(url) as db:
        db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)")
        if db.one("SELECT version FROM schema_migrations WHERE version=1"):
            return
        for statement in SCHEMA:
            if db.pg:
                statement = statement.replace("id INTEGER PRIMARY KEY", "id BIGSERIAL PRIMARY KEY")
                # Внешние ключи должны соответствовать BIGSERIAL.
                for field in ('user_id','manager_id','project_id','requirement_id','stage_id','created_by',
                              'changed_by','task_id','assigned_by','document_id','author_id','actor_id','entity_id'):
                    statement = statement.replace(f"{field} INTEGER", f"{field} BIGINT")
            db.execute(statement)
        db.execute("INSERT INTO schema_migrations(version) VALUES (1)")
