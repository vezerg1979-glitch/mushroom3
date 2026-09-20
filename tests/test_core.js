const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const C = require('../app/src/main/assets/core.js');
const root = path.join(__dirname,'../app/src/main/assets');
let total=0;
function test(name,run){run();total++;console.log('✓ '+name);}
const date = (y,m,d)=>new Date(y,m-1,d);
test('Локальная дата без смещения часового пояса',()=>{
  assert.equal(C.dateKey(date(2026,9,19)), '2026-09-19');
  assert.equal(C.daysSince('2026-09-17', date(2026,9,19)),2);
  assert.equal(C.daysSince('2026-12-31', date(2027,1,1)),1);
});
test('Некорректные даты отклоняются',()=>{
  assert.equal(C.parseDay('2026-02-30'),null);
  assert.equal(C.parseDay('0000-00-00'),null);
  assert.equal(C.parseDay('2026-9-19'),null);
  assert.equal(C.daysSince('not-a-date'),null);
});
test('Влажность: никогда не предписывает полив автоматически',()=>{
  assert.equal(C.moistureStatus({lastCheck:''},date(2026,7,15)).due,true);
  assert.equal(C.moistureStatus({lastCheck:'2026-07-14'},date(2026,7,15)).due,false);
  assert.equal(C.moistureStatus({lastCheck:'2026-07-13'},date(2026,7,15)).due,true);
  assert.match(C.moistureStatus({lastCheck:''},date(2026,7,15)).secondary,/только если/i);
});
test('Отметка календарной задачи привязана к году и месяцу',()=>{
  assert.equal(C.checklistKey('prune',3,2026),'2026-04:prune');
  assert.notEqual(C.checklistKey('prune',3,2026),C.checklistKey('prune',3,2027));
});
test('Корректная копия сохраняет растения и историю',()=>{
  const b=C.sanitizeBackup({version:1,plants:[{id:'p1',name:'Лаймлайт',variety:'Limelight',lastCheck:'2026-09-19',history:[{kind:'water',day:'2026-09-19',note:'полив'}]}],completed:['2026-04:prune']});
  assert.equal(b.plants[0].name,'Лаймлайт');
  assert.equal(b.plants[0].history[0].kind,'water');
  assert.equal(b.completed.length,1);
});
test('Копия с повторными ID и неверной версией не импортируется',()=>{
  assert.throws(()=>C.sanitizeBackup({version:2,plants:[],completed:[]}));
  assert.throws(()=>C.sanitizeBackup({version:1,plants:[{id:'x',name:'Куст'},{id:'x',name:'Куст 2'}],completed:[]}));
});
test('Длинные примечания и дополнительные поля отбрасываются при импорте',()=>{
  const p=C.sanitizeBackup({version:1,plants:[{id:'x',name:'A'.repeat(500),notes:'n'.repeat(900),evil:'<script>'}],completed:['bad value','2026-04:prune']}).plants[0];
  assert.equal(p.name.length,70); assert.equal(p.notes.length,400);
  assert.equal(Object.hasOwn(p,'evil'),false);
});
test('Сезонные задачи, справочник и сорта доступны для 12 месяцев',()=>{
  const ctx={window:{},console};vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(root,'content.js'),'utf8'),ctx);
  assert.equal(ctx.window.GardenContent.tasks.length,12);
  assert.ok(ctx.window.GardenContent.tasks.every(x=>x.length>=2));
  assert.ok(ctx.window.GardenContent.guides.length>=8);
  assert.ok(ctx.window.GardenContent.varieties.some(x=>x.name==='Limelight'));
});
test('Стартовая страница приложения рендерится в офлайн-режиме',()=>{
  const stored={};
  const ctx={window:{GardenCore:C},console,Date,Math,JSON,URL,Blob,setTimeout:()=>1,clearTimeout:()=>{},
    localStorage:{getItem:k=>stored[k]||null,setItem:(k,v)=>{stored[k]=v;}},
    FormData:class {constructor(form){this.values=form.values;} get(key){return this.values[key]||'';}},
  };
  class El{
    constructor(){this.innerHTML='';this.classList={toggle:()=>{},add:()=>{},remove:()=>{},contains:()=>true};this.dataset={};this.handlers={};}
    addEventListener(name, fn){this.handlers[name]=fn;}
    querySelectorAll(){return [new El(),new El(),new El(),new El(),new El()];}
    querySelector(){return null;}
    setAttribute(){}
  }
  const elems={main:new El(),overlay:new El(),tabs:new El(),toast:new El(),'backup-file':new El()};
  ctx.document={getElementById:id=>elems[id]};
  ctx.window.scrollTo=()=>{};
  ctx.window.GardenContent=null;
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(root,'content.js'),'utf8'),ctx);
  vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),ctx);
  assert.match(elems.main.innerHTML,/Сегодня в саду/);
  assert.match(elems.main.innerHTML,/Добавить гортензию/);
  assert.match(elems.main.innerHTML,/Гортензия/);
  // Переход в календарь и справочник через настоящие обработчики приложения.
  elems.tabs.handlers.click({target:{closest:()=>({dataset:{tab:'calendar'}})}});
  assert.match(elems.main.innerHTML,/Календарь ухода/);
  elems.tabs.handlers.click({target:{closest:()=>({dataset:{tab:'guide'}})}});
  assert.match(elems.main.innerHTML,/Справочник/);
  elems.tabs.handlers.click({target:{closest:()=>({dataset:{tab:'plants'}})}});
  elems.main.handlers.click({target:{closest:()=>({dataset:{action:'add-plant'}})}});
  assert.match(elems.overlay.innerHTML,/Новая гортензия/);
  let prevented=false;
  elems.overlay.handlers.submit({preventDefault:()=>{prevented=true;},target:{id:'plant-form',dataset:{id:''},values:{name:'Куст у дома',variety:'Limelight',place:'Терраса'}}});
  assert.equal(prevented,true);
  assert.match(elems.main.innerHTML,/Куст у дома/);
  assert.equal(JSON.parse(stored['gortenziya_moy_sad_v1']).plants.length,1);
});
test('Фото в резервной копии: только локальные UUID, максимум 12',()=>{
  const valid='01234567-89ab-4cde-8f01-234567890abc';
  const backup=C.sanitizeBackup({version:1,plants:[{id:'p',name:'Гортензия',photos:[valid,'../evil.jpg','<script>']}],completed:[]});
  assert.equal(backup.plants[0].photos.length,1);
  assert.equal(backup.plants[0].photos[0],valid);
  assert.equal(backup.plants[0].photos.includes('../evil.jpg'),false);
});
test('Старые копии 1.0/1.1 импортируются с пустым каталогом новых сортов',()=>{
  const old=C.sanitizeBackup({version:1,plants:[{id:'p',name:'Куст',variety:'Bobo'}],completed:[]});
  assert.deepEqual(old.customVarieties,[]);
  assert.equal(old.plants[0].variety,'Bobo');
});
test('Новые сорта проходят проверку и остаются в резервной копии',()=>{
  const v={id:'v-abcdefgh-12345678',name:'Pink Diamond',height:'до 1,5 м',color:'Белый → розовый',bloom:'Поздний',tag:'Высокий',notes:'Наблюдения'};
  const b=C.sanitizeBackup({version:1,plants:[{id:'p',name:'Куст',variety:v.name}],completed:[],customVarieties:[v]});
  assert.equal(b.customVarieties[0].color,'Белый → розовый');
  assert.equal(b.plants[0].variety,'Pink Diamond');
  assert.equal(b.customVarieties[0].notes,'Наблюдения');
  assert.equal(b.customVarieties[0].evil,undefined);
});
test('Повторные сорта, подозрительные ID и превышение лимита блокируются',()=>{
  const good={id:'v-abcdefgh-12345678',name:'New Rose'};
  assert.throws(()=>C.sanitizeVariety({...good,id:'../private'}));
  assert.throws(()=>C.sanitizeBackup({version:1,plants:[],completed:[],customVarieties:[good,{...good,id:'v-abcdefgh-87654321',name:'  NEW   rose ' }]}));
  assert.throws(()=>C.sanitizeBackup({version:1,plants:[],completed:[],customVarieties:Array.from({length:101},(_,i)=>({...good,id:'v-'+String(i).padStart(10,'0'),name:'Новый сорт '+i}))}));
  assert.equal(C.sanitizeVariety({...good,bloom:'<script>',tag:'other',notes:'N'.repeat(900)}).notes.length,500);
});
test('Интерфейс позволяет добавить и изменить свой сорт, а затем удалить его',()=>{
  const stored={};
  const ctx={window:{GardenCore:C},console,Date,Math,JSON,URL,Blob,setTimeout:()=>1,clearTimeout:()=>{},
    localStorage:{getItem:k=>stored[k]||null,setItem:(k,v)=>{stored[k]=v;}},
    FormData:class {constructor(form){this.values=form.values;} get(key){return Object.hasOwn(this.values,key)?this.values[key]:'';}},
  };
  class El{
    constructor(){this.innerHTML='';this.classList={toggle:()=>{},add:()=>{},remove:()=>{},contains:()=>true};this.dataset={};this.handlers={};}
    addEventListener(name,fn){this.handlers[name]=fn;}
    querySelectorAll(){return [new El(),new El(),new El()];}
    querySelector(){return null;}
    setAttribute(){}
  }
  const elems={main:new El(),overlay:new El(),tabs:new El(),toast:new El(),'backup-file':new El()};
  ctx.document={getElementById:id=>elems[id]};ctx.window.scrollTo=()=>{};
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(root,'content.js'),'utf8'),ctx);
  vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),ctx);
  const click=(el, action, id='',more={})=>el.handlers.click({target:{closest:()=>({dataset:{action,id,...more}})}});
  elems.tabs.handlers.click({target:{closest:()=>({dataset:{tab:'guide'}})}});
  click(elems.main,'guide-mode','sort');
  assert.match(elems.main.innerHTML,/Добавить новый сорт/);
  click(elems.main,'add-variety');
  assert.match(elems.overlay.innerHTML,/Новый сорт гортензии/);
  const form=(id,values)=>elems.overlay.handlers.submit({preventDefault:()=>{},target:{id:'variety-form',dataset:{id},values}});
  form('',{name:'Pink Diamond',height:'до 1,5 м',color:'Белый → розовый',bloom:'Поздний',tag:'Высокий',notes:'Мой опыт'});
  let state=JSON.parse(stored['gortenziya_moy_sad_v1']);
  assert.equal(state.customVarieties.length,1);
  assert.match(elems.main.innerHTML,/Pink Diamond/);
  const id=state.customVarieties[0].id;
  click(elems.main,'edit-variety',id);
  form(id,{name:'Pink Diamond II',height:'до 2 м',color:'Розовый',bloom:'Ранний',tag:'Другой',notes:'Обновлено'});
  state=JSON.parse(stored['gortenziya_moy_sad_v1']);
  assert.equal(state.customVarieties[0].name,'Pink Diamond II');
  assert.equal(state.customVarieties[0].height,'до 2 м');
  // Нельзя дублировать встроенный сорт.
  click(elems.main,'add-variety');form('',{name:'Limelight',tag:'Другой',bloom:'Неизвестно'});
  assert.equal(JSON.parse(stored['gortenziya_moy_sad_v1']).customVarieties.length,1);
  click(elems.overlay,'cancel-variety');
  click(elems.main,'delete-variety',id);
  assert.match(elems.overlay.innerHTML,/Удалить сорт/);
  click(elems.overlay,'delete-variety-confirm',id);
  assert.equal(JSON.parse(stored['gortenziya_moy_sad_v1']).customVarieties.length,0);
});
test('Переименование своего сорта обновляет связанные кусты, удаление не стирает их данные',()=>{
  const id='v-abcd1234-efgh5678';
  const stored={'gortenziya_moy_sad_v1':JSON.stringify({version:1,plants:[{id:'p1',name:'У дома',variety:' Pink Diamond ',photos:[]},{id:'p2',name:'У забора',variety:'Bobo',photos:[]}],completed:[],customVarieties:[{id,name:'Pink Diamond',height:'',color:'',bloom:'Ранний',tag:'Другой',notes:''}]})};
  const ctx={window:{GardenCore:C},console,Date,Math,JSON,URL,Blob,setTimeout:()=>1,clearTimeout:()=>{},
    localStorage:{getItem:k=>stored[k]||null,setItem:(k,v)=>{stored[k]=v;}},
    FormData:class {constructor(form){this.values=form.values;} get(key){return this.values[key]||'';}},
  };
  class El{constructor(){this.innerHTML='';this.classList={toggle:()=>{},add:()=>{},remove:()=>{},contains:()=>true};this.dataset={};this.handlers={};}
    addEventListener(name,fn){this.handlers[name]=fn;}querySelectorAll(){return [];}querySelector(){return null;}setAttribute(){}
  }
  const elems={main:new El(),overlay:new El(),tabs:new El(),toast:new El(),'backup-file':new El()};
  ctx.document={getElementById:id=>elems[id]};ctx.window.scrollTo=()=>{};vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(root,'content.js'),'utf8'),ctx);vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),ctx);
  const click=(el,action,vid)=>el.handlers.click({target:{closest:()=>({dataset:{action,id:vid}})}});
  click(elems.main,'add-variety'); // Добавление открывает только форму; редактирование работает из неё независимо.
  click(elems.overlay,'cancel-variety');
  elems.tabs.handlers.click({target:{closest:()=>({dataset:{tab:'guide'}})}});
  click(elems.main,'guide-mode','sort');
  click(elems.main,'edit-variety',id);
  elems.overlay.handlers.submit({preventDefault:()=>{},target:{id:'variety-form',dataset:{id},values:{name:'Pink Diamond II',bloom:'Средний',tag:'Другой'}}});
  let state=JSON.parse(stored['gortenziya_moy_sad_v1']);
  assert.equal(state.plants[0].variety,'Pink Diamond II');
  assert.equal(state.plants[1].variety,'Bobo');
  click(elems.main,'delete-variety',id);click(elems.overlay,'delete-variety-confirm',id);
  state=JSON.parse(stored['gortenziya_moy_sad_v1']);
  assert.equal(state.plants.length,2);
  assert.equal(state.plants[0].variety,'Pink Diamond II');
});
test('Добавление сорта из формы куста сохраняет незавершённые поля',()=>{
  const stored={};
  const ctx={window:{GardenCore:C},console,Date,Math,JSON,URL,Blob,setTimeout:()=>1,clearTimeout:()=>{},
    localStorage:{getItem:k=>stored[k]||null,setItem:(k,v)=>{stored[k]=v;}},
    FormData:class {constructor(form){this.values=form.values;} get(key){return this.values[key]||'';}},
  };
  class El{
    constructor(){this.innerHTML='';this.classList={toggle:()=>{},add:()=>{},remove:()=>{},contains:()=>true};this.dataset={};this.handlers={};}
    addEventListener(name,fn){this.handlers[name]=fn;}
    querySelectorAll(){return [];}
    querySelector(selector){if(selector==='#plant-form')return {dataset:{id:''},values:{name:'У веранды',variety:'Пинк Даймонд',planted:'2026-04-25',place:'У веранды',notes:'Полутень'}};return null;}
    setAttribute(){}
  }
  const elems={main:new El(),overlay:new El(),tabs:new El(),toast:new El(),'backup-file':new El()};
  ctx.document={getElementById:id=>elems[id]};ctx.window.scrollTo=()=>{};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(root,'content.js'),'utf8'),ctx);
  vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),ctx);
  const click=(el,action)=>el.handlers.click({target:{closest:()=>({dataset:{action}})}});
  click(elems.main,'add-plant');click(elems.overlay,'add-variety-from-plant');
  assert.match(elems.overlay.innerHTML,/Пинк Даймонд/);
  elems.overlay.handlers.submit({preventDefault:()=>{},target:{id:'variety-form',dataset:{id:''},values:{name:'Pink Diamond',bloom:'Средний',tag:'Другой'}}});
  assert.match(elems.overlay.innerHTML,/У веранды/);
  assert.match(elems.overlay.innerHTML,/Pink Diamond/);
  assert.match(elems.overlay.innerHTML,/Полутень/);
});
test('v1.3: новые и старые фотографии сортируются по дате, при совпадении — по порядку',()=>{
  const a='01234567-89ab-4cde-8f01-234567890abc',b='11234567-89ab-4cde-8f01-234567890abc',c='21234567-89ab-4cde-8f01-234567890abc';
  const p={photos:[a,b,c],photoMeta:{[a]:{day:'2026-07-11',stage:'Цветение',note:'Первое цветение'},[b]:{day:'2026-04-01',stage:'Рост побегов',note:'Весна'}}};
  assert.deepEqual(C.photoTimeline(p).map(x=>x.id),[c,b,a]); // Старые снимки без даты первыми.
  assert.equal(C.photoTimeline(p)[2].note,'Первое цветение');
});
test('v1.3: история фото сохраняется в копии, невалидные даты и этапы отбрасываются',()=>{
  const valid='01234567-89ab-4cde-8f01-234567890abc',other='11234567-89ab-4cde-8f01-234567890abc';
  const backup=C.sanitizeBackup({version:1,plants:[{id:'p',name:'Гортензия',photos:[valid,other,valid],photoMeta:{
    [valid]:{day:'2026-08-12',stage:'Цветение',note:'n'.repeat(800),evil:'bad'},
    [other]:{day:'2026-02-30',stage:'<script>',note:'Зимний вид'},
    '31234567-89ab-4cde-8f01-234567890abc':{note:'лишнее фото'}
  }}],completed:[]});
  const p=backup.plants[0];
  assert.deepEqual(p.photos,[valid,other]);
  assert.equal(p.photoMeta[valid].note.length,180);
  assert.equal(p.photoMeta[valid].stage,'Цветение');
  assert.equal(p.photoMeta[valid].evil,undefined);
  assert.equal(p.photoMeta[other].day,'');
  assert.equal(p.photoMeta[other].stage,'Не указана');
  assert.equal(Object.keys(p.photoMeta).length,2);
});
test('v1.3: поиск по названию, сорту и месту не теряет длинные записи',()=>{
  const p=[{name:'А'.repeat(70),variety:'Limelight',place:'У дорожки',photos:[],lastCheck:''},
    {name:'Другой',variety:'Bobo',place:'За домом',photos:['id'],lastCheck:'2026-08-12'}];
  assert.equal(C.filterPlants(p,'limelight').length,1);
  assert.equal(C.filterPlants(p,'дорожки').length,1);
  assert.equal(C.filterPlants(p,'bobo','С фотографиями').length,1);
  assert.equal(C.filterPlants(p,'limelight','С фотографиями').length,0);
  assert.equal(C.filterPlants(p,'','Проверить почву').length,2); // Давно не проверяли оба куста.
  assert.equal(C.filterPlants(p,'нет такого названия').length,0);
});
test('v1.3: фото с опасным вводом экранируются в визуальном дневнике',()=>{
  const photo='01234567-89ab-4cde-8f01-234567890abc',stored={};
  stored['gortenziya_moy_sad_v1']=JSON.stringify({version:1,completed:[],plants:[{id:'p',name:'Куст',variety:'Limelight',photos:[photo],photoMeta:{[photo]:{day:'2026-08-12',stage:'Цветение',note:'<img src=x onerror=alert(1)>'}}}]});
  const ctx={window:{GardenCore:C},console,Date,Math,JSON,URL,Blob,setTimeout:()=>1,clearTimeout:()=>{},
    localStorage:{getItem:k=>stored[k]||null,setItem:(k,v)=>{stored[k]=v;}},
    FormData:class{constructor(form){this.values=form.values||{};}get(key){return this.values[key]||'';}},
  };
  class El{
    constructor(){this.innerHTML='';this.classList={toggle:()=>{},add:()=>{},remove:()=>{},contains:()=>true};this.dataset={};this.handlers={};}
    addEventListener(name,fn){this.handlers[name]=fn;}
    querySelectorAll(){return [new El(),new El(),new El()];}
    querySelector(){return null;}
    setAttribute(){}
    scrollIntoView(){}
  }
  const elems={main:new El(),overlay:new El(),tabs:new El(),toast:new El(),'backup-file':new El()};
  ctx.document={getElementById:id=>elems[id]};ctx.window.scrollTo=()=>{};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(root,'content.js'),'utf8'),ctx);
  vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),ctx);
  elems.tabs.handlers.click({target:{closest:()=>({dataset:{tab:'plants'}})}});
  elems.main.handlers.click({target:{closest:()=>({dataset:{action:'open-plant',id:'p'}})}});
  assert.match(elems.main.innerHTML,/&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(elems.main.innerHTML,/<img src=x onerror=alert\(1\)>/);
  assert.match(elems.main.innerHTML,/Описание/);
});

