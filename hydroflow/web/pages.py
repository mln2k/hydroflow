"""Разрешённые HTML-страницы с проверкой сессии и доступа на сервере."""
from flask import Blueprint, current_app, redirect, render_template, request
from .. import services as s
from ..db import transaction
from .common import current_user

bp = Blueprint('pages', __name__)
PROJECT_PAGES = {
    'overview': 'Обзор', 'requirements': 'Требования', 'tasks': 'Задачи',
    'stages': 'Этапы', 'documents': 'Документы', 'members': 'Команда',
    'reports': 'Отчёты', 'activity': 'История',
}
GLOBAL_PAGES = {
    'projects': 'Проекты', 'account': 'Личный кабинет', 'feedback': 'Обратная связь',
    'help': 'Справка', 'admin/users': 'Команда и доступ', 'admin/feedback': 'Обращения пользователей',
}


def page(name, pid=None):
    try:
        with transaction(current_app.config['DATABASE_URL']) as db:
            user = current_user(db)
            if name.startswith('admin/'):
                s.allow(user['role'], ('ADMIN',))
            if pid is not None:
                s.project_role(db, user, s.number(pid))
            title = PROJECT_PAGES[name] if pid is not None else GLOBAL_PAGES[name]
    except s.Error as error:
        if error.status == 401:
            return redirect('/login?next=' + request.path)
        raise
    return render_template('app.html', title=title, page=name)


@bp.get('/')
def index():
    return redirect('/projects')


@bp.get('/login')
def login():
    return render_template('app.html', title='Вход в систему', page='login')


@bp.get('/projects/<pid>/<section>')
def project_page(pid, section):
    if section not in PROJECT_PAGES:
        raise s.Error('Страница не найдена', 404)
    return page(section, pid)


@bp.get('/projects/<pid>')
def project_redirect(pid):
    return redirect(f'/projects/{s.number(pid)}/overview')


@bp.get('/projects')
@bp.get('/account')
@bp.get('/feedback')
@bp.get('/help')
@bp.get('/admin/users')
@bp.get('/admin/feedback')
def global_page():
    return page(request.path.lstrip('/'))
