"""Проверки доступа и транзакционные операции предметной области."""
import base64
import json
import re
from datetime import date, datetime, timedelta, timezone
from .security import now, hash_password

ROLES = ('ADMIN', 'PM', 'ANALYST', 'DEV', 'QA', 'VIEWER')
PRIORITIES = ('low', 'medium', 'high', 'critical')
ENTITIES = ('requirements', 'tasks', 'documents', 'stages')


class Error(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def text(data, field, default=None, limit=200):
    value = data.get(field, default)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise Error(f"Поле «{field}»: требуется текст длиной 1–{limit} символов")
    return value.strip()


def optional(data, field, default='', limit=20000):
    value = data.get(field, default)
    if not isinstance(value, str) or len(value) > limit:
        raise Error(f"Некорректное поле «{field}»")
    return value.strip()


def choice(data, field, choices, default=None):
    value = data.get(field, default)
    if value not in choices:
        raise Error(f"Недопустимое значение «{field}»")
    return value


def number(value):
    if isinstance(value, bool):
        raise Error("Некорректный идентификатор")
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise Error("Некорректный идентификатор") from None
    if str(result) != str(value) or not 1 <= result <= 9223372036854775807:
        raise Error("Некорректный идентификатор")
    return result


def dates(data, start, end, required=False):
    values = []
    for key in (start, end):
        value = data.get(key) or None
        try:
            if value:
                value = date.fromisoformat(value).isoformat()
            elif required:
                raise ValueError()
        except (TypeError, ValueError):
            raise Error(f"Поле «{key}»: укажите дату ГГГГ-ММ-ДД") from None
        values.append(value)
    if all(values) and values[0] > values[1]:
        raise Error("Дата окончания раньше даты начала")
    return dict(zip((start, end), values))


def audit(db, user, project, action, entity, entity_id, detail=''):
    db.insert('audit_log', dict(project_id=project, actor_id=user['id'], action=action,
                               entity_type=entity, entity_id=entity_id, detail=detail, created_at=now()))


def project_role(db, user, pid, write=False):
    # Общая блокировка проекта сериализует проверки связей и запись в PostgreSQL.
    # SQLite уже сериализует транзакции через BEGIN IMMEDIATE.
    read = db.locked_one if write else db.one
    if not read('SELECT id FROM projects WHERE id=?', (pid,)):
        raise Error("Проект не найден", 404)
    if user['role'] == 'ADMIN':
        return 'ADMIN'
    member = db.one('SELECT role FROM project_members WHERE project_id=? AND user_id=?', (pid, user['id']))
    if not member:
        raise Error("Нет доступа к проекту", 403)
    return member['role']


def allow(role, roles):
    if role not in roles:
        raise Error("Недостаточно прав для этого действия", 403)


def create_user(db, user, data):
    allow(user['role'], ('ADMIN',))
    email = text(data, 'email', limit=120).lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise Error("Некорректный email")
    if db.one('SELECT id FROM users WHERE email=?', (email,)):
        raise Error("Email уже зарегистрирован", 409)
    try:
        password = hash_password(data.get('password'))
    except ValueError as e:
        raise Error(str(e)) from e
    uid = db.insert('users', dict(email=email, full_name=text(data, 'full_name', limit=150),
                    role=choice(data, 'role', ROLES), password_hash=password, active=1, created_at=now()))
    audit(db, {**user, 'id':uid} if user.get('bootstrap') else user, None, 'create', 'users', uid)
    return uid


def list_projects(db, user):
    sql = """SELECT p.*, u.full_name AS manager_name,
        (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id) AS task_count,
        (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id AND t.status='done') AS done_count
        FROM projects p JOIN users u ON u.id=p.manager_id"""
    if user['role'] == 'ADMIN':
        return db.all(sql + ' ORDER BY p.id DESC')
    return db.all(sql + ' WHERE p.id IN (SELECT project_id FROM project_members WHERE user_id=?) ORDER BY p.id DESC', (user['id'],))


def save_project(db, user, data, pid=None):
    if pid:
        allow(project_role(db, user, pid, write=True), ('ADMIN', 'PM'))
        old = db.one('SELECT * FROM projects WHERE id=?', (pid,))
        data = {**old, **data}
    else:
        allow(user['role'], ('ADMIN', 'PM'))
    values = dict(name=text(data, 'name'), description=optional(data, 'description'),
                  customer=optional(data, 'customer', limit=150),
                  status=choice(data, 'status', ('planned','active','closed'), 'planned'))
    values.update(dates(data, 'start_date', 'end_date'))
    if not values['start_date']:
        raise Error("Укажите дату начала проекта")
    if pid:
        update(db, 'projects', pid, values)
    else:
        values.update(manager_id=user['id'], created_at=now())
        pid = db.insert('projects', values)
        db.insert('project_members', dict(project_id=pid, user_id=user['id'], role='PM'))
    audit(db, user, pid, 'save', 'projects', pid)
    return pid


def update(db, table, eid, values):
    db.execute(f"UPDATE {table} SET " + ','.join(f'{k}=?' for k in values) + ' WHERE id=?', (*values.values(), eid))


def membership(db, user, pid, data, remove=False):
    allow(project_role(db, user, pid, write=True), ('ADMIN','PM'))
    uid = number(data.get('user_id'))
    account = db.locked_one('SELECT id,active FROM users WHERE id=?', (uid,), shared=True)
    if not account or (not remove and not account['active']):
        raise Error("Активный пользователь не найден")
    manager = db.one('SELECT manager_id FROM projects WHERE id=?', (pid,))['manager_id']
    if remove:
        if uid == manager:
            raise Error("Нельзя удалить руководителя проекта")
        if db.one('SELECT a.id FROM task_assignments a JOIN tasks t ON t.id=a.task_id WHERE t.project_id=? AND a.user_id=?', (pid, uid)):
            raise Error("Сначала снимите назначения задач этого участника", 409)
        db.execute('DELETE FROM project_members WHERE project_id=? AND user_id=?', (pid, uid))
    else:
        role = choice(data, 'role', ROLES[1:])
        if uid == manager and role != 'PM':
            raise Error("Руководитель проекта должен сохранять роль PM")
        if role == 'VIEWER' and db.one('SELECT a.id FROM task_assignments a JOIN tasks t ON t.id=a.task_id WHERE t.project_id=? AND a.user_id=?', (pid, uid)):
            raise Error("Сначала снимите назначения задач этого участника", 409)
        db.execute('''INSERT INTO project_members(project_id,user_id,role) VALUES (?,?,?)
            ON CONFLICT(project_id,user_id) DO UPDATE SET role=excluded.role''', (pid,uid,role))
    audit(db, user, pid, 'remove_member' if remove else 'set_member', 'users', uid)


def get_entity(db, entity, eid, pid):
    if entity not in ENTITIES:
        raise Error("Раздел не найден", 404)
    row = db.one(f'SELECT * FROM {entity} WHERE id=? AND project_id=?', (eid, pid))
    if not row:
        raise Error("Запись не найдена", 404)
    return row


def snapshot(db, user, entity, eid, row, reason=''):
    table, fk = ('requirement_versions', 'requirement_id') if entity == 'requirements' else ('document_versions', 'document_id')
    values = {fk:eid, 'version':row['version'], 'snapshot':json.dumps(row, ensure_ascii=False),
              'changed_by':user['id'], 'changed_at':now()}
    if entity == 'requirements':
        values['reason'] = reason
    db.insert(table, values)


def save_entity(db, user, pid, entity, data, eid=None):
    role = project_role(db, user, pid, write=True)
    allowed = {'requirements':('ADMIN','PM','ANALYST'), 'tasks':('ADMIN','PM','ANALYST','DEV','QA'),
               'documents':('ADMIN','PM','ANALYST','DEV'), 'stages':('ADMIN','PM')}
    if entity not in allowed:
        raise Error("Раздел не найден", 404)
    allow(role, allowed[entity])
    old = get_entity(db, entity, eid, pid) if eid else None
    incoming = data
    data = {**(old or {}), **data}
    if entity == 'tasks' and role in ('DEV','QA'):
        if old:
            if not db.one('SELECT id FROM task_assignments WHERE task_id=? AND user_id=?', (eid,user['id'])):
                raise Error("Изменять можно только назначенные вам задачи", 403)
            if set(incoming) - {'status'}:
                raise Error("Исполнитель может менять только статус задачи", 403)
        elif data.get('type') != ('dev' if role == 'DEV' else 'test'):
            raise Error("Вы можете создавать задачи своего направления", 403)
    if entity == 'requirements':
        values = dict(code=text(data,'code',limit=30), title=text(data,'title'), description=text(data,'description',limit=20000),
                      priority=choice(data,'priority',PRIORITIES,'medium'),
                      status=choice(data,'status',('draft','review','approved','rejected'),'draft'))
        if values['status'] in ('approved','rejected') and (not old or old['status'] != values['status']):
            allow(role, ('ADMIN','PM'))
        if old and role == 'ANALYST' and old['status'] in ('approved','rejected'):
            values['status'] = 'draft'
        duplicate = db.one('SELECT id FROM requirements WHERE project_id=? AND code=?', (pid,values['code']))
        if duplicate and duplicate['id'] != eid:
            raise Error("Код требования уже используется", 409)
    elif entity == 'tasks':
        values = dict(title=text(data,'title'), description=optional(data,'description'),
            type=choice(data,'type',('analysis','dev','test','doc'),'dev'), priority=choice(data,'priority',PRIORITIES,'medium'),
            status=choice(data,'status',('new','work','review','done'),'new'))
        values.update(dates(data, 'planned_start', 'planned_end'))
        for field, table in (('requirement_id','requirements'), ('stage_id','stages')):
            values[field] = number(data[field]) if data.get(field) else None
            if values[field]:
                get_entity(db, table, values[field], pid)
        values['actual_start'] = (old or {}).get('actual_start')
        if values['status'] != 'new' and not values['actual_start']:
            values['actual_start'] = now()
        values['actual_end'] = (old or {}).get('actual_end') if values['status'] == 'done' else None
        if values['status'] == 'done' and not values['actual_end']:
            values['actual_end'] = now()
    elif entity == 'documents':
        values = dict(title=text(data,'title'), content=optional(data,'content'),
                      doc_type=choice(data,'doc_type',('TZ','SRS','Protocol','Report','Other'),'Other'),
                      filename=optional(data,'filename',limit=180), file_base64=data.get('file_base64',''))
        if not isinstance(values['file_base64'], str) or len(values['file_base64']) > 7_000_000:
            raise Error("Файл превышает 5 МиБ")
        try:
            raw = base64.b64decode(values['file_base64'], validate=True)
        except ValueError:
            raise Error("Некорректное содержимое файла") from None
        if len(raw) > 5*1024*1024:
            raise Error("Файл превышает 5 МиБ")
        if bool(raw) != bool(values['filename']):
            raise Error("Имя файла и содержимое должны быть указаны вместе")
        if '/' in values['filename'] or '\\' in values['filename'] or any(ord(c)<32 for c in values['filename']):
            raise Error("Некорректное имя файла")
    else:
        values = dict(title=text(data,'title'), status=choice(data,'status',('planned','active','done'),'planned'))
        values.update(dates(data,'start_date','end_date',True))
    if entity != 'stages':
        values['updated_at'] = now()
    if entity in ('requirements','documents'):
        if old:
            if type(incoming.get('version')) is not int or incoming['version'] < 1:
                raise Error("version: требуется положительное целое число")
            if incoming.get('version') != old['version']:
                raise Error("Запись изменена другим пользователем. Обновите страницу",409)
            # Условный UPDATE защищает от одновременных правок и в PostgreSQL.
            changed = db.execute(f'UPDATE {entity} SET version=version+1 WHERE id=? AND version=?', (eid,old['version'])).rowcount
            if not changed:
                raise Error("Конфликт версий. Обновите страницу",409)
            values['version'] = old['version']+1
        else:
            values['version'] = 1
    if old:
        update(db, entity, eid, values)
    else:
        values['project_id'] = pid
        if entity != 'stages':
            values['created_by'] = user['id']
        eid = db.insert(entity, values)
    if entity in ('requirements','documents'):
        snapshot(db, user, entity, eid, get_entity(db,entity,eid,pid), optional(incoming,'reason',limit=2000))
    if entity == 'tasks' and not old and role in ('DEV','QA'):
        db.insert('task_assignments', dict(task_id=eid,user_id=user['id'],assigned_by=user['id'],assigned_at=now()))
    audit(db,user,pid,'update' if old else 'create',entity,eid)
    return eid


def assign(db, user, pid, eid, data):
    allow(project_role(db,user,pid,write=True),('ADMIN','PM'))
    get_entity(db,'tasks',eid,pid)
    ids = data.get('user_ids')
    if not isinstance(ids,list) or len(ids)>50:
        raise Error("Укажите список исполнителей")
    ids = sorted(set(number(i) for i in ids))
    for uid in ids:
        # Блокировка учётной записи согласует назначение с блокировкой пользователя.
        db.locked_one('SELECT id FROM users WHERE id=?', (uid,), shared=True)
        if not db.one('SELECT m.id FROM project_members m JOIN users u ON u.id=m.user_id WHERE m.project_id=? AND m.user_id=? AND u.active=1 AND m.role<>?',(pid,uid,'VIEWER')):
            raise Error("Исполнитель должен быть активным участником проекта с правом редактирования")
    db.execute('DELETE FROM task_assignments WHERE task_id=?',(eid,))
    for uid in ids:
        db.insert('task_assignments',dict(task_id=eid,user_id=uid,assigned_by=user['id'],assigned_at=now()))
    audit(db,user,pid,'assign','tasks',eid,json.dumps(ids))


def project_detail(db, user, pid):
    role = project_role(db,user,pid)
    result = db.one('SELECT * FROM projects WHERE id=?',(pid,))
    result['my_role'] = role
    result['members'] = db.all('''SELECT m.user_id,m.role,u.full_name,u.email,u.active FROM project_members m
        JOIN users u ON u.id=m.user_id WHERE m.project_id=? ORDER BY u.full_name''',(pid,))
    for entity in ENTITIES:
        fields = '*' if entity != 'documents' else 'id,project_id,title,doc_type,version,filename,created_by,updated_at'
        result[entity] = db.all(f'SELECT {fields} FROM {entity} WHERE project_id=? ORDER BY id',(pid,))
    assignments = db.all('''SELECT a.task_id,a.user_id FROM task_assignments a JOIN tasks t ON t.id=a.task_id
        WHERE t.project_id=?''',(pid,))
    for task in result['tasks']:
        task['assignee_ids'] = [a['user_id'] for a in assignments if a['task_id']==task['id']]
    result['comments'] = db.all('''SELECT c.*,u.full_name AS author FROM comments c JOIN users u ON u.id=c.author_id
        WHERE c.project_id=? ORDER BY c.id''',(pid,))
    result['audit'] = db.all('''SELECT a.*,u.full_name AS actor FROM audit_log a JOIN users u ON u.id=a.actor_id
        WHERE a.project_id=? ORDER BY a.id DESC LIMIT 100''',(pid,))
    return result


def comment(db,user,pid,data):
    role = project_role(db,user,pid,write=True)
    allow(role,ROLES[:-1])
    entity = choice(data,'entity_type',('requirements','tasks','documents'))
    eid = number(data.get('entity_id'))
    get_entity(db,entity,eid,pid)
    cid = db.insert('comments',dict(project_id=pid,entity_type=entity,entity_id=eid,author_id=user['id'],
                                   text=text(data,'text',limit=5000),created_at=now()))
    audit(db,user,pid,'comment',entity,eid)
    return cid


def report(db,user,pid):
    p = project_detail(db,user,pid)
    tasks = p['tasks']
    total = len(tasks)
    today = date.today().isoformat()
    return dict(project=p['name'],generated_at=now(),total_tasks=total,
        done=sum(t['status']=='done' for t in tasks),
        overdue=sum(bool(t['planned_end'] and t['planned_end']<today and t['status']!='done') for t in tasks),
        progress=round(100*sum(t['status']=='done' for t in tasks)/total) if total else 0,
        by_status={s:sum(t['status']==s for t in tasks) for s in ('new','work','review','done')},
        requirements=len(p['requirements']),approved_requirements=sum(r['status']=='approved' for r in p['requirements']),
        documents=len(p['documents']),stages=p['stages'],tasks=tasks,
        impact=[dict(requirement=r['code'],version=r['version'],status=r['status'],
                     task_ids=[t['id'] for t in tasks if t['requirement_id']==r['id']],
                     completed_task_ids=[t['id'] for t in tasks if t['requirement_id']==r['id'] and t['status']=='done'])
                for r in p['requirements'] if r['version']>1])


def manage_user(db, user, uid, data):
    allow(user['role'], ('ADMIN',))
    # Общая строка блокировки исключает одновременное отключение двух последних ADMIN.
    db.locked_one("SELECT name FROM system_locks WHERE name='administrators'")
    actor = db.one('SELECT role,active FROM users WHERE id=?', (user['id'],))
    if not actor or not actor['active'] or actor['role'] != 'ADMIN':
        raise Error('Недостаточно прав для этого действия', 403)
    if uid == user['id']:
        raise Error('Изменение собственной роли или активности запрещено')
    account = db.locked_one('SELECT * FROM users WHERE id=?', (uid,))
    if not account:
        raise Error('Пользователь не найден', 404)
    if set(data) - {'role', 'active'}:
        raise Error('Недопустимые поля пользователя')
    values = {}
    if 'active' in data:
        if type(data['active']) is not bool:
            raise Error('active: ожидается boolean')
        values['active'] = int(data['active'])
    if 'role' in data:
        values['role'] = choice(data, 'role', ROLES)
    if not values:
        raise Error('Нет изменений')
    if account['role'] == 'ADMIN' and account['active'] and (
        values.get('active', 1) == 0 or values.get('role', 'ADMIN') != 'ADMIN'
    ):
        remaining = db.one("SELECT COUNT(*) AS n FROM users WHERE role='ADMIN' AND active=1 AND id<>?", (uid,))
        if not remaining['n']:
            raise Error('Нельзя отключить последнего активного администратора', 409)
    update(db, 'users', uid, values)
    db.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
    audit(db, user, None, 'update', 'users', uid, json.dumps(values))


def create_feedback(db, user, data):
    subject = text(data, 'subject', limit=160)
    category = choice(data, 'category', ('question', 'bug', 'suggestion'))
    body = text(data, 'body', limit=10000)
    key = text(data, 'request_key', limit=80)
    if not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', key):
        raise Error('Некорректный ключ повторной отправки')
    db.locked_one('SELECT id FROM users WHERE id=?', (user['id'],))
    existing = db.one('SELECT * FROM feedback WHERE user_id=? AND request_key=?', (user['id'], key))
    if existing:
        if (existing['subject'], existing['category'], existing['body']) != (subject, category, body):
            raise Error('Ключ отправки уже использован для другого обращения', 409)
        return existing['id'], False
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec='seconds')
    count = db.one('SELECT COUNT(*) AS n FROM feedback WHERE user_id=? AND created_at>=?', (user['id'], since))['n']
    if count >= 5:
        raise Error('Не более пяти новых обращений за час. Повторите позже', 429)
    fid = db.insert('feedback', dict(user_id=user['id'], subject=subject, category=category,
        body=body, status='new', reply='', answered_by=None, request_key=key, version=1,
        created_at=now(), updated_at=now()))
    audit(db, user, None, 'create', 'feedback', fid)
    return fid, True


def get_feedback(db, user, fid):
    row = db.one('SELECT * FROM feedback WHERE id=?', (fid,))
    if not row or (row['user_id'] != user['id'] and user['role'] != 'ADMIN'):
        raise Error('Обращение не найдено', 404)
    return row


def answer_feedback(db, user, fid, data):
    allow(user['role'], ('ADMIN',))
    old = get_feedback(db, user, fid)
    if set(data) - {'status', 'reply', 'version'}:
        raise Error('Недопустимые поля обращения')
    if type(data.get('version')) is not int:
        raise Error('version: требуется целое число')
    status = choice(data, 'status', ('new', 'work', 'closed'), old['status'])
    reply = optional(data, 'reply', old['reply'], limit=10000)
    changed = db.execute('''UPDATE feedback SET status=?,reply=?,answered_by=?,
        updated_at=?,version=version+1 WHERE id=? AND version=?''',
        (status, reply, user['id'], now(), fid, data['version'])).rowcount
    if not changed:
        raise Error('Обращение уже изменено. Обновите страницу', 409)
    audit(db, user, None, 'answer', 'feedback', fid)
