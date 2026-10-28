"""Отдельные HTML-макеты страниц: артефакты проектирования, не скриншоты приложения."""
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'docs' / 'mockups'
PAGES = [
 ('login','/login','Вход','Email и пароль; сообщение об ошибке; переход на запрошенную страницу после входа.'),
 ('projects','/projects','Проекты','Карточки доступных проектов, заказчик, сроки и число завершённых задач.'),
 ('overview','/projects/<id>/overview','Обзор','Прогресс, требования, просрочки, команда и ближайшие задачи.'),
 ('requirements','/projects/<id>/requirements','Требования','Код, описание, приоритет, статус и версия; согласование руководителем; конфликт правок.'),
 ('tasks','/projects/<id>/tasks','Задачи','Доска по статусам, несколько исполнителей, сроки, связи с требованием и этапом.'),
 ('stages','/projects/<id>/stages','Этапы','Периоды этапов и число завершённых связанных задач.'),
 ('documents','/projects/<id>/documents','Документы','Текст, тип и вложение; история версий и получение старого файла.'),
 ('members','/projects/<id>/members','Команда','Участники проекта и их проектные роли; добавление, смена роли, удаление.'),
 ('reports','/projects/<id>/reports','Отчёты','Доля завершённых задач, просрочки и влияние изменённых требований; CSV/JSON/печать.'),
 ('activity','/projects/<id>/activity','История','Автор, действие, объект и дата последних 100 операций проекта.'),
 ('account','/account','Личный кабинет','Имя, email, системная роль; изменение имени и пароля; проекты и назначенные задачи.'),
 ('feedback','/feedback','Обратная связь','Тема, тип, текст; подтверждение сохранения; свои обращения и ответы администратора.'),
 ('help','/help','Справка','Порядок работы, роли, восстановление после ошибок и границы предметной области.'),
 ('admin-users','/admin/users','Команда и доступ','Создание учётной записи, системная роль, блокировка и отзыв сеансов. Только ADMIN.'),
 ('admin-feedback','/admin/feedback','Обращения пользователей','Автор, тема и статус; ответ, закрытие обращения, конфликт одновременной обработки. Только ADMIN.'),
]


