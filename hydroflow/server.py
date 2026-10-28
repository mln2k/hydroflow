"""Фабрика Flask и WSGI-сервер; legacy HTTP handler удалён."""
import os
from pathlib import Path
from flask import Flask, jsonify, request, render_template
from werkzeug.exceptions import HTTPException
from .db import Conflict, transaction
from . import services as s
from .web.auth import ATTEMPTS

ROOT = Path(__file__).resolve().parent.parent


def create_app(config=None):
    app = Flask(__name__, static_folder=str(ROOT / 'static'), static_url_path='',
                template_folder=str(ROOT / 'templates'))
    app.config.from_mapping(
        DATABASE_URL=os.getenv('DATABASE_URL', 'sqlite:///data/hydroflow.db'),
        PUBLIC_ORIGIN=os.getenv('PUBLIC_ORIGIN', ''),
        COOKIE_SECURE=os.getenv('COOKIE_SECURE') == '1',
        MAX_CONTENT_LENGTH=7_500_000,
        TRUSTED_HOSTS=os.getenv('TRUSTED_HOSTS', '').split(',') if os.getenv('TRUSTED_HOSTS') else None,
    )
    if config:
        app.config.update(config)
    app.json.ensure_ascii = False
    from .web import auth, projects, admin, pages, account
    for module in (auth, projects, admin, pages, account):
        app.register_blueprint(module.bp)

    @app.get('/api/health')
    def health():
        with transaction(app.config['DATABASE_URL']) as db:
            db.execute('SELECT 1')
        return {'ok': True}

    @app.after_request
    def headers(response):
        response.headers.update({
            'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'Referrer-Policy': 'same-origin',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        })
        return response

    @app.errorhandler(Exception)
    def error(error):
        if isinstance(error, s.Error):
            status, message = error.status, str(error)
        elif isinstance(error, Conflict):
            status, message = 409, str(error)
        elif isinstance(error, HTTPException):
            status = error.code
            message = {400: 'Некорректный запрос', 404: 'Страница не найдена',
                       405: 'Метод не поддерживается', 413: 'Недопустимый размер запроса'}.get(status, 'Ошибка запроса')
        else:
            # Исключения драйвера могут содержать SQL/данные: не пишем их в общие логи.
            app.logger.error('Unhandled request error: %s', type(error).__name__)
            status, message = 500, 'Внутренняя ошибка сервера'
        if request.path.startswith('/api/'):
            return jsonify(error=message), status
        return render_template('error.html', status=status, message=message), status
    return app


def make_server(host='127.0.0.1', port=8000, db_url=None):
    """Werkzeug WSGI-сервер только для интеграционных тестов."""
    from werkzeug.serving import make_server as wsgi_server
    config = {'DATABASE_URL': db_url} if db_url else None
    return wsgi_server(host, port, create_app(config), threaded=True)


def serve(host='127.0.0.1', port=8000):
    """Один процесс Waitress с потоками. Forwarded-заголовки не считаются доверенными."""
    from waitress import serve as run
    run(create_app(), host=host, port=port, threads=8, max_request_body_size=7_500_000,
        clear_untrusted_proxy_headers=True, channel_timeout=30)