test('v1.3: поиск и фильтры сада работают в интерфейсе',()=>{
  const stored={};
  stored['gortenziya_moy_sad_v1']=JSON.stringify({version:1,completed:[],plants:[
    {id:'p1',name:'Розовая',variety:'Pink Diamond',place:'У калитки',photos:[]},
    {id:'p2',name:'Белая',variety:'Limelight',place:'У дома',photos:['01234567-89ab-4cde-8f01-234567890abc']}
  ]});
  const ctx={window:{GardenCore:C},console,Date,Math,JSON,URL,Blob,setTimeout:()=>1,clearTimeout:()=>{},
    localStorage:{getItem:k=>stored[k]||null,setItem:(k,v)=>{stored[k]=v;}},
    FormData:class{constructor(form){this.values=form.values||{};}get(key){return this.values[key]||'';}},
  };
  class El{
    constructor(){this.innerHTML='';this.classList={toggle:()=>{},add:()=>{},remove:()=>{},contains:()=>true};this.dataset={};this.handlers={};}
    addEventListener(name,fn){this.handlers[name]=fn;}
    querySelectorAll(){return [new El(),new El(),new El()];}
    querySelector(){return null;}
    setAttribute(){}
  }
  const elems={main:new El(),overlay:new El(),tabs:new El(),toast:new El(),'backup-file':new El()};
  ctx.document={getElementById:id=>elems[id]};ctx.window.scrollTo=()=>{};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(root,'content.js'),'utf8'),ctx);
  vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),ctx);
  elems.tabs.handlers.click({target:{closest:()=>({dataset:{tab:'plants'}})}});
  assert.match(elems.main.innerHTML,/Розовая/);
  elems.main.handlers.submit({target:{id:'plant-search-form',values:{query:'Limelight'}},preventDefault(){}});
  assert.match(elems.main.innerHTML,/Белая/);
  assert.doesNotMatch(elems.main.innerHTML,/<h3 class="clipped">Розовая<\/h3>/);
  elems.main.handlers.click({target:{closest:()=>({dataset:{action:'clear-plant-search'}})}});
  elems.main.handlers.click({target:{closest:()=>({dataset:{action:'plant-filter',filter:'С фотографиями'}})}});
  assert.match(elems.main.innerHTML,/Белая/);
  assert.doesNotMatch(elems.main.innerHTML,/<h3 class="clipped">Розовая<\/h3>/);
});
test('v1.3: у фото можно открыть описание и сравнение двух снимков',()=>{
  const first='01234567-89ab-4cde-8f01-234567890abc',second='11234567-89ab-4cde-8f01-234567890abc',stored={};
  stored['gortenziya_moy_sad_v1']=JSON.stringify({version:1,completed:[],plants:[{id:'p',name:'Куст',photos:[first,second]}]});
  const ctx={window:{GardenCore:C},console,Date,Math,JSON,URL,Blob,setTimeout:()=>1,clearTimeout:()=>{},
    localStorage:{getItem:k=>stored[k]||null,setItem:(k,v)=>{stored[k]=v;}},
    FormData:class{constructor(form){this.values=form.values||{};}get(key){return this.values[key]||'';}},
  };
  class El{
    constructor(){this.innerHTML='';this.classList={toggle:()=>{},add:()=>{},remove:()=>{},contains:()=>true};this.dataset={};this.handlers={};}
    addEventListener(name,fn){this.handlers[name]=fn;}
    querySelectorAll(){return [new El(),new El(),new El()];}
    querySelector(){return null;}
    setAttribute(){}
  }
  const elems={main:new El(),overlay:new El(),tabs:new El(),toast:new El(),'backup-file':new El()};
  ctx.document={getElementById:id=>elems[id]};ctx.window.scrollTo=()=>{};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(root,'content.js'),'utf8'),ctx);
  vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),ctx);
  elems.tabs.handlers.click({target:{closest:()=>({dataset:{tab:'plants'}})}});
  elems.main.handlers.click({target:{closest:()=>({dataset:{action:'open-plant',id:'p'}})}});
  assert.match(elems.main.innerHTML,/Сравнить два снимка/);
  elems.main.handlers.click({target:{closest:()=>({dataset:{action:'edit-photo',id:'p',photo:first}})}});
  assert.match(elems.overlay.innerHTML,/Дата снимка/);
  elems.overlay.handlers.submit({preventDefault(){},target:{id:'photo-form',dataset:{id:'p',photo:first},values:{day:'2026-08-12',stage:'Цветение',note:'Первое цветение'}}});
  assert.equal(JSON.parse(stored['gortenziya_moy_sad_v1']).plants[0].photoMeta[first].note,'Первое цветение');
  elems.main.handlers.click({target:{closest:()=>({dataset:{action:'compare-photos',id:'p'}})}});
  assert.match(elems.overlay.innerHTML,/Первый снимок/);
  assert.match(elems.overlay.innerHTML,/Второй снимок/);
});

