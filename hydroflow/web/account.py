"""Личный кабинет и внутренняя обратная связь."""
from flask import Blueprint, g, request
from .. import services as s
from .common import api_view, public_user

bp = Blueprint('account', __name__, url_prefix='/api')


@bp.route('/account', methods=['GET', 'PATCH'])
@api_view()
def account():
    if request.method == 'PATCH':
        if set(g.data) != {'full_name'}:
            raise s.Error('В профиле можно изменить только имя', 403)
        name = s.text(g.data, 'full_name', limit=150)
        s.update(g.db, 'users', g.user['id'], {'full_name': name})
        s.audit(g.db, g.user, None, 'profile', 'users', g.user['id'])
        return {'ok': True}
    tasks = g.db.all('''SELECT t.*,p.name AS project_name FROM tasks t
        JOIN projects p ON p.id=t.project_id JOIN task_assignments a ON a.task_id=t.id
        JOIN project_members m ON m.project_id=p.id AND m.user_id=a.user_id
        WHERE a.user_id=? ORDER BY t.planned_end,t.id''', (g.user['id'],))
    return {'user': public_user(g.user), 'projects': s.list_projects(g.db, g.user), 'tasks': tasks}


@bp.route('/feedback', methods=['GET', 'POST'])
@api_view()
def feedback():
    if request.method == 'POST':
        fid, created = s.create_feedback(g.db, g.user, g.data)
        return {'id': fid, 'created': created}, 201 if created else 200
    return g.db.all('SELECT * FROM feedback WHERE user_id=? ORDER BY id DESC', (g.user['id'],))


@bp.get('/feedback/<fid>')
@api_view()
def feedback_detail(fid):
    return s.get_feedback(g.db, g.user, s.number(fid))


@bp.get('/admin/feedback')
@api_view()
def admin_feedback():
    s.allow(g.user['role'], ('ADMIN',))
    return g.db.all('''SELECT f.*,u.full_name AS author,u.email FROM feedback f
        JOIN users u ON u.id=f.user_id ORDER BY f.id DESC''')


@bp.patch('/admin/feedback/<fid>')
@api_view()
def answer_feedback(fid):
    s.answer_feedback(g.db, g.user, s.number(fid), g.data)
    return {'ok': True}
