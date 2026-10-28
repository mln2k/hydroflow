# Фактическая Git-история

Снимок ветки `dissertation/flask-pages-2026-10-28` на `23689df400b9c0f9007cd73493a40613408d498b`: **10 коммитов**, shallow=False. Полная история получена из origin; исходные 6 коммитов сверены через GitHub API. Последующие коммиты комплекта в этот снимок не входят. Повтор: `python scripts/git_history.py`.

| SHA | Автор в Git | Дата автора | Содержание | Изменения |
| --- | --- | --- | --- | --- |
| 23689df | HydroFlow Audit | 2026-10-28T23:56:29+03:00 | fix: treat automatic Flask HEAD requests as read-only | 3 files changed, 21 insertions(+), 5 deletions(-) |
| af39815 | HydroFlow Audit | 2026-10-28T23:48:56+03:00 | fix: handle long mobile headings and prepare persistent demo deployment | 10 files changed, 148 insertions(+), 12 deletions(-) |
| 5b4d213 | HydroFlow Audit | 2026-10-28T23:42:54+03:00 | feat: serve HydroFlow with Flask, routed pages, account and feedback | 24 files changed, 1036 insertions(+), 316 deletions(-) |
| 1257f17 | HydroFlow Audit | 2026-10-28T18:41:01+03:00 | docs: establish dissertation requirements and baseline evidence | 1 file changed, 26 insertions(+) |
| c89860b | mln2k | 2026-10-27T15:01:52+03:00 | test: cover remaining browser lifecycle exports and account flows | 2 files changed, 53 insertions(+), 1 deletion(-) |
| 121b748 | mln2k | 2026-10-27T14:58:42+03:00 | docs: record verified PostgreSQL Chromium and Docker audit results | 2 files changed, 11 insertions(+), 2 deletions(-) |
| 055421f | mln2k | 2026-10-27T14:54:26+03:00 | fix: enforce project permissions and transactional integrity with audit regressions | 19 files changed, 691 insertions(+), 94 deletions(-) |
| 19af048 | mln2k | 2026-10-26T19:17:32+03:00 | Document successful SQLite, PostgreSQL and Chromium checks | 2 files changed, 19 insertions(+), 5 deletions(-) |
| ef166cb | mln2k | 2026-10-26T19:14:56+03:00 | Implement HydroFlow: requirements, tasks, documents, roles, reports and tests | 26 files changed, 1766 insertions(+), 2 deletions(-) |
| 3cee4cc | mln2k | 2026-10-26T19:14:10+03:00 | Initial commit | 1 file changed, 2 insertions(+) |

Просмотр изменений показывает реальные этапы: исходная реализация, тестовые результаты, исправление доступа/транзакций, расширение браузерных проверок, матрица задания, перенос Flask/страницы/обращения, подготовка размещения и исправление Firefox. Инициализационный коммит и коммиты документации не следует автоматически считать функциональными доработками студента.

Исходные 6 коммитов имеют автора mln2k и даты 26–27.10.2026. Новые локальные коммиты используют существующую конфигурацию HydroFlow Audit; автор/даты не подменялись. Код текущей доработки создан с помощью ИИ. Ни имя в Git, ни число файлов не доказывают собственноручное авторство студента.

**Требование 50 содержательных коммитов студента в установленные периоды не выполнено/не подтверждено.** В истории существенно меньше 50 коммитов; календарь и критерии авторства из оригинального DOCX недоступны. Фиктивные коммиты, задние даты и подмена автора не создавались. Это отдельный вопрос к руководителю, который нельзя закрыть технической миграцией.