test('v1.4: сохранённые сравнения сохраняются в резервной копии',()=>{
  const a='01234567-89ab-4cde-8f01-234567890abc',b='11234567-89ab-4cde-8f01-234567890abc';
  const clean=C.sanitizeBackup({version:1,completed:[],plants:[{id:'p',name:'Сад',photos:[a,b],comparisons:[{id:'cmp-12345678',first:a,second:b,created:'2026-09-19',note:'Август и сентябрь'}]}]});
  assert.equal(clean.plants[0].comparisons.length,1);
  assert.equal(C.sanitizeBackup(JSON.parse(JSON.stringify(clean))).plants[0].comparisons[0].note,'Август и сентябрь');
});
test('v1.4: некорректные сравнения и удалённые фотографии не восстанавливаются',()=>{
  const a='01234567-89ab-4cde-8f01-234567890abc',b='11234567-89ab-4cde-8f01-234567890abc';
  const clean=C.sanitizeBackup({version:1,completed:[],plants:[{id:'p',name:'Сад',photos:[a,b],comparisons:[
    {id:'cmp-12345678',first:a,second:b,note:'Хорошо'},
    {id:'cmp-12345678',first:a,second:b,note:'Дубликат'},
    {id:'cmp-87654321',first:a,second:a},
    {id:'cmp-abcdefgh',first:a,second:'21234567-89ab-4cde-8f01-234567890abc'}]}]});
  assert.equal(clean.plants[0].comparisons.length,1);
});
test('v1.4: календарь цветения проверяет годы, даты и порядок',()=>{
  const cleaned=C.sanitizeBloomYears([{year:2025,start:'2025-07-02',end:'2025-08-12',note:'Цвёл долго'},
    {year:2026,start:'2026-09-01',end:'2026-08-01'},
    {year:2025,start:'2025-06-01'},
    {year:2024,start:'2025-07-02'}]);
  assert.equal(cleaned.length,1);
  assert.equal(cleaned[0].note,'Цвёл долго');
});
test('v1.4: календарь учитывает датированные фотографии, но не выдаёт их за границы цветения',()=>{
  const a='01234567-89ab-4cde-8f01-234567890abc',b='11234567-89ab-4cde-8f01-234567890abc';
  const p={photos:[a,b],photoMeta:{[a]:{day:'2025-07-12',stage:'Цветение'},[b]:{day:'2026-08-13',stage:'Цветение'}},bloomYears:[{year:2025,start:'2025-07-01',end:'2025-08-20',note:''}]};
  const timeline=C.bloomTimeline(p);
  assert.equal(timeline.length,2);
  assert.equal(timeline[0].year,2026);
  assert.equal(timeline[0].firstPhoto,'2026-08-13');
  assert.equal(timeline[0].start,'');
  assert.equal(timeline[1].start,'2025-07-01');
});
test('v1.4: старые резервные копии импортируются с пустым календарём и сравнениями',()=>{
  const clean=C.sanitizeBackup({version:1,completed:[],plants:[{id:'p',name:'Сад'}]});
  assert.deepEqual(clean.plants[0].bloomYears,[]);
  assert.deepEqual(clean.plants[0].comparisons,[]);
});

