"""Серверные сессии, вход, выход и смена пароля."""
import secrets
import threading
import time
from flask import Blueprint, g, jsonify, request
from .. import services as s
from ..security import hash_password, verify_password, token_hash, now, future
from .common import api_view, session_cookie, public_user

bp = Blueprint('auth', __name__, url_prefix='/api')
ATTEMPTS = {}
LOGIN_LOCK = threading.Lock()
DUMMY_PASSWORD = hash_password('dummy-password-for-timing-only')


@bp.post('/login')
@api_view(public=True)
def login():
    email = g.data.get('email', '')
    if not isinstance(email, str) or len(email) > 120:
        raise s.Error('Неверный email или пароль', 401)
    key = request.remote_addr
    with LOGIN_LOCK:
        current = time.monotonic()
        for ip, attempts in list(ATTEMPTS.items()):
            recent = [stamp for stamp in attempts if current - stamp < 900]
            if recent:
                ATTEMPTS[ip] = recent
            else:
                del ATTEMPTS[ip]
        bucket = ATTEMPTS.setdefault(key, [])
        if len(bucket) >= 15:
            raise s.Error('Слишком много попыток. Повторите через 15 минут', 429)
        bucket.append(current)
    user = g.db.locked_one('SELECT * FROM users WHERE email=?', (email.lower().strip(),))
    valid = verify_password(g.data.get('password', ''), user['password_hash'] if user else DUMMY_PASSWORD)
    if not user or not valid or not user['active']:
        raise s.Error('Неверный email или пароль', 401)
    # Успешный вход не расходует бюджет неудачных попыток общей сети.
    # Удаляем только эту попытку, сохраняя параллельные ошибки и резервирование.
    with LOGIN_LOCK:
        if current in ATTEMPTS.get(key, []):
            ATTEMPTS[key].remove(current)
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    g.db.execute('DELETE FROM sessions WHERE expires_at<=?', (now(),))
    g.db.insert('sessions', dict(token_hash=token_hash(token), user_id=user['id'],
                                csrf=csrf, expires_at=future()))
    return session_cookie(jsonify(user=public_user(user), csrf=csrf), token)


@bp.get('/me')
@api_view()
def me():
    return dict(user=public_user(g.user), csrf=g.user['csrf'])


@bp.post('/logout')
@api_view()
def logout():
    g.db.execute('DELETE FROM sessions WHERE token_hash=?', (g.user['token_hash'],))
    return session_cookie(jsonify(ok=True), clear=True)


@bp.post('/password')
@api_view()
def password():
    account = g.db.locked_one('SELECT password_hash FROM users WHERE id=?', (g.user['id'],))
    if not verify_password(g.data.get('current_password', ''), account['password_hash']):
        raise s.Error('Текущий пароль указан неверно', 403)
    try:
        encoded = hash_password(g.data.get('password'))
    except ValueError as error:
        raise s.Error(str(error)) from error
    g.db.execute('UPDATE users SET password_hash=? WHERE id=?', (encoded, g.user['id']))
    g.db.execute('DELETE FROM sessions WHERE user_id=?', (g.user['id'],))
    return session_cookie(jsonify(ok=True), clear=True)
