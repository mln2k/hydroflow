# HTTP API

Все пути ниже начинаются с `/api`. Тело записи — JSON-объект, заголовок `Content-Type: application/json`. Ответы — JSON, кроме `report.csv`. Ошибка: `{"error":"описание"}`. Коды: 400 — валидация, 401 — нет сессии, 403 — запрещено, 404 — нет объекта, 409 — конфликт версий или связей, 413 — размер запроса, 415 — тип тела, 429 — лимит входа или новых обращений.

`POST /login` получает `email`, `password`, возвращает `user`, `csrf` и cookie `hf_session`. Все последующие изменяющие запросы требуют cookie и `X-CSRF-Token`. Для `GET` CSRF-токен не требуется. При наличии `Origin` сервер проверяет его соответствие `PUBLIC_ORIGIN`.

| Метод | Путь | Назначение / основные поля |
| --- | --- | --- |
| GET | `/health` | Проверка процесса и подключения к БД, без входа |
| POST | `/login` | Начало сессии |
| GET | `/me` | Текущий пользователь и CSRF-токен |
| POST | `/logout` | Завершение текущей сессии, тело `{}` |
| POST | `/password` | `current_password`, `password`; завершает все сессии пользователя |
| GET | `/users` | Каталог пользователей для системных ADMIN/PM |
| GET | `/projects/{p}/member-candidates` | ADMIN или PM этого проекта: активные пользователи для подбора участников (`id`, `email`, `full_name`, `active`), независимо от системной роли PM |
| POST | `/users` | ADMIN: `email`, `full_name`, `role`, `password` |
| PATCH | `/users/{id}` | ADMIN: `active` (boolean), `role`; свою роль/активность менять нельзя |
| GET | `/projects` | Доступные проекты и статистика |
| POST | `/projects` | ADMIN/PM: `name`, `description`, `customer`, `start_date`, `end_date`, `status` |
| GET | `/projects/{p}` | Проект с требованиями, задачами, этапами, документами, участниками, обсуждением и последними 100 действиями |
| PATCH | `/projects/{p}` | ADMIN/PM проекта: изменение реквизитов |
| POST | `/projects/{p}/members` | `user_id`, `role`; добавление или смена роли |
| DELETE | `/projects/{p}/members` | `user_id`; удаление участника без назначенных задач |
| POST | `/projects/{p}/comments` | `entity_type`, `entity_id`, `text` |
| GET | `/projects/{p}/report` | Полный отчёт, включая связи изменённых требований |
| GET | `/projects/{p}/report.csv` | Выгрузка задач с BOM UTF-8 и защитой от CSV-формул |

Для сущностей `requirements`, `tasks`, `documents`, `stages`:

| Метод | Путь | Назначение |
| --- | --- | --- |
| POST | `/projects/{p}/{entity}` | Создание, ответ `{"id":123}` |
| GET | `/projects/{p}/{entity}/{id}` | Получение одного объекта |
| PATCH | `/projects/{p}/{entity}/{id}` | Частичное обновление |
| DELETE | `/projects/{p}/{entity}/{id}` | Удаление ADMIN, тело `{}` |
| GET | `/projects/{p}/requirements/{id}/versions` | Снимки редакций требований |
| GET | `/projects/{p}/documents/{id}/versions` | Снимки редакций документов с вложениями |
| POST | `/projects/{p}/tasks/{id}/assignments` | Полная замена исполнителей: `{"user_ids":[2,3]}` |

## Поля сущностей

- Требование: `code`, `title`, `description`, `priority` (`low/medium/high/critical`), `status` (`draft/review/approved/rejected`). В PATCH обязателен текущий целочисленный `version`; `reason` сохраняется в истории. Несовпадение версии возвращает 409.
- Задача: `title`, `description`, `type` (`analysis/dev/test/doc`), `priority`, `status` (`new/work/review/done`), `planned_start`, `planned_end`, необязательные `requirement_id`, `stage_id`. Ссылки должны вести в тот же проект. `actual_start/actual_end` устанавливает сервер. DEV/QA отправляют в PATCH только `status`.
- Этап: `title`, `start_date`, `end_date`, `status` (`planned/active/done`). Обе даты обязательны.
- Документ: `title`, `doc_type` (`TZ/SRS/Protocol/Report/Other`), `content`, `filename`, `file_base64`. В PATCH обязателен `version`. Файл необязателен; бинарные данные и имя задаются вместе. Для удаления текущего вложения через API отправьте обе строки пустыми в новой версии.

`version` в PATCH — строго положительное JSON-целое: boolean, дробное число и строка возвращают 400; устаревшее целое — 409. Идентификаторы ограничены диапазоном 1…9223372036854775807. Некорректный JSON, NaN/Infinity, непарные Unicode-суррогаты и слишком глубокая вложенность возвращают 400. Ошибки ограничений БД возвращают 409 без текста SQL.

Участника с назначенными задачами нельзя удалить или перевести в VIEWER (409); сначала снимите назначения. Заблокированного участника можно удалить после снятия назначений. Блокировка учётной записи сохраняет прежние назначения для последующего решения руководителя, но запрещает новые назначения и вход.

Даты передаются как `YYYY-MM-DD`, время возвращается в ISO 8601 UTC. Текстовое поле описания ограничено 20 000 символами, комментарий — 5 000, файл — 5 МиБ. Для списков используется агрегированный GET проекта; отдельные GET коллекций сущностей не предусмотрены.


## Кабинет и обращения (v2)

| Метод | Путь после /api | Данные / результат |
| --- | --- | --- |
| GET | `/account` | public user (id/email/full_name/role), доступные projects, назначенные tasks; без хеша/сессионных секретов |
| PATCH | `/account` | только full_name, непустое до 150 символов; role/active/email и любые другие поля → 403 |
| GET | `/feedback` | Только обращения текущего пользователя; ADMIN здесь также видит только свои |
| POST | `/feedback` | subject (1–160), category (question/bug/suggestion), body (1–10000), request_key (16–80: буквы/цифры/_/-); 201 новый id или 200 replay |
| GET | `/feedback/{id}` | Автор или ADMIN; чужой/неизвестный ID → 404 |
| GET | `/admin/feedback` | Только ADMIN, все обращения с автором/email |
| PATCH | `/admin/feedback/{id}` | Только ADMIN, обязательный integer version, status (new/work/closed), reply (до 10000); конфликт → 409 |

Автор/время/начальный статус обращения задаются сервером; переданные клиентом user_id/created_at/status не используются. Один request_key у одного автора с другим текстом → 409. Лимит: 5 новых обращений за скользящий час; повтор уже сохранённой записи не тратит лимит. Обращения и ответ не отправляются во внешнюю почту. Время хранится в UTC.

Системный каталог GET /users оставлен совместимым для ADMIN/PM; HTML-админпанель /admin/users и все изменения пользователей доступны только ADMIN. Проектный PM получает кандидатов через /projects/{p}/member-candidates независимо от своей системной роли. Менять собственную системную роль/активность нельзя; изменения отзывают сессии.