def table(headers, rows):
    return '<div class="scroll"><table><tr>'+''.join('<th>'+h+'</th>' for h in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+c+'</td>' for c in row)+'</tr>' for row in rows)+'</table></div>'


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    content = {
      'login':'<form><label>Email<input type="email" value="analyst@example.local"></label><label>Пароль<input type="password" placeholder="Введите пароль"></label><button type="button">Войти</button><p role="alert">Место сообщения: неверный email или пароль.</p></form>',
      'projects':'<article><h2>Журнал наблюдений гидроузла</h2><p>Учебный заказчик · В работе</p><progress value="1" max="3"></progress><p>Завершена 1 из 3 задач</p><a href="overview.html">Открыть проект</a></article>',
      'overview':'<div class="stats"><article><h2>33%</h2>Завершение задач</article><article><h2>3</h2>Требования</article><article><h2>1</h2>Просроченная задача</article></div><h2>Ближайшие задачи</h2><p>Реализовать журнал · Мария Соколова · В работе</p>',
      'requirements':table(['Код','Название','Статус','Версия'],[['REQ-001','Журнал наблюдений','Согласовано','2'],['REQ-002','Проверка доступа','На проверке','1']])+'<article><h2>История REQ-001</h2><p>v2: уточнено обязательное поле участка; автор — аналитик. Руководитель согласовывает редакцию.</p><p>Состояние ошибки: запись уже изменена; обновите данные и сравните правки.</p></article>',
      'tasks':'<div class="stats"><article><h2>Новая</h2><p>Проверить доступ · QA</p></article><article><h2>В работе</h2><p>Реализовать журнал · DEV</p><p>REQ-001 · Этап «Первая версия»</p></article><article><h2>Завершена</h2><p>Согласовать спецификацию · ANALYST</p></article></div>',
      'stages':table(['Этап','Период','Статус','Готовые задачи'],[['Первая версия','01–30 ноября','В работе','1 / 3'],['Приёмка','01–10 декабря','Запланирован','0 / 0']]),
      'documents':table(['Название','Тип','Версия','Файл'],[['Техническое задание','ТЗ','2','specification.txt']])+'<article><h2>Содержание и версии</h2><p>Цель: регистрация наблюдений и согласование отчётов.</p><button>Скачать текущую версию</button><button>История версий</button><p>v1 — исходный текст и первоначальное вложение сохранены.</p></article>',
      'members':table(['Участник','Роль в проекте','Действие'],[['Елена Волкова','PM','Управляет составом'],['Мария Соколова','DEV','Роль / удалить'],['Учебный заказчик','VIEWER','Только просмотр']]),
      'reports':'<h2>Завершена 1 из 3 задач — 33%</h2><p>Новых: 1 · В работе: 1 · Просроченных: 1</p><button>CSV</button> <button>JSON</button> <button>Печать</button><article><h2>Изменённое требование REQ-001 v2</h2><p>Связана завершённая задача «Спроектировать журнал». Необходимость доработки определяет руководитель.</p></article>',
      'activity':table(['Автор','Действие','Объект','Дата'],[['Елена Волкова','Назначение','Задача #2','Сегодня'],['Алексей Морозов','Изменение','REQ-001 v2','Вчера']]),
      'account':'<article><h2>Мои данные</h2><p>Алексей Морозов · analyst@example.local</p><p>Системная роль: ANALYST</p><button>Изменить имя</button> <button>Сменить пароль</button><p>Email доступен только для просмотра.</p></article><h2>Доступные проекты</h2><a href="overview.html">Журнал наблюдений</a><h2>Назначенные задачи</h2><p>Уточнить спецификацию · На проверке · 10 ноября</p>',
      'feedback':'<form><label>Тема<input placeholder="Не удаётся сохранить документ"></label><label>Тип<select><option>Вопрос</option><option>Ошибка</option><option>Предложение</option></select></label><label>Текст<textarea placeholder="Опишите действия и результат"></textarea></label><button type="button">Отправить обращение</button><p>Состояния: отправка / сохранено / нет связи; повторная отправка без дубликата.</p></form><h2>Мои обращения</h2><article><h3>Как получить старое вложение?</h3><p>Закрыто · Ответ: откройте историю версий документа.</p></article>',
      'help':'<h2>Порядок работы</h2><ol><li>Руководитель создаёт проект и команду.</li><li>Аналитик описывает требования, руководитель согласовывает их.</li><li>Исполнители выполняют назначенные задачи; документы сохраняют версии.</li><li>Руководитель проверяет сроки и влияние изменений в отчётах.</li></ol><h2>Границы</h2><p>Управление разработкой ПО; инженерные расчёты и снабжение не выполняются.</p>',
      'admin-users':table(['Имя','Системная роль','Активность','Действия'],[['Елена Волкова','PM','Активна','Изменить роль / блокировать'],['Администратор','ADMIN','Активен','Собственную роль изменить нельзя']])+'<p>Права внутри проекта назначаются отдельно. Последний активный ADMIN защищён.</p>',
      'admin-feedback':table(['Автор','Тема','Статус'],[['Алексей Морозов','Как получить старое вложение?','В работе']])+'<form><label>Статус<select><option>Новое</option><option>В работе</option><option>Закрыто</option></select></label><label>Ответ<textarea>Откройте историю версий документа.</textarea></label><button type="button">Сохранить ответ</button></form>',
    }
    css='body{font:16px/1.5 Arial;margin:0;color:#203847;background:#f3f6f8}header,main{padding:24px}header{background:#142e3b;color:white}a{color:#087e8b}nav{display:flex;flex-wrap:wrap;gap:14px}main{max-width:1100px;margin:auto}article,form{background:white;border:1px solid #ccd9df;border-radius:10px;padding:24px;margin:16px 0}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}label{display:block;margin:12px 0}input,textarea,select{display:block;padding:10px;width:90%;font:inherit}button{padding:10px;margin:4px;border:1px solid #087e8b;border-radius:6px;background:white;color:#087e8b}td,th{text-align:left;padding:14px;border-bottom:1px solid #ccd9df}table{width:100%;background:white}.scroll{overflow:auto}.note{border-left:4px solid #087e8b;padding:12px}h1,h2,p{overflow-wrap:anywhere}@media(max-width:700px){.stats{grid-template-columns:1fr}main{padding:16px}nav{flex-direction:column}details:not([open]) nav{display:none}}'
    (ROOT/'mockup.css').write_text(css, encoding='utf-8')
    links=''.join(f'<a href="{slug}.html">{escape(title)}</a>' for slug,_,title,_ in PAGES)
    for slug,route,title,purpose in PAGES:
        html=f'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Макет: {title}</title><link rel="stylesheet" href="mockup.css"><header>HydroFlow · проектный макет</header><main><p class="note">Самостоятельный макет, подготовлен при доработке 28.10.2026. Вымышленные примеры; формы не сохраняют данные. Это не снимок работающего приложения.</p><details><summary>Карта макетов / мобильное меню</summary><nav>{links}</nav></details><p><a href="projects.html">Проекты</a> → {title}</p><h1>{title}</h1><p><code>{escape(route)}</code> · {escape(purpose)}</p>{content[slug]}</main></html>'
        (ROOT/(slug+'.html')).write_text(html,encoding='utf-8')
    (ROOT/'index.html').write_text(f'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Карта макетов HydroFlow</title><link rel="stylesheet" href="mockup.css"><main><h1>15 макетов страниц</h1><p>Откройте любой макет; ширину окна можно уменьшить до 390 px. Формы и кнопки показывают назначение, а не выполняют операции.</p><nav>{links}</nav></main></html>',encoding='utf-8')


if __name__ == '__main__':
    main()
