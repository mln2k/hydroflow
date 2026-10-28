"""Единая HTTP-граница: проверка тела, сессии, CSRF и транзакция."""
from functools import wraps
import hmac
import json
from flask import current_app, g, request
from .. import services as s
from ..db import transaction
from ..security import now, token_hash


def current_user(db):
    token = request.cookies.get('hf_session', '')
    user = db.one('''SELECT u.id,u.email,u.full_name,u.role,u.active,se.csrf,se.token_hash
        FROM sessions se JOIN users u ON u.id=se.user_id
        WHERE se.token_hash=? AND se.expires_at>? AND u.active=1''',
        (token_hash(token), now()))
    if not user:
        raise s.Error('Войдите в систему', 401)
    return user


def json_body():
    if request.mimetype != 'application/json':
        raise s.Error('Ожидается application/json', 415)
    raw = request.get_data()
    if not raw:
        raise s.Error('Недопустимый размер запроса', 413)
    def invalid_constant(value):
        raise ValueError(value)
    try:
        data = json.loads(raw, parse_constant=invalid_constant)
        json.dumps(data, ensure_ascii=False).encode('utf-8')
    except (ValueError, UnicodeError, RecursionError):
        raise s.Error('Некорректный JSON') from None
    if not isinstance(data, dict):
        raise s.Error('Ожидается JSON-объект')
    return data


def api_view(*, public=False):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            writing = request.method not in ('GET', 'HEAD', 'OPTIONS')
            if writing:
                origin = request.headers.get('Origin')
                expected = current_app.config['PUBLIC_ORIGIN'] or request.host_url.rstrip('/')
                if origin and origin != expected:
                    raise s.Error('Недопустимый источник запроса', 403)
            g.data = json_body() if writing else {}
            with transaction(current_app.config['DATABASE_URL']) as db:
                g.db = db
                if not public:
                    g.user = current_user(db)
                    if writing and not hmac.compare_digest(
                        request.headers.get('X-CSRF-Token', '').encode(), g.user['csrf'].encode()
                    ):
                        raise s.Error('Ошибка CSRF. Обновите страницу', 403)
                result = view(*args, **kwargs)
            # Flask получает результат только после успешного commit.
            return result
        return wrapped
    return decorate


def session_cookie(response, token='', clear=False):
    response.set_cookie('hf_session', token, max_age=0 if clear else 43200,
                        httponly=True, secure=current_app.config['COOKIE_SECURE'],
                        samesite='Strict', path='/')
    return response


def public_user(user):
    return {key: user[key] for key in ('id', 'email', 'full_name', 'role')}
