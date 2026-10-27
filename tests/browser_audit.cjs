/* Только изолированный сервер: создаёт синтетические проекты и пользователей. */
'use strict';
const {chromium,expect}=require('playwright/test');
const assert=require('node:assert/strict');
const {readFile}=require('node:fs/promises');
const {randomUUID}=require('node:crypto');

(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.HF_BROWSER_CHANNEL||undefined});
  try{
    const base=process.env.HF_TEST_URL||'http://127.0.0.1:8000';
    const suffix=randomUUID();
    const password='Audit-only-'+randomUUID();
    const payload='<img data-audit="xss" src=x onerror="window.auditXss=1">';
    const errors=[];
    const contexts=[];
    async function login(email,pass){
      const context=await browser.newContext({viewport:{width:1440,height:1000}});contexts.push(context);
      const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
      await page.goto(base);
      await page.getByLabel('Электронная почта').fill(email);
      await page.getByLabel('Пароль',{exact:true}).fill(pass);
      await page.getByRole('button',{name:'Войти',exact:true}).click();
      await expect(page.getByRole('heading',{name:'Проекты',exact:true})).toBeVisible();
      const me=await (await context.request.get(base+'/api/me')).json();
      async function api(path,method='GET',data,status=200){
        const response=await context.request.fetch(base+'/api'+path,{method,data,headers:{'X-CSRF-Token':me.csrf}});
        assert.equal(response.status(),status,method+' '+path);
        return await response.json();
      }
      return {context,page,api};
    }
    const admin=await login(process.env.HF_TEST_EMAIL||'admin@example.local',process.env.HF_TEST_PASSWORD);
    const project='Audit '+suffix;
    const {id:pid}=await admin.api('/projects','POST',{name:project,start_date:'2026-01-01'},201);
    const root='/projects/'+pid;
    const users={};
    for(const role of ['PM','ANALYST','DEV','QA','VIEWER']){
      const email=role.toLowerCase()+'-'+suffix+'@example.local';
      const {id}=await admin.api('/users','POST',{email,full_name:role+' '+suffix,role:role==='PM'?'DEV':role,password},201);
      users[role]={id,email};
      await admin.api(root+'/members','POST',{user_id:id,role});
    }
    const {id:rid}=await admin.api(root+'/requirements','POST',{code:'AUDIT',title:'Requirement '+payload,description:payload},201);
    const {id:tid}=await admin.api(root+'/tasks','POST',{title:'Task '+payload,requirement_id:rid},201);
    await admin.api(root+'/tasks/'+tid+'/assignments','POST',{user_ids:[users.DEV.id,users.QA.id]});
    const {id:did}=await admin.api(root+'/documents','POST',{title:'Document '+payload,content:payload,filename:'old.html',file_base64:Buffer.from(payload).toString('base64')},201);
    await admin.api(root+'/documents/'+did,'PATCH',{version:1,filename:'new.txt',file_base64:Buffer.from('New bytes').toString('base64')});
    await admin.api(root+'/comments','POST',{entity_type:'tasks',entity_id:tid,text:payload},201);
    async function openProject(page){
      await page.reload();
      await page.locator('.project-card').filter({hasText:project}).getByRole('button',{name:'Открыть проект →'}).click();
      await expect(page.getByRole('heading',{name:project,exact:true})).toBeVisible();
    }
    async function tab(page,name){await page.getByRole('button',{name,exact:true}).click();}
    async function safe(page){
      assert.equal(await page.locator('img[data-audit]').count(),0);
      assert.equal(await page.evaluate(()=>window.auditXss),undefined);
    }
    await openProject(admin.page);
    // Две открытые формы: проигравшая правка не закрывается и не теряет текст.
    await tab(admin.page,'Документы');
    await tab(admin.page,'Document '+payload);await tab(admin.page,'Редактировать');
    const second=await admin.context.newPage();second.on('pageerror',e=>errors.push(e.message));
    await second.goto(base);await openProject(second);await tab(second,'Документы');
    await tab(second,'Document '+payload);await tab(second,'Редактировать');
    await second.getByLabel('Содержимое / описание').fill('Unsaved text');
    await admin.page.getByLabel('Содержимое / описание').fill('Winning text');
    await tab(admin.page,'Сохранить');await expect(admin.page.locator('#modal')).not.toBeVisible();
    await tab(second,'Сохранить');
    await expect(second.locator('#editor .error')).toContainText('изменена другим');
    await expect(second.getByLabel('Содержимое / описание')).toHaveValue('Unsaved text');
    await second.close();
    await tab(admin.page,'Document '+payload);await tab(admin.page,'История версий');
    await expect(admin.page.locator('.history').last()).toContainText(payload);
    const download=admin.page.waitForEvent('download');
    await admin.page.locator('.history').last().getByRole('button',{name:'Скачать эту версию'}).click();
    const file=await download;assert.equal(file.suggestedFilename(),'old.html');
    assert.equal(await readFile(await file.path(),'utf8'),payload);
    await safe(admin.page);await tab(admin.page,'Закрыть');

    for(const role of ['PM','ANALYST','DEV','QA','VIEWER']){
      const user=await login(users[role].email,password);const {page}=user;
      await openProject(page);
      await tab(page,'Требования');
      await expect(page.getByRole('button',{name:'+ Требование',exact:true})).toHaveCount(['PM','ANALYST'].includes(role)?1:0);
      await tab(page,'Requirement '+payload);await safe(page);
      if(['PM','ANALYST'].includes(role)){
        await tab(page,'Редактировать');
        if(role==='PM')await page.getByLabel('Статус',{exact:true}).selectOption('approved');
        else {await expect(page.getByLabel('Статус',{exact:true})).toHaveValue('draft');await page.getByLabel('Описание',{exact:true}).fill('Analyst revision');}
        await tab(page,'Сохранить');await expect(page.locator('#modal')).not.toBeVisible();
        assert.equal((await user.api(root+'/requirements/'+rid)).status,role==='PM'?'approved':'draft');
      }else await tab(page,'Закрыть');
      await tab(page,'Документы');
      await expect(page.getByRole('button',{name:'+ Документ',exact:true})).toHaveCount(['PM','ANALYST','DEV'].includes(role)?1:0);
      await tab(page,'Document '+payload);await tab(page,'История версий');await safe(page);await tab(page,'Закрыть');
      await tab(page,'Команда');
      await expect(page.getByRole('button',{name:'+ Добавить участника',exact:true})).toHaveCount(role==='PM'?1:0);
      if(role==='PM'){
        await tab(page,'+ Добавить участника');
        await expect(page.getByLabel('Пользователь')).toBeFocused();
        await page.getByLabel('Пользователь').selectOption(String(users.VIEWER.id));
        await page.getByLabel('Роль в проекте').selectOption('VIEWER');
        await tab(page,'Сохранить');await expect(page.locator('#modal')).not.toBeVisible();
      }
      await tab(page,'Задачи');
      await expect(page.getByRole('button',{name:'+ Задача',exact:true})).toHaveCount(role==='VIEWER'?0:1);
      await tab(page,'Task '+payload);await safe(page);
      await expect(page.locator('#comment-form')).toHaveCount(role==='VIEWER'?0:1);
      await expect(page.getByRole('button',{name:'Назначить исполнителей',exact:true})).toHaveCount(role==='PM'?1:0);
      if(role==='DEV'){
        // Ошибка сети сохраняет комментарий и не выбрасывает исключение из catch.
        await page.route('**/api'+root+'/comments',route=>route.abort(),{times:1});
        await page.getByLabel('Комментарий',{exact:true}).fill('Retried comment');await tab(page,'Отправить');
        await expect(page.locator('#comment-form .error')).toContainText('Нет связи');
        await expect(page.getByLabel('Комментарий',{exact:true})).toHaveValue('Retried comment');
        // Повторное submit во время запроса не должно создавать две записи.
        let release;const gate=new Promise(resolve=>release=resolve);let posts=0;
        await page.route('**/api'+root+'/comments',async route=>{posts++;await gate;await route.continue();});
        await page.locator('#comment-form').evaluate(form=>{form.requestSubmit();form.requestSubmit();});
        await expect(page.getByRole('button',{name:'Отправить',exact:true})).toBeDisabled();release();
        await expect(page.locator('.comment')).toContainText([payload,'Retried comment']);assert.equal(posts,1);
        await page.unroute('**/api'+root+'/comments');
      }
      await tab(page,'Закрыть');
      if(['DEV','QA'].includes(role)){
        await tab(page,'+ Задача');await page.getByLabel('Название',{exact:true}).fill(role+' own task');
        await expect(page.getByLabel('Тип',{exact:true})).toHaveValue(role==='DEV'?'dev':'test');
        await tab(page,'Сохранить');await expect(page.locator('#modal')).not.toBeVisible();
        await page.getByLabel('Статус задачи '+role+' own task',{exact:true}).selectOption('done');
        await expect(page.locator('.column').filter({has:page.getByRole('heading',{name:/Завершена/})}).getByRole('button',{name:role+' own task',exact:true})).toBeVisible();
      }
      if(role==='VIEWER'){
        assert.equal((await user.api(root+'/tasks/'+tid,'PATCH',{status:'done'},403)).error,'Недостаточно прав для этого действия');
        await page.setViewportSize({width:390,height:844});
        for(const name of ['Обзор','Требования','Задачи','Этапы','Документы','Команда','Отчёты','История']){
          await tab(page,name);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,name+' mobile overflow');
        }
      }
      await user.context.close();
    }
    // Потеря сессии закрывает диалог, а повторная загрузка после сбоя сети доступна.
    await tab(admin.page,'Требования');await tab(admin.page,'Requirement '+payload);
    await admin.api('/logout','POST',{});
    await tab(admin.page,'История версий');
    await expect(admin.page.getByRole('heading',{name:'Вход в систему'})).toBeVisible();
    await expect(admin.page.locator('#modal')).not.toBeVisible();
    await admin.page.route('**/api/me',route=>route.abort(),{times:1});await admin.page.reload();
    await expect(admin.page.getByRole('button',{name:'Повторить загрузку'})).toBeVisible();
    await tab(admin.page,'Повторить загрузку');await expect(admin.page.getByRole('heading',{name:'Вход в систему'})).toBeVisible();
    assert.deepEqual(errors,[]);
    console.log('Browser audit: OK — roles, project PM, approval, conflict, old attachment bytes, rendered XSS, retry, duplicate submit, mobile tabs, expired session');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
