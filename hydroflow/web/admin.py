"""Административные операции и совместимый каталог пользователей."""
from flask import Blueprint, g, request
from .. import services as s
from .common import api_view

bp = Blueprint('admin', __name__, url_prefix='/api')


@bp.route('/users', methods=['GET', 'POST'])
@api_view()
def users():
    if request.method in ('GET', 'HEAD'):
        s.allow(g.user['role'], ('ADMIN', 'PM'))
        return g.db.all('SELECT id,email,full_name,role,active FROM users ORDER BY full_name')
    return {'id': s.create_user(g.db, g.user, g.data)}, 201


@bp.patch('/users/<uid>')
@api_view()
def update_user(uid):
    s.manage_user(g.db, g.user, s.number(uid), g.data)
    return {'ok': True}
