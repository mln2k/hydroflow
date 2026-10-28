// Run only against an isolated installation; creates synthetic users and records.
const {chromium, firefox, expect} = require('playwright/test');
const assert = require('node:assert/strict');
const {randomUUID} = require('node:crypto');
const path = require('node:path');
const fs = require('node:fs');
const base = process.env.HF_TEST_URL || 'http://127.0.0.1:8000';
const channel = process.env.HF_BROWSER_CHANNEL;
const browserType = process.env.HF_BROWSER === 'firefox' ? firefox : chromium;
const password = process.env.HF_TEST_PASSWORD;
if (!password) throw new Error('HF_TEST_PASSWORD required for disposable installation');
(async()=>{
  const browser = await browserType.launch({headless:true,...(channel?{channel}:{}),...(process.env.HF_BROWSER_EXECUTABLE?{executablePath:process.env.HF_BROWSER_EXECUTABLE}:{})});
  const errors=[];
  async function session(email, pass){
    const context=await browser.newContext({viewport:{width:1366,height:768}});
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base+'/login');
    await page.getByLabel('Электронная почта').fill(email);await page.getByLabel('Пароль',{exact:true}).fill(pass);
    await page.getByRole('button',{name:'Войти',exact:true}).click();await expect(page).toHaveURL(base+'/projects');
    await expect(page.getByRole('heading',{name:'Проекты',exact:true})).toBeVisible();
    const me=await (await context.request.get(base+'/api/me')).json();
    async function api(url,method='GET',data,status=200){const r=await context.request.fetch(base+'/api'+url,{method,data,headers:{'X-CSRF-Token':me.csrf}});assert.equal(r.status(),status,await r.text());return r.json();}
    return {context,page,api};
  }
  try{
    const admin=await session(process.env.HF_TEST_EMAIL||'admin@example.local',password);
    const suffix=randomUUID();const pass='Synthetic-'+suffix;
    const users={};for(const role of ['PM','ANALYST','DEV','QA','VIEWER']){const email=role.toLowerCase()+'-'+suffix+'@example.local';const result=await admin.api('/users','POST',{email,full_name:role+' '+suffix,password:pass,role},201);users[role]={id:result.id,email};}
    const {id:pid}=await admin.api('/projects','POST',{name:'Routes '+suffix,start_date:'2026-01-01'},201);
    for(const [role,user] of Object.entries(users))await admin.api(`/projects/${pid}/members`,'POST',{user_id:user.id,role});
    const {id:tid}=await admin.api(`/projects/${pid}/tasks`,'POST',{title:'Assigned '+suffix},201);
    await admin.api(`/projects/${pid}/tasks/${tid}/assignments`,'POST',{user_ids:[users.DEV.id]});
    const projectRoutes=['overview','requirements','tasks','stages','documents','members','reports','activity'];
    const routes=['/projects',...projectRoutes.map(r=>`/projects/${pid}/${r}`),'/account','/feedback','/help','/admin/users','/admin/feedback'];
    for(const route of routes){
      assert.equal((await admin.page.goto(base+route)).status(),200);
      await expect(admin.page.locator('#main-content h1')).toBeVisible();
      await admin.page.reload();await expect(admin.page.locator('#main-content h1')).toBeVisible();
      assert.equal(new URL(admin.page.url()).pathname,route);
      await expect(admin.page.getByRole('navigation',{name:'Основное меню'}).locator('[aria-current=page]')).toHaveCount(1);
    }
    await admin.page.goto(base+`/projects/${pid}/requirements`);
    const nav=admin.page.getByRole('navigation',{name:'Основное меню'});
    await expect(nav.getByRole('link')).toHaveCount(14);
    await admin.page.getByRole('navigation',{name:'Хлебные крошки'}).getByRole('link',{name:'Routes '+suffix}).click();
    await expect(admin.page).toHaveURL(base+`/projects/${pid}/overview`);
    await admin.page.goBack();await expect(admin.page).toHaveURL(base+`/projects/${pid}/requirements`);
    await expect(admin.page.getByRole('button',{name:'+ Требование',exact:true})).toBeVisible();
    const dev=await session(users.DEV.email,pass);
    await dev.page.goto(base+'/account');await expect(dev.page.getByRole('link',{name:'Assigned '+suffix})).toBeVisible();
    const payload='<img src=x onerror="window.__xss=1">';
    await dev.page.getByRole('button',{name:'Изменить имя'}).click();await dev.page.getByLabel('Полное имя').fill(payload);
    await dev.page.getByRole('button',{name:'Сохранить',exact:true}).click();await expect(dev.page.locator('dd').first()).toHaveText(payload);
    await expect(dev.page.locator('img')).toHaveCount(0);assert.equal(await dev.page.evaluate(()=>window.__xss),undefined);
    await dev.page.goto(base+'/feedback');await dev.page.getByLabel('Тема',{exact:true}).fill(payload);await dev.page.getByLabel('Текст обращения').fill(payload);
    // A network interruption must keep the form and permit retry with the same request key.
    await dev.page.route('**/api/feedback',route=>route.abort(),{times:1});
    await dev.page.getByRole('button',{name:'Отправить обращение'}).click();await expect(dev.page.locator('#feedback-form .error')).toContainText('Нет связи');
    await expect(dev.page.getByLabel('Текст обращения')).toHaveValue(payload);
    // Repeated submit while the first response is pending creates a single record.
    let release;const hold=new Promise(resolve=>release=resolve);
    await dev.page.route('**/api/feedback',async route=>{if(route.request().method()==='POST'){await hold;}await route.continue();},{times:1});
    await dev.page.getByRole('button',{name:'Отправить обращение'}).click();await expect(dev.page.getByRole('button',{name:'Отправить обращение'})).toBeDisabled();
    await dev.page.locator('#feedback-form').dispatchEvent('submit');release();
    await expect(dev.page.locator('.feedback-item')).toHaveCount(1);await expect(dev.page.locator('.feedback-item img')).toHaveCount(0);
    const own=await dev.api('/feedback');assert.equal(own.length,1);const fid=own[0].id;
    await admin.page.goto(base+'/admin/feedback');await admin.page.locator(`[data-feedback="${fid}"]`).click();
    await admin.page.getByLabel('Статус обращения').selectOption('closed');await admin.page.getByLabel('Ответ администратора').fill('Ответ '+payload);
    await admin.page.getByRole('button',{name:'Сохранить',exact:true}).click();await expect(admin.page.locator('#modal')).not.toBeVisible();
    await dev.page.reload();await expect(dev.page.locator('.feedback-item')).toContainText('Ответ '+payload);await expect(dev.page.locator('img')).toHaveCount(0);
    for(const role of Object.keys(users)){
      const u=role==='DEV'?dev:await session(users[role].email,pass);
      for(const url of ['/admin/users','/admin/feedback'])assert.equal((await u.page.goto(base+url)).status(),403);
      await u.page.goto(base+'/account');await expect(u.page.getByRole('navigation',{name:'Основное меню'}).getByRole('link',{name:'Обращения пользователей'})).toHaveCount(0);
      if(role!=='DEV'){await u.api('/feedback/'+fid,'GET',undefined,404);await u.context.close();}
    }
    for(const viewport of [{width:1920,height:1080},{width:1366,height:768},{width:390,height:844}]){
      await admin.page.setViewportSize(viewport);
      for(const url of [`/projects/${pid}/overview`,`/projects/${pid}/tasks`,'/account','/feedback','/admin/feedback','/help']){
        await admin.page.goto(base+url);await expect(admin.page.locator('#main-content h1')).toBeVisible();
        assert.equal(await admin.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,url+' overflow '+viewport.width);
      }
      if(viewport.width===390){
        await admin.page.getByRole('button',{name:'Меню',exact:true}).click();await expect(admin.page.getByRole('button',{name:'Меню',exact:true})).toHaveAttribute('aria-expanded','true');
        await admin.page.getByRole('navigation',{name:'Основное меню'}).getByRole('link',{name:'Личный кабинет'}).click();await expect(admin.page).toHaveURL(base+'/account');
      }
      if(process.env.HF_ARTIFACT_DIR){fs.mkdirSync(process.env.HF_ARTIFACT_DIR,{recursive:true});await admin.page.screenshot({path:path.join(process.env.HF_ARTIFACT_DIR,`${channel||browserType.name()}-${viewport.width}.png`),fullPage:true});}
    }
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({result:'PASS',browser:channel||browserType.name(),version:browser.version(),routes:15,viewports:[1920,1366,390],checks:'direct/reload/back/menu/account/roles/feedback/retry/duplicate/XSS/admin reply'},null,2));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