test('v1.4: интерфейс показывает календарь и сохранённое сравнение',()=>{
 const a='01234567-89ab-4cde-8f01-234567890abc',b='11234567-89ab-4cde-8f01-234567890abc';
 const stored={'gortenziya_moy_sad_v1':JSON.stringify({version:1,completed:[],plants:[{id:'p',name:'Мой куст',photos:[a,b],comparisons:[{id:'cmp-12345678',first:a,second:b,created:'2026-09-18',note:'Первый и второй год'}],bloomYears:[{year:2026,start:'2026-07-01',end:'2026-09-01',note:'Много цветов'}]}]})};
 const ctx={window:{GardenCore:C},console,Date,Math,JSON,URL,Blob,setTimeout:()=>1,clearTimeout:()=>{},localStorage:{getItem:k=>stored[k]||null,setItem:(k,v)=>{stored[k]=v;}},FormData:class{constructor(form){this.values=form.values||{};}get(key){return this.values[key]||'';}}};
 class El{constructor(){this.innerHTML='';this.classList={toggle:()=>{},add:()=>{},remove:()=>{},contains:()=>true};this.dataset={};this.handlers={};}addEventListener(n,f){this.handlers[n]=f;}querySelectorAll(){return [new El(),new El(),new El()];}querySelector(){return null;}setAttribute(){}}
 const elems={main:new El(),overlay:new El(),tabs:new El(),toast:new El(),'backup-file':new El()};
 ctx.document={getElementById:id=>elems[id]};ctx.window.scrollTo=()=>{};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(root,'content.js'),'utf8'),ctx);vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),ctx);
 elems.tabs.handlers.click({target:{closest:()=>({dataset:{tab:'plants'}})}});
 elems.main.handlers.click({target:{closest:()=>({dataset:{action:'open-plant',id:'p'}})}});
 assert.match(elems.main.innerHTML,/Сохранённые сравнения/);assert.match(elems.main.innerHTML,/Первый и второй год/);
 assert.match(elems.main.innerHTML,/Цветение по годам/);assert.match(elems.main.innerHTML,/Много цветов/);
 elems.main.handlers.click({target:{closest:()=>({dataset:{action:'edit-bloom',id:'p',year:'2026'}})}});
 assert.match(elems.overlay.innerHTML,/Начало цветения/);
 elems.overlay.handlers.submit({preventDefault(){},target:{id:'bloom-form',dataset:{id:'p',year:'2026'},values:{start:'2026-07-01',end:'2026-09-02',note:'Обильное'}}});
 assert.equal(JSON.parse(stored['gortenziya_moy_sad_v1']).plants[0].bloomYears[0].note,'Обильное');
});

