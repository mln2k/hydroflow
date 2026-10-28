"""Существующие URL проектов и сущностей обслуживаются Flask."""
import csv
import io
import json
from flask import Blueprint, Response, g, request
from .. import services as s
from .common import api_view

bp = Blueprint('projects', __name__, url_prefix='/api/projects')


def project(pid):
    pid = s.number(pid)
    role = s.project_role(g.db, g.user, pid, write=request.method not in ('GET', 'HEAD'))
    return pid, role


@bp.route('', methods=['GET', 'POST'])
@api_view()
def projects():
    if request.method in ('GET', 'HEAD'):
        return s.list_projects(g.db, g.user)
    return {'id': s.save_project(g.db, g.user, g.data)}, 201


@bp.route('/<pid>', methods=['GET', 'PATCH'])
@api_view()
def details(pid):
    pid, _ = project(pid)
    if request.method in ('GET', 'HEAD'):
        return s.project_detail(g.db, g.user, pid)
    return {'id': s.save_project(g.db, g.user, g.data, pid)}


@bp.get('/<pid>/member-candidates')
@api_view()
def candidates(pid):
    _, role = project(pid)
    s.allow(role, ('ADMIN', 'PM'))
    return g.db.all('SELECT id,email,full_name,active FROM users WHERE active=1 ORDER BY full_name')


@bp.route('/<pid>/members', methods=['POST', 'DELETE'])
@api_view()
def members(pid):
    pid, _ = project(pid)
    s.membership(g.db, g.user, pid, g.data, request.method == 'DELETE')
    return {'ok': True}


@bp.post('/<pid>/comments')
@api_view()
def comments(pid):
    pid, _ = project(pid)
    return {'id': s.comment(g.db, g.user, pid, g.data)}, 201


@bp.get('/<pid>/report')
@bp.get('/<pid>/report.csv')
@api_view()
def report(pid):
    pid, _ = project(pid)
    result = s.report(g.db, g.user, pid)
    if not request.path.endswith('.csv'):
        return result
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Задача', 'Статус', 'Приоритет', 'Срок', 'Требование'])
    def cell(value):
        value = str(value) if value is not None else ''
        return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
    for task in result['tasks']:
        writer.writerow([cell(task[key]) for key in
                         ('id', 'title', 'status', 'priority', 'planned_end', 'requirement_id')])
    return Response('\ufeff' + output.getvalue(), content_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="report.csv"'})


@bp.post('/<pid>/<entity>')
@api_view()
def create_entity(pid, entity):
    pid, _ = project(pid)
    return {'id': s.save_entity(g.db, g.user, pid, entity, g.data)}, 201


@bp.route('/<pid>/<entity>/<eid>', methods=['GET', 'PATCH', 'DELETE'])
@api_view()
def entity(pid, entity, eid):
    pid, role = project(pid)
    eid = s.number(eid)
    record = s.get_entity(g.db, entity, eid, pid)
    if request.method in ('GET', 'HEAD'):
        return record
    if request.method == 'PATCH':
        return {'id': s.save_entity(g.db, g.user, pid, entity, g.data, eid)}
    s.allow(role, ('ADMIN',))
    if entity in ('requirements', 'stages'):
        field = 'requirement_id' if entity == 'requirements' else 'stage_id'
        if g.db.one(f'SELECT id FROM tasks WHERE {field}=?', (eid,)):
            raise s.Error('Сначала уберите связи с задачами', 409)
    if entity in ('requirements', 'tasks', 'documents'):
        g.db.execute('DELETE FROM comments WHERE entity_type=? AND entity_id=?', (entity, eid))
    g.db.execute(f'DELETE FROM {entity} WHERE id=?', (eid,))
    s.audit(g.db, g.user, pid, 'delete', entity, eid)
    return {'ok': True}


@bp.get('/<pid>/<entity>/<eid>/versions')
@api_view()
def versions(pid, entity, eid):
    pid, _ = project(pid)
    eid = s.number(eid)
    if entity not in ('requirements', 'documents'):
        raise s.Error('Метод не найден', 404)
    s.get_entity(g.db, entity, eid, pid)
    table, fk = ('requirement_versions', 'requirement_id') if entity == 'requirements' else ('document_versions', 'document_id')
    rows = g.db.all(f'SELECT * FROM {table} WHERE {fk}=? ORDER BY version DESC', (eid,))
    for row in rows:
        row['snapshot'] = json.loads(row['snapshot'])
    return rows


@bp.post('/<pid>/tasks/<eid>/assignments')
@api_view()
def assignments(pid, eid):
    pid, _ = project(pid)
    s.assign(g.db, g.user, pid, s.number(eid), g.data)
    return {'ok': True}
