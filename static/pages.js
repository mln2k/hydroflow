'use strict';
const sections = {overview:'Обзор',requirements:'Требования',tasks:'Задачи',stages:'Этапы',documents:'Документы',members:'Команда',report:'Отчёты',audit:'История'};
const routes = {report:'reports',audit:'activity'};
const globalTitles = {projects:'Проекты',account:'Личный кабинет',feedback:'Обратная связь',help:'Справка',users:'Команда и доступ',adminFeedback:'Обращения пользователей'};
const feedbackTypes = {question:'Вопрос',bug:'Ошибка',suggestion:'Предложение'};
const feedbackStatuses = {new:'Новое',work:'В работе',closed:'Закрыто'};
let navigating = false;

function currentPath(){return state.p?projectURL()+'/'+(routes[state.tab]||state.tab):({users:'/admin/users',adminFeedback:'/admin/feedback'}[state.page]||'/'+state.page);}
function locationFor(path,replace=false){if(location.pathname!==path)(replace?history.replaceState:history.pushState).call(history,{},'',path);}
function navLink(path,title){return `<a data-nav href="${esc(path)}" ${currentPath()===path?'aria-current="page" class="active"':''}>${esc(title)}</a>`;}
function shell(content){
  const title=state.p?sections[state.tab]:globalTitles[state.page];
  document.title=title+' · HydroFlow';
  const breadcrumbs=`<a data-nav href="/projects">Проекты</a>${state.p?`<span aria-hidden="true"> → </span><a data-nav href="${projectURL()}/overview">${esc(state.p.name)}</a>`:''}<span aria-hidden="true"> → </span><span aria-current="page">${esc(title)}</span>`;
  $('#app').innerHTML=`<div class="shell"><button class="menu-toggle" aria-controls="navigation" aria-expanded="false">Меню</button><aside class="sidebar" id="navigation"><div class="brand">Hydro<span>Flow</span></div><small>Управление разработкой ПО</small><nav aria-label="Основное меню">${navLink('/projects','Все проекты')}${state.p?`<div class="workspace">${esc(state.p.name)}</div>`+Object.entries(sections).map(([key,value])=>navLink(projectURL()+'/'+(routes[key]||key),value)).join(''):''}${navLink('/account','Личный кабинет')}${navLink('/feedback','Обратная связь')}${navLink('/help','Справка')}${state.user.role==='ADMIN'?navLink('/admin/users','Команда и доступ')+navLink('/admin/feedback','Обращения пользователей'):''}</nav><div class="spacer"></div><button data-action="password">Сменить пароль</button><button data-action="logout">Выйти</button><div class="identity">${esc(state.user.full_name)}<br><small>Системная роль: ${esc(labels[state.user.role])}</small></div></aside><main class="main" id="main-content" tabindex="-1"><header class="topbar"><nav aria-label="Хлебные крошки">${breadcrumbs}</nav></header><div class="content">${content}</div></main></div>`;
  $('.menu-toggle').onclick=()=>{const open=$('.menu-toggle').getAttribute('aria-expanded')!=='true';$('.menu-toggle').setAttribute('aria-expanded',String(open));$('.sidebar').classList.toggle('is-open',open);};
}
async function loadProjects(){state.projects=await api('/projects');state.page='projects';state.p=null;locationFor('/projects');renderProjects();}
async function openProject(id){state.p=await api('/projects/'+id);state.page='project';state.tab='overview';state.search='';locationFor(currentPath());renderProject();}
async function refresh(){if(!state.user){renderLogin();return;}if(state.p){state.p=await api(projectURL());locationFor(currentPath());renderProject();}else await navigate(currentPath(),true);}
async function navigate(path,replace=false){
  if(navigating)return;
  navigating=true;
  try{
    if(path==='/'||path==='/login')path='/projects';
    const match=path.match(/^\/projects\/([1-9][0-9]*)\/(overview|requirements|tasks|stages|documents|members|reports|activity)$/);
    if(match){const p=await api('/projects/'+match[1]);state.p=p;state.page='project';state.tab=({reports:'report',activity:'audit'})[match[2]]||match[2];state.search='';renderProject();}
    else if(path==='/projects'){state.projects=await api('/projects');state.p=null;state.page='projects';renderProjects();}
    else if(path==='/account')await accountPage();
    else if(path==='/feedback')await feedbackPage(false);
    else if(path==='/admin/feedback')await feedbackPage(true);
    else if(path==='/admin/users'){if(state.user.role!=='ADMIN')throw new Error('Недостаточно прав');await usersPage();}
    else if(path==='/help'){state.p=null;state.page='help';helpPage();}
    else throw new Error('Страница не найдена');
    locationFor(path,replace);$('#main-content')?.focus({preventScroll:true});
  }catch(error){if(error.status===401)return;state.p=null;$('#app').innerHTML=`<main class="loading" id="main-content"><h1>Не удалось открыть страницу</h1><p role="alert">${esc(error.message)}</p><a href="${esc(path)}">Повторить загрузку</a> · <a href="/projects">Проекты</a></main>`;}
  finally{navigating=false;}
}
async function accountPage(){
  const data=await api('/account');state.p=null;state.page='account';state.user=data.user;
  shell(`<h1>Личный кабинет</h1><section class="panel panel-body"><h2>Мои данные</h2><dl><dt>Имя</dt><dd>${esc(data.user.full_name)}</dd><dt>Email</dt><dd>${esc(data.user.email)}</dd><dt>Системная роль</dt><dd>${esc(labels[data.user.role])}</dd></dl><p>Email используется для входа и здесь не изменяется. Роли в проектах назначает руководитель.</p><div class="actions"><button id="edit-profile">Изменить имя</button><button data-action="password">Сменить пароль</button></div></section><section class="panel panel-body"><h2>Доступные проекты</h2>${data.projects.map(p=>`<p><a data-nav href="/projects/${p.id}/overview">${esc(p.name)}</a></p>`).join('')||'<p>Доступных проектов нет.</p>'}</section><section class="panel panel-body"><h2>Назначенные мне задачи</h2>${data.tasks.map(t=>`<p><a data-nav href="/projects/${t.project_id}/tasks">${esc(t.title)}</a> · ${esc(t.project_name)} · ${badge(t.status)} · срок ${date(t.planned_end)}</p>`).join('')||'<p>Назначенных задач нет.</p>'}</section>`);
  $('#edit-profile').onclick=()=>formModal('Изменить имя',field('Полное имя','full_name',data.user.full_name,'text',true),data=>api('/account','PATCH',data));
}
async function feedbackPage(admin){
  const rows=await api(admin?'/admin/feedback':'/feedback');state.p=null;state.page=admin?'adminFeedback':'feedback';
  shell(`<h1>${admin?'Обращения пользователей':'Обратная связь'}</h1><p>Вопросы о работе HydroFlow, сообщения об ошибках и предложения. Не указывайте пароли и конфиденциальные данные.</p>${admin?'':`<section class="panel panel-body"><h2>Новое обращение</h2><form id="feedback-form">${field('Тема','subject','','text',true)}<label for="f-category">Тип обращения</label><select id="f-category" name="category">${Object.entries(feedbackTypes).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select>${area('Текст обращения','body','',true)}<p class="file-note">До 5 новых обращений в час. Ответ появится в списке ниже.</p><p class="error" role="alert"></p><button class="primary">Отправить обращение</button></form></section>`}<section class="panel panel-body"><h2>${admin?'Все обращения':'Мои обращения'}</h2>${rows.map(r=>`<article class="feedback-item"><h3><button class="link" data-feedback="${r.id}">${esc(r.subject)}</button></h3><p>${esc(feedbackTypes[r.category])} · ${esc(feedbackStatuses[r.status])} · ${date(r.created_at)}${admin?' · '+esc(r.author)+' · '+esc(r.email):''}</p><p class="detail-text">${esc(r.body)}</p>${r.reply?`<h4>Ответ администратора</h4><p class="detail-text">${esc(r.reply)}</p>`:''}</article>`).join('')||'<p>Обращений пока нет.</p>'}</section>`);
  document.querySelectorAll('[data-feedback]').forEach(b=>b.onclick=async()=>{
    try{const r=await api('/feedback/'+b.dataset.feedback);const body=`<p>${esc(feedbackTypes[r.category])} · ${date(r.created_at)}</p><p class="detail-text">${esc(r.body)}</p>`;
      if(admin)formModal(r.subject,body+`<label for="f-status">Статус обращения</label><select id="f-status" name="status">${Object.entries(feedbackStatuses).map(([k,v])=>`<option value="${k}" ${k===r.status?'selected':''}>${v}</option>`).join('')}</select>`+area('Ответ администратора','reply',r.reply),data=>api('/admin/feedback/'+r.id,'PATCH',{...data,version:r.version}));
      else modal(r.subject,body+`<p>Статус: ${esc(feedbackStatuses[r.status])}</p><h3>Ответ администратора</h3><p class="detail-text">${esc(r.reply||'Ответ ещё не получен.')}</p>`);
    }catch(error){toast(error.message);}
  });
  const form=$('#feedback-form');if(!form)return;
  $('#f-subject').maxLength=160;$('#f-body').maxLength=10000;
  const requestKey=crypto.randomUUID();
  form.onsubmit=async e=>{e.preventDefault();if(form.dataset.busy)return;form.dataset.busy='true';form.setAttribute('aria-busy','true');const b=$('button',form);b.disabled=true;
    let saved=false;try{await api('/feedback','POST',{...Object.fromEntries(new FormData(form)),request_key:requestKey});saved=true;}catch(error){$('.error',form).textContent=error.message;}finally{delete form.dataset.busy;form.removeAttribute('aria-busy');b.disabled=false;}
    if(saved){toast('Обращение сохранено');try{await feedbackPage(false);}catch(error){b.disabled=true;$('.error',form).textContent='Обращение сохранено. Обновите страницу: '+error.message;}}
  };
}
function helpPage(){shell(`<h1>Справка</h1><section class="panel panel-body"><h2>От требования до результата</h2><ol><li>Руководитель создаёт проект, задаёт сроки и добавляет команду. Системная роль и роль в конкретном проекте могут различаться.</li><li>Аналитик описывает требования и причины изменений. Руководитель согласовывает требования. Новая редакция согласованного требования аналитиком возвращает его в черновик.</li><li>Создайте этапы и задачи со связями на требования. Руководитель назначает активных участников. Разработчик и тестировщик меняют статус назначенных задач.</li><li>В документах храните текст и файлы до 5 МиБ. История версий позволяет получить старое вложение. При конфликте сохранения закройте редактор, обновите данные и сопоставьте правки.</li><li>Обсуждайте конкретные записи в комментариях. Общие вопросы о системе отправляйте через обратную связь.</li><li>Отчёты показывают завершённые задачи, просрочки и связи с изменёнными требованиями. Решение о доработке принимает руководитель.</li></ol></section><section class="panel panel-body"><h2>Права и безопасность</h2><p>ADMIN управляет пользователями и всеми проектами; PM управляет своим проектом; ANALYST работает с требованиями, задачами и документами; DEV создаёт задачи разработки и документы; QA создаёт задачи тестирования; VIEWER просматривает проект.</p><p>Смена пароля завершает все сеансы. При блокировке доступ также отзывается. Пользователь меняет своё имя в личном кабинете; email и роль самостоятельно не изменяются.</p><h2>Если операция не выполнена</h2><p>Проверьте сообщение рядом с формой и соединение с сервером. При конфликте версий обновите запись. Не повторяйте создание, если сообщение уже подтверждает сохранение. Используйте «Обновить» для повторного получения данных.</p><h2>Границы системы</h2><p>HydroFlow управляет разработкой программного обеспечения для гидротехнических строительных работ. Инженерные расчёты, снабжение и бухгалтерский учёт в систему не входят. Прогресс считается по количеству задач.</p></section>`);}
document.addEventListener('click',async e=>{const a=e.target.closest('a[data-nav]');if(!a||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||e.button!==0)return;e.preventDefault();await navigate(a.getAttribute('href'));});
window.addEventListener('popstate',()=>navigate(location.pathname,true));
bootstrap();