test('v1.6: фото-справочник содержит 12 сортов и локальные встроенные фотографии',()=>{
 const ctx={window:{},console};vm.createContext(ctx);
 vm.runInContext(fs.readFileSync(path.join(root,'content.js'),'utf8'),ctx);
 const vs=ctx.window.GardenContent.varieties;
 assert.equal(vs.length,12);
 assert.equal(vs.filter(v=>v.photo).length,12);
 for(const v of vs){
   assert.match(v.photo,/^catalog_photos\//);
 }
 assert.ok(vs.filter(v=>v.onlinePhotoSource).length>=8);
 assert.equal(vs.find(v=>v.name==='Quick Fire').photo,'catalog_photos/quick_fire.jpg');
});
test('v1.5: ссылки на личные фото сортов валидируются и резервируются',()=>{
 const id='01234567-89ab-4cde-8f01-234567890abc';
 const backup=C.sanitizeBackup({version:1,plants:[],customVarieties:[],completed:[],catalogPhotos:{b0:id}});
 assert.equal(backup.catalogPhotos.b0,id);
 assert.deepEqual(Object.keys(C.sanitizeBackup({version:1,plants:[],completed:[]}).catalogPhotos),[]);
 assert.throws(()=>C.sanitizeCatalogPhotos({'../../secret':id}));
 assert.throws(()=>C.sanitizeCatalogPhotos({'b0':'../../photo.jpg'}));
 assert.equal(C.sanitizeCatalogPhotos({'b100':id}).b100,id);
 assert.throws(()=>C.sanitizeCatalogPhotos({'b999':id}));
 assert.throws(()=>C.sanitizeCatalogPhotos(Object.fromEntries(Array.from({length:210},(_,i)=>['b'+i,id]))));
});
test('v1.6: навигация фото-справочника показывает встроенные фото и позволяет выбрать локальное фото',()=>{
 const storage={},picked=[];
 const ctx={window:{GardenCore:C,GardenAndroid:{cloudConfigured:()=>false,pickPhoto:id=>picked.push(id),deleteLocalPhoto:()=>{}}},console,Date,Math,JSON,URL,Blob,setTimeout:()=>1,clearTimeout:()=>{},
   localStorage:{getItem:k=>storage[k]||null,setItem:(k,v)=>{storage[k]=v;}},
   FormData:class{constructor(form){this.values=form.values;}get(key){return this.values[key]||'';}}
 };
 class El{constructor(){this.innerHTML='';this.classList={toggle:()=>{},add:()=>{},remove:()=>{},contains:()=>true};this.dataset={};this.handlers={};}
   addEventListener(name,fn){this.handlers[name]=fn;} querySelectorAll(){return [new El(),new El(),new El()];}querySelector(){return null;}setAttribute(){} }
 const elems={main:new El(),overlay:new El(),tabs:new El(),toast:new El(),'backup-file':new El()};
 ctx.document={getElementById:id=>elems[id]};ctx.window.scrollTo=()=>{};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(root,'content.js'),'utf8'),ctx);
 vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),ctx);
 const act=(action,id='')=>elems.main.handlers.click({target:{closest:()=>({dataset:{action,id}})}});
 elems.tabs.handlers.click({target:{closest:()=>({dataset:{tab:'guide'}})}});
 act('guide-mode','sort');
 assert.match(elems.main.innerHTML,/Фото-справочник сортов/);
 assert.match(elems.main.innerHTML,/<img class="catalog-photo" src="catalog_photos\//);
 act('view-variety','b0');
 assert.match(elems.main.innerHTML,/Описание сорта/);
 assert.match(elems.main.innerHTML,/встроенн/i);
 act('catalog-pick','b0');assert.deepEqual(picked,['catalog:b0']);
 ctx.window.nativePhotoAdded('catalog:b0','01234567-89ab-4cde-8f01-234567890abc');
 assert.equal(JSON.parse(storage['gortenziya_moy_sad_v1']).catalogPhotos.b0,'01234567-89ab-4cde-8f01-234567890abc');
 assert.match(elems.main.innerHTML,/Ваше фото/);
 act('catalog-remove','b0');
 assert.equal(JSON.parse(storage['gortenziya_moy_sad_v1']).catalogPhotos.b0,undefined);
});

test('v1.7: в расширенном каталоге есть научные названия и культурные формы нескольких видов',()=>{
 const ctx={window:{},console};vm.createContext(ctx);
 vm.runInContext(fs.readFileSync(path.join(root,'content.js'),'utf8'),ctx);
 vm.runInContext(fs.readFileSync(path.join(root,'catalog_expanded.js'),'utf8'),ctx);
 const d=ctx.window.GardenContent;
 assert.ok(d.speciesList.length>=98);
 assert.ok(d.varieties.length>=100);
 for(const name of ['Hydrangea paniculata','Hydrangea macrophylla','Hydrangea arborescens','Hydrangea quercifolia','Hydrangea serrata']){
   assert.ok(d.speciesList.some(s=>s.latin===name));
   assert.ok(d.varieties.some(v=>v.species===name));
 }
 assert.equal(d.varieties.slice(0,12).every(v=>v.species==='Hydrangea paniculata'),true);
 assert.equal(new Set(d.speciesList.map(s=>s.latin)).size,d.speciesList.length);
});
test('v1.7: расширенный справочник выбирает виды и открывает карточки без выдуманных фото',()=>{
 const storage={},ctx={window:{GardenCore:C},console,Date,Math,JSON,URL,Blob,setTimeout:()=>1,clearTimeout:()=>{},
   localStorage:{getItem:k=>storage[k]||null,setItem:(k,v)=>{storage[k]=v;}},
   FormData:class{constructor(form){this.values=form.values||{};}get(k){return this.values[k]||'';}}};
 class El {constructor(){this.innerHTML='';this.classList={toggle:()=>{},add:()=>{},remove:()=>{},contains:()=>true};this.dataset={};this.handlers={};}
   addEventListener(n,f){this.handlers[n]=f;}querySelectorAll(){return [new El(),new El(),new El()];}querySelector(){return null;}setAttribute(){} }
 const elems={main:new El(),overlay:new El(),tabs:new El(),toast:new El(),'backup-file':new El()};
 ctx.document={getElementById:id=>elems[id]};ctx.window.scrollTo=()=>{};
 vm.createContext(ctx);
 for(const file of ['content.js','catalog_expanded.js','app.js'])vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),ctx);
 const act=(action,id='')=>elems.main.handlers.click({target:{closest:()=>({dataset:{action,id}})}});
 elems.tabs.handlers.click({target:{closest:()=>({dataset:{tab:'guide'}})}});
 act('guide-mode','species');assert.match(elems.main.innerHTML,/Ботанические виды и гибриды/);
 act('species-varieties','Hydrangea quercifolia');assert.match(elems.main.innerHTML,/Snow Queen/);
 assert.doesNotMatch(elems.main.innerHTML,/Bobo/);
 const newVar=ctx.window.GardenContent.varieties.findIndex(v=>v.name==='Snow Queen');
 act('view-variety','b'+newVar);assert.match(elems.main.innerHTML,/Snow Queen/);
 assert.match(elems.main.innerHTML,/Фото пока нет/);
});
console.log(`ИТОГО: ${total} тестов пройдено`);
