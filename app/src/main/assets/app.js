(() => {
'use strict';
const C = window.GardenCore;
const D = window.GardenContent;
const STORE = 'gortenziya_moy_sad_v1';
const main = document.getElementById('main');
const overlay = document.getElementById('overlay');
const tabs = document.getElementById('tabs');
let current = 'today';
let article = '';
let plantId = '';
let month = new Date().getMonth();
let guideMode = 'care';
let varietyFilter = 'Все';
let varietySearch = '';
let speciesFilter = 'Все виды';
let speciesSearch = '';
let speciesShown = 30;
let varietyShown = 30;
let selectedVariety = '';
let externalPhotosEnabled = false;
let plantFilter = 'Все';
let plantQuery = '';
let comparePhotos = [];
let comparePlantId = '';
let galleryFilter = 'Все';
let plantDraft = null;
let editingVariety = '';
let returningToPlant = false;
let noticeTimer = null;
let reminderEnabled = false;
let data = readState();
let galleryItems = [];
let galleryBusy = false;
let galleryError = '';
let uploadPhoto = '';
let uploadPlant = '';
const onlineAvailable = !!(window.GardenAndroid && window.GardenAndroid.cloudConfigured && window.GardenAndroid.cloudConfigured());
let cloudCallbacks = {};
let cloudSeq = 0;
function cloud(action, body={}) {
  if (!onlineAvailable) { toast('Общий альбом пока не подключён администратором'); return Promise.reject(Error('Общий альбом не подключён')); }
  return new Promise((resolve,reject)=>{
    const id='r'+(++cloudSeq);
    cloudCallbacks[id]={resolve,reject};
    window.GardenAndroid.cloud(action, JSON.stringify(body), id);
  });
}
window.cloudResponse = (id, json) => {
  const cb=cloudCallbacks[id]; if(!cb)return; delete cloudCallbacks[id];
  try {const result=JSON.parse(json);if(result.ok)cb.resolve(result);else cb.reject(Error(result.error||'Ошибка сети'));}
  catch(e){cb.reject(e);}
};
window.nativePhotoAdded = (id, photo) => {
  if(id.startsWith('catalog:')){
    const key=id.slice(8);
    if(!isCatalogKey(key)){window.GardenAndroid?.deleteLocalPhoto(photo);return;}
    const previous=data.catalogPhotos[key];
    data.catalogPhotos[key]=photo;save();
    if(previous && previous!==photo)window.GardenAndroid?.deleteLocalPhoto(previous);
    guideMode='sort';selectedVariety=key;go('guide');toast('Фото сорта сохранено только на вашем устройстве');return;
  }
  const p=data.plants.find(x=>x.id===id);
  if(!p){if(window.GardenAndroid)window.GardenAndroid.deleteLocalPhoto(photo);return;}
  p.photos=Array.isArray(p.photos)?p.photos:[];
  if(p.photos.length>=12){window.GardenAndroid.deleteLocalPhoto(photo);toast('Не больше 12 фотографий на куст');return;}
  p.photos.push(photo);p.photoMeta=p.photoMeta||{};p.photoMeta[photo]={day:today(),stage:'Не указана',note:''};save();go('plants',{plant:id});photoSheet(id,photo);toast('Фото добавлено — укажите дату и этап роста');
};
window.nativePhotoError = text => toast(text||'Не удалось добавить фотографию');
function localPhotoUrl(id){return /^[-a-f0-9]{36}$/.test(id)?'https://garden.local/photo/'+id+'.jpg':'';}
function picture(id,label='Фотография гортензии'){
  const src=localPhotoUrl(id);return src?`<img class="plant-photo" src="${src}" alt="${attr(label)}" loading="lazy" onerror="this.style.display='none'"/>`:'';
}


function readState() {
  try { const raw = localStorage.getItem(STORE); return raw ? C.sanitizeBackup(JSON.parse(raw)) : {version:1,plants:[],customVarieties:[],catalogPhotos:{},completed:[]}; }
  catch(err) { return {version:1,plants:[],customVarieties:[],catalogPhotos:{},completed:[]}; }
}
function save() { localStorage.setItem(STORE, JSON.stringify(data)); }
function allVarieties(){ return [...D.varieties,...data.customVarieties]; }
function catalogKey(v){const i=D.varieties.indexOf(v);return v.id|| (i>=0?'b'+i:'');}
function isCatalogKey(key){return D.varieties.some(v=>catalogKey(v)===key)||data.customVarieties.some(v=>v.id===key);}
function catalogImage(v){
 const key=catalogKey(v),local=data.catalogPhotos?.[key];
 if(local)return {url:localPhotoUrl(local),credit:'Ваше фото · хранится на телефоне',kind:'local'};
 if(v.photo && !/^https?:\/\//.test(v.photo))
   return {url:v.photo,credit:v.photoCredit||'Встроенное фото-иллюстрация гортензии',kind:'bundled'};
 if(externalPhotosEnabled && v.onlinePhoto && /^https:\/\/commons\.wikimedia\.org\/wiki\/Special:FilePath\//.test(v.onlinePhoto))
   return {url:v.onlinePhoto,credit:'Фото: '+v.onlinePhotoAuthor+' · '+v.onlinePhotoLicense+' · Wikimedia Commons',kind:'commons'};
 if(v.onlinePhotoSource)
   return {url:'',credit:'Для этого сорта доступны встроенное фото и страница с точным онлайн-снимком в Wikimedia Commons.',kind:'none'};
 return {url:'',credit:'У этого сорта пока нет фотографии. Добавьте свою.',kind:'none'};
}
function catalogPicture(v){
 const pic=catalogImage(v);
 return pic.url?`<img class="catalog-photo" src="${attr(pic.url)}" alt="${attr(v.name)} — ${pic.kind==='local'?'фотография пользователя':'справочное фото сорта'}" loading="lazy" referrerpolicy="no-referrer" onerror="this.hidden=true;this.nextElementSibling.hidden=false"/><div class="catalog-placeholder" hidden>Фотография недоступна</div>`:
 '<div class="catalog-placeholder"><span aria-hidden="true">❀</span><small>Фото пока нет</small></div>';
}

function varietyExists(name, ignoreId=''){const n=C.normalizedVarietyName(name);return allVarieties().some(v=>v.id!==ignoreId&&C.normalizedVarietyName(v.name)===n);}
function esc(value) { return String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function attr(s) { return esc(s); }
const symbol = {
  droplet:'♧',leaf:'✿',sprout:'❧',calendar:'▦',flower:'❀',scissors:'✂',shield:'◇',sparkles:'✧',
  sun:'☀',snow:'❄',search:'⌕',bug:'♧',heart:'♡',check:'✓',clock:'◷',settings:'⚙',note:'☰',plant:'❀'
};
function glyph(icon='leaf', theme='') { return `<span class="glyph ${theme}" aria-hidden="true">${symbol[icon]||symbol.leaf}</span>`; }
function dayLabel(day) {
  const d = C.parseDay(day); return d ? `${d.getDate()} ${C.MONTHS[d.getMonth()]} ${d.getFullYear()}` : 'Не указано';
}
function nowTitle(){const d=new Date();return `${d.getDate()} ${C.MONTHS[d.getMonth()]} · ${['вс','пн','вт','ср','чт','пт','сб'][d.getDay()]}`;}
function today(){return C.dateKey(new Date());}
function toast(text){
  const target=document.getElementById('toast');target.textContent=text;target.classList.add('show');
  clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>target.classList.remove('show'),2600);
}
function go(tab, options={}) {
  current=tab;article=options.article||'';plantId=options.plant||'';
  if(tab!=='guide')selectedVariety='';
  if(typeof options.month === 'number') month=options.month;
  render();window.scrollTo(0,0);
}
window.gardenBack=()=>{
  if(!overlay.classList.contains('hidden')){closeSheet();return;}
  if(plantId){go('plants');return;}
  if(selectedVariety){selectedVariety='';go('guide');return;}
  if(article){go('guide');return;}
  if (current !== 'today') {go('today');return 'home';}
  return 'exit';
};
function header() {
  return `<div class="topbar"><div><div class="eyebrow">ВАШ ЦВЕТУЩИЙ САД</div><div class="app-name">Гортензия <span style="color:#cb93a9">✿</span></div></div><button class="circle-button avatar" data-action="open-settings" aria-label="Настройки">❀</button></div>`;
}
function flowerIllustration() {
  return `<svg viewBox="0 0 170 200" role="img" aria-label="Рисунок метельчатой гортензии" xmlns="http://www.w3.org/2000/svg">
  <path d="M86 188Q91 131 91 80" stroke="#8cab81" stroke-width="5" fill="none" stroke-linecap="round"/>
  <path d="M85 158Q31 134 14 146Q49 183 85 158Z" fill="#80a47f"/><path d="M89 151Q133 121 158 133Q134 169 89 151Z" fill="#a3be8d"/>
  <path d="M84 119Q46 101 28 106Q52 127 83 119Z" fill="#85ac82"/><path d="M91 121Q122 92 144 103Q131 120 91 121Z" fill="#c1d2a2"/>
  <path d="M88 11 C58 29 39 63 46 91 C52 117 71 133 88 135 C114 130 133 104 129 76 C125 51 109 28 88 11Z" fill="#e7b6cb" opacity=".85"/>
  <g fill="#fff2f5" stroke="#ebcad8" stroke-width=".8">${[[85,30],[72,46],[95,46],[58,65],[77,68],[101,68],[118,69],[52,85],[70,87],[90,89],[109,91],[126,86],[65,107],[86,110],[106,110],[89,126]].map(([x,y],i)=>`<g transform="translate(${x} ${y})"><ellipse rx="7" ry="4.7" cy="-5"/><ellipse rx="7" ry="4.7" cy="5"/><ellipse rx="4.7" ry="7" cx="-5"/><ellipse rx="4.7" ry="7" cx="5"/><circle r="2.2" fill="${i%3===0?'#d39bad':'#e7c8a6'}" stroke="none"/></g>`).join('')}</g>
  <g fill="#e8d6e2" opacity=".78"><circle cx="91" cy="52" r="2"/><circle cx="63" cy="78" r="2"/><circle cx="115" cy="103" r="2"/></g></svg>`;
}
function plantArt(){return `<div class="plant-illustration">${flowerIllustration()}</div>`;}
function hero() {
  const d = new Date(); const m=d.getMonth();
  const phase = m<=1||m===11?'Зимний покой':m<=4?'Пробуждение сада':m<=7?'Сезон роста и цветения':'Готовимся к холодам';
  const title = m<=1||m===11?'Пусть ваш сад отдыхает':m<=4?'Время новых побегов':m<=7?'Время пышных соцветий':'Осень в вашем саду';
  const desc = m<=1||m===11?'Проверьте укрытие и берегите ветви от тяжёлого снега.':m<=4?'Наблюдайте за кустами, почвой и погодой — весенний уход начинается с осмотра.':m<=7?'Проверяйте влажность грунта, любуйтесь цветением и отмечайте заботу о кустах.':'Наблюдайте за листьями и соцветиями, постепенно готовьте растения к зиме.';
  return `<div class="date-line">${esc(nowTitle())}</div><section class="hero"><div class="hero-art">${flowerIllustration()}</div><div class="hero-kicker">✧ ${phase}</div><h1>${title}</h1><p>${desc}</p><span class="hero-tag">🌿 Советы по сезону</span></section>`;
}
function careCard(task, idx, calendarMonth=new Date().getMonth(), now=new Date()) {
  const key=C.checklistKey(task.id,calendarMonth,now.getFullYear());
  const done=data.completed.includes(key);
  return `<article class="card care-card ${done?'done':''}">${glyph(task.icon,idx%3===1?'rose':idx%3===2?'cream':'')}<div class="care-text"><h3>${esc(task.title)}</h3><p>${esc(task.note)}</p></div><button class="check ${done?'checked':''}" data-action="toggle-task" data-key="${attr(key)}" aria-label="${done?'Отменить выполнение':'Отметить выполненным'}: ${attr(task.title)}">${done?'✓':''}</button></article>`;
}
function plantCard(p) {
  const status=C.moistureStatus(p), sub=p.variety||'Сорт не указан';
  return `<button class="card plant-card" style="width:100%;text-align:left;color:inherit" data-action="open-plant" data-id="${attr(p.id)}">${p.photos?.length?picture(p.photos[p.photos.length-1],p.name):plantArt()}<div class="care-text"><h3 class="clipped">${esc(p.name)}</h3><p class="clipped">${esc(sub)}${p.place?' · '+esc(p.place):''}</p><span class="small-status ${status.due?'attention':''}">${status.due?'◷ Проверьте почву':'✓ Влажность проверена'}</span></div><span class="chevron">›</span></button>`;
}
function todayPage() {
  const d=new Date(),m=d.getMonth(), tasks=D.tasks[m], outstanding=tasks.filter(t=>!data.completed.includes(C.checklistKey(t.id,m,d.getFullYear())));
  const due=data.plants.filter(p=>C.moistureStatus(p,d).due);
  return `${header()}${hero()}
  <div class="section-head"><h2>Сегодня в саду</h2><span class="pill">${outstanding.length+due.length} дел</span></div>
  ${due.slice(0,4).map(p=>`<article class="card care-card">${glyph('droplet')}<div class="care-text"><h3>Проверить влажность: ${esc(p.name)}</h3><p>Коснитесь карточки, чтобы записать результат осмотра.</p></div><button class="check" aria-label="Перейти к растению" data-action="open-plant" data-id="${attr(p.id)}">›</button></article>`).join('')}
  ${outstanding.slice(0,3).map((t,i)=>careCard(t,i,m,d)).join('')}
  ${outstanding.length+due.length===0?`<div class="empty"><span class="large-emoji">🌸</span><h3>Все дела отмечены</h3><p>Загляните в календарь, если хотите посмотреть задачи на другие месяцы.</p></div>`:''}
  <div class="section-head"><h2>Мои гортензии</h2><button class="aux" data-action="go-plants">${data.plants.length?'Смотреть все →':'Добавить +'} </button></div>
  ${data.plants.length?data.plants.slice(0,2).map(plantCard).join(''):`<div class="empty"><span class="large-emoji">🌿</span><h3>Посадим первую?</h3><p>Добавьте свою гортензию, чтобы сохранять историю ухода и получать подсказки для каждого куста.</p><button class="btn btn-primary" data-action="add-plant">+ Добавить гортензию</button></div>`}
  <div class="section-head"><h2>Полезно знать</h2></div><div class="action-card">${glyph('sprout')}<div style="flex:1"><h3>Не поливайте по расписанию</h3><p>Сначала проверьте почву — после дождя полив может быть лишним.</p></div><button data-action="guide-article" data-id="watering">Читать</button></div>`;
}
function plantsPage() {
  const due=data.plants.filter(p=>C.moistureStatus(p).due).length;
  const matched=C.filterPlants(data.plants,plantQuery,plantFilter);
  return `${header()}<h1 class="page-title">Мой сад</h1><p class="sub-title">У каждого куста — своя история, особенности и уход.</p>
  <div class="stats"><div class="stat"><strong>${data.plants.length}</strong><span>гортензий в саду</span></div><div class="stat"><strong>${due}</strong><span>проверок влажности</span></div></div>
  <form id="plant-search-form" class="search-row"><input class="input" name="query" maxlength="80" value="${attr(plantQuery)}" aria-label="Поиск по кустам, сортам и месту" placeholder="Название, сорт или место…"/><button class="btn btn-primary" type="submit">Найти</button></form>
  <div class="filter-row">${['Все','Проверить почву','С фотографиями'].map(f=>`<button class="filter ${f===plantFilter?'selected':''}" data-action="plant-filter" data-filter="${attr(f)}">${esc(f)}</button>`).join('')}</div>
  <p class="muted tiny">Найдено: ${matched.length}${plantQuery?` · <button class="text-button" data-action="clear-plant-search">Сбросить поиск</button>`:''}</p>
  ${matched.map(plantCard).join('')}
  ${!data.plants.length?`<div class="empty"><span class="large-emoji">🌸</span><h3>Здесь будет ваша коллекция</h3><p>Добавьте сорт, дату посадки и место в саду — всё сохранится на телефоне.</p></div>`:!matched.length?`<div class="empty"><h3>Ничего не найдено</h3><p>Измените запрос или выберите другой фильтр.</p></div>`:''}
  <button class="btn btn-primary btn-block" data-action="add-plant" style="margin-top:7px">+ Добавить гортензию</button>`;
}
function plantDetail() {
  const p=data.plants.find(x=>x.id===plantId);if(!p)return plantsPage();
  const moisture=C.moistureStatus(p),history=(p.history||[]).slice().reverse();
  return `<div class="header-row"><button class="back" data-action="go-plants" aria-label="Вернуться">←</button><div class="eyebrow">МОЙ САД · КАРТОЧКА КУСТА</div></div>
    <div class="detail-banner"><div><h2>${esc(p.name)}</h2><p>${esc(p.variety||'Метельчатая гортензия')}</p><span class="pill">${esc(p.place||'Место не указано')}</span></div>${p.photos?.length?picture(p.photos[p.photos.length-1],p.name):plantArt()}</div>
    <div class="card"><div class="mini-label">СОСТОЯНИЕ ПОЧВЫ</div><h3 style="font-size:17px;margin:8px 0">${esc(moisture.text)}</h3><p class="intro">${esc(moisture.secondary)}. Последняя проверка: ${p.lastCheck?dayLabel(p.lastCheck):'ещё не было'}.</p><div class="btn-row"><button class="btn btn-primary" data-action="moisture" data-id="${attr(p.id)}">Проверить почву</button><button class="btn btn-outline" data-action="water" data-id="${attr(p.id)}">+ Полив</button></div></div>
    <div class="section-head"><h2>Фотоистория</h2><span class="pill">${p.photos?.length||0} из 12</span></div>
    <p class="intro">Укажите дату, этап роста и заметку: так можно сравнивать цветение по сезонам. Личные фотографии не публикуются автоматически.</p>
    <div class="photo-grid">${C.photoTimeline(p).map(photo=>`<div class="photo-tile">${picture(photo.id,p.name)}<div class="photo-info"><strong>${photo.day?dayLabel(photo.day):'Дата не указана'}</strong><small>${esc(photo.stage)}</small>${photo.note?`<small class="photo-note">${esc(photo.note)}</small>`:''}</div><div class="photo-tools"><button data-action="edit-photo" data-id="${attr(p.id)}" data-photo="${attr(photo.id)}">Описание</button><button data-action="share-photo" data-id="${attr(p.id)}" data-photo="${attr(photo.id)}">В альбом</button><button data-action="delete-photo" data-id="${attr(p.id)}" data-photo="${attr(photo.id)}" aria-label="Удалить фото">✕</button></div></div>`).join('')}</div>
    <button class="btn btn-primary btn-block" data-action="add-photo" data-id="${attr(p.id)}" ${p.photos?.length>=12?'disabled':''}>+ Добавить фотографию</button>
    ${(p.photos||[]).length>=2?`<button class="btn btn-outline btn-block" data-action="compare-photos" data-id="${attr(p.id)}">⇆ Сравнить два снимка</button>`:''}
    ${savedComparisons(p)}
    ${bloomCalendar(p)}
    <div class="section-head"><h2>Записи об уходе</h2></div>
    <div class="plant-actions"><button class="plant-action" data-action="log" data-kind="feed" data-id="${attr(p.id)}"><span>✧</span>Подкормка</button><button class="plant-action" data-action="log" data-kind="prune" data-id="${attr(p.id)}"><span>✂</span>Обрезка</button><button class="plant-action" data-action="log" data-kind="mulch" data-id="${attr(p.id)}"><span>❧</span>Мульча</button></div>
    ${history.length?history.slice(0,12).map(h=>`<div class="history-item"><strong>${esc(historyLabel(h.kind))}</strong><small>${dayLabel(h.day)}${h.note?' · '+esc(h.note):''}</small></div>`).join(''):`<div class="card muted tiny">Пока нет записей. Отмечайте проверки почвы и выполненные работы — здесь появится история.</div>`}
    <hr class="divider"/><div class="btn-row"><button class="btn btn-outline" data-action="edit-plant" data-id="${attr(p.id)}">Изменить куст</button><button class="btn btn-danger" data-action="delete-plant" data-id="${attr(p.id)}">Удалить</button></div>
    ${p.planted?`<p class="source-note">Дата посадки: ${dayLabel(p.planted)}${p.notes?'<br/>Заметки: '+esc(p.notes):''}</p>`:p.notes?`<p class="source-note">${esc(p.notes)}</p>`:''}`;
}
function historyLabel(kind){return ({water:'Полив',moisture:'Проверка влажности',feed:'Подкормка',prune:'Обрезка',mulch:'Мульчирование',note:'Наблюдение'})[kind]||'Уход';}
function calendarPage(){
  const year=new Date().getFullYear(), tasks=D.tasks[month];
  const done=tasks.filter(t=>data.completed.includes(C.checklistKey(t.id,month,year))).length;
  return `${header()}<h1 class="page-title">Календарь ухода</h1><p class="sub-title">Не жёсткое расписание, а сезонные ориентиры. Учитывайте погоду и состояние кустов.</p>
  <div class="month-hero"><div class="mini-label">СЕЗОННЫЕ ЗАДАЧИ · ${year}</div><h2>${C.MONTH_LABELS[month]}</h2><p>${done} из ${tasks.length} задач отмечено</p></div>
  <div class="filter-row">${C.MONTH_LABELS.map((s,i)=>`<button class="filter ${i===month?'selected':''}" data-action="month" data-month="${i}">${s}</button>`).join('')}</div>
  ${tasks.map((t,i)=>careCard(t,i,month,new Date(year,month,1))).join('')}
  <div class="tip">☀ Сроки приблизительны и ориентированы на климат средней полосы. В тёплых и холодных регионах ориентируйтесь прежде всего на погоду, состояние грунта и фазу роста растения.</div>`;
}
function guidePage() {
  if(selectedVariety && guideMode==='sort'){const found=allVarieties().find(v=>catalogKey(v)===selectedVariety);if(found)return varietyDetail(found);selectedVariety='';}
  if(article) return articlePage();
  const choices=[['care','Уход'],['sort','Сорта'],['species','Виды'],['problem','Проблемы']];
  return `${header()}<h1 class="page-title">Справочник</h1><p class="sub-title">Каталог видов и культурных форм. Практические советы ниже относятся прежде всего к метельчатой гортензии.</p>
  <div class="segment">${choices.map(([id,label])=>`<button class="${guideMode===id?'active':''}" data-action="guide-mode" data-id="${id}">${label}</button>`).join('')}</div>
  <div style="height:18px"></div>
  ${guideMode==='care'?D.guides.map(g=>`<button class="list-card" data-action="guide-article" data-id="${g.id}">${glyph(g.icon)}<span style="flex:1"><strong>${esc(g.title)}</strong><small>${esc(g.sub)}</small></span><span class="chevron">›</span></button>`).join(''):
    guideMode==='sort'?varietiesView():guideMode==='species'?speciesView():problemsView()}
  <div class="source-note">Практические советы по уходу адаптированы из приложенного пособия о метельчатой гортензии. У остальных видов обрезка, зимовка и требования к почве могут существенно отличаться. Названия видов: Kew POWO; названия культурных форм: RHS. Уточняйте актуальные ботанические наименования и условия ухода.</div>`;
}
function varietiesView(){
  const opts=['Все','Мои сорта','Компактный','Ранний','Поздний','Высокий'];
  const query=C.normalizedVarietyName(varietySearch);
  const matched=allVarieties().filter(v=>(varietyFilter==='Все'||(varietyFilter==='Мои сорта'&&!!v.id)||v.tag===varietyFilter||v.bloom===varietyFilter) && (speciesFilter==='Все виды'||v.species===speciesFilter) && (!query || C.normalizedVarietyName([v.name,v.species,v.color,v.tag,v.notes].join(' ')).includes(query)));
  const shown=matched.slice(0,varietyShown);
  return `<div class="card"><h3>Фото-справочник сортов</h3><p class="intro">В справочник добавлены встроенные фотографии гортензий. Они доступны без интернета. При желании можно заменить фото своим снимком — он останется только на вашем телефоне.</p>
    <p class="muted tiny">У новых карточек нет неподтверждённых фотографий. Для первых 12 приведены иллюстративные снимки, не удостоверяющие точный сорт.</p><button class="btn btn-primary btn-block" data-action="add-variety" style="margin-top:9px">+ Добавить новый сорт</button></div>
    <label class="form-field"><span>Найти сорт</span><input class="input" id="variety-search" placeholder="Название, окраска, особенности" maxlength="80" value="${attr(varietySearch)}" /></label>
    <div class="filter-row">${opts.map(x=>`<button class="filter ${varietyFilter===x?'selected':''}" data-action="variety-filter" data-filter="${attr(x)}">${esc(x)}</button>`).join('')}</div>
    <label class="form-field"><span>Ботанический вид</span><select class="input" id="species-filter"><option value="Все виды">Все виды</option>${[...new Set(allVarieties().map(v=>v.species).filter(Boolean))].sort().map(s=>`<option value="${attr(s)}" ${speciesFilter===s?'selected':''}>${esc(s)}</option>`).join('')}</select></label>
    <p class="intro">Найдено: ${matched.length}. Показано: ${shown.length}.</p>
    ${shown.map(v=>`<article class="variety catalog-card">${catalogPicture(v)}<div class="catalog-body"><div class="top"><h3>${esc(v.name)}</h3><span class="pill">${v.id?'Мой сорт':esc(v.tag)}</span></div>
      <div class="meta">${esc(v.species||'Вид не указан')}<br/>Высота: ${esc(v.height||'Не указана')}<br/>Соцветия: ${esc(v.color||'Не указаны')}<br/>Цветение: ${esc(v.bloom==='Неизвестно'?'не указано':v.bloom.toLowerCase())}</div>
      <button class="btn btn-outline btn-block" data-action="view-variety" data-id="${attr(catalogKey(v))}" style="margin-top:12px">Открыть карточку и фотографии →</button></div></article>`).join('')}
    ${shown.length<matched.length?'<button class="btn btn-outline btn-block" data-action="variety-more">Показать ещё 30 →</button>':''}
    ${!matched.length?'<p class="intro">По вашему запросу сорта не найдены.</p>':''}`;
}
function speciesView(){
 const list=D.speciesList||[];
 const query=C.normalizedVarietyName(speciesSearch);
 const filtered=list.filter(s=>!query||C.normalizedVarietyName(s.latin+' '+s.common).includes(query));
 const shown=filtered.slice(0,speciesShown);
 return `<div class="card"><h3>Ботанические виды и гибриды</h3><p class="intro">Индекс научных названий для поиска. У Kew Plants of the World Online число признанных видов меняется с уточнением таксономии; не все перечисленные названия обязательно имеют статус принятого вида в текущей редакции. Для проверки откройте Kew.</p>
 <button class="btn btn-outline btn-block" data-action="open-kew">Открыть актуальный реестр Kew ↗</button></div>
 <label class="form-field"><span>Поиск вида</span><input class="input" id="species-search" maxlength="80" placeholder="Название по-латыни или по-русски" value="${attr(speciesSearch)}" /></label>
 <p class="intro">В указателе ${list.length} названий. Найдено ${filtered.length}.</p>
 ${shown.map(s=>`<article class="variety"><h3>${esc(s.latin)}</h3><p class="muted tiny">${esc(s.common)}</p><button class="btn btn-outline" data-action="species-varieties" data-id="${attr(s.latin)}">Сорта этого вида →</button></article>`).join('')}
 ${shown.length<filtered.length?'<button class="btn btn-outline btn-block" data-action="species-more">Показать ещё 30 →</button>':''}
 ${!filtered.length?'<p class="intro">Вид не найден. Проверьте написание.</p>':''}`;
}
function varietyDetail(v){
 const pic=catalogImage(v),key=catalogKey(v),count=data.plants.filter(p=>C.normalizedVarietyName(p.variety)===C.normalizedVarietyName(v.name)).length;
 return `<div class="header-row"><button class="back" data-action="variety-back" aria-label="К сортам">←</button><span class="eyebrow">ФОТО-СПРАВОЧНИК · HYDRANGEA PANICULATA</span></div>
 <h1 class="page-title">${esc(v.name)}</h1><p class="intro">${esc(v.species||'Вид не указан')} · ${esc(v.tag||'Культурная форма')}</p><div class="catalog-detail-photo">${catalogPicture(v)}</div>
 <div class="card"><h3>Описание сорта</h3><p class="intro">Высота: ${esc(v.height||'Не указана')}<br/>Окраска: ${esc(v.color||'Не указана')}<br/>Срок цветения: ${esc(v.bloom||'Не указан')}<br/>Особенности: ${esc(v.tag||'Не указаны')}</p>${v.notes?`<p>${esc(v.notes)}</p>`:''}
 <p class="muted tiny">${esc(pic.credit)}</p>
 ${v.onlinePhotoSource?`<button class="text-button" data-action="photo-source" data-id="${attr(key)}">Открыть страницу фото на Wikimedia Commons ↗</button>`:''}
 ${v.reference?`<button class="text-button" data-action="variety-reference" data-id="${attr(key)}">Посмотреть источник названия сорта ↗</button>`:''}
 <div class="btn-row" style="margin-top:15px"><button class="btn btn-primary" data-action="catalog-pick" data-id="${attr(key)}">${data.catalogPhotos[key]?'Заменить моё фото':'+ Добавить моё фото'}</button>
 ${data.catalogPhotos[key]?`<button class="btn btn-danger" data-action="catalog-remove" data-id="${attr(key)}">Удалить моё фото</button>`:''}</div>
 <p class="muted tiny">Личное фото привязано к сорту в справочнике, не публикуется в общем альбоме и не входит в JSON-копию как файл.</p></div>
 <div class="card"><h3>Ваш сад · ${count} ${count===1?'куст':'кустов'}</h3><button class="btn btn-outline btn-block" data-action="add-plant-variety" data-id="${attr(key)}">+ Добавить куст этого сорта</button></div>
 ${v.id?`<button class="btn btn-outline" data-action="edit-variety" data-id="${attr(v.id)}">Изменить описание сорта</button>`:''}`;
}
function problemsView(){return `<p class="intro">Выберите наиболее заметный признак. Подсказки не заменяют осмотр растения и не являются диагнозом.</p>
    ${D.problems.map(p=>`<button class="help-option" data-action="problem" data-id="${p.id}">${glyph(p.icon)}<span style="flex:1">${esc(p.label)}</span><span class="chevron">›</span></button>`).join('')}`;}
function articlePage(){
  const item=D.guides.find(x=>x.id===article),problem=D.problems.find(x=>x.id===article);
  if(problem)return `<div class="header-row"><button class="back" data-action="go-guide" aria-label="Вернуться">←</button><span class="eyebrow">ПОМОЩЬ РАСТЕНИЮ</span></div><div class="article-head">${glyph(problem.icon)}<div><h2>${esc(problem.label)}</h2><p>Возможные причины и первые шаги</p></div></div><div class="card article"><p>${esc(problem.title)}</p><div class="help-answer">${esc(problem.help)}</div><p class="muted tiny">Если проблема быстро распространяется или растение сильно ослабло, обратитесь за местной консультацией в питомник или к специалисту по растениям.</p></div><button class="btn btn-outline" data-action="go-guide">← Назад к справочнику</button>`;
  if(!item)return guidePage();
  return `<div class="header-row"><button class="back" data-action="go-guide" aria-label="Вернуться">←</button><span class="eyebrow">АЗБУКА УХОДА</span></div><div class="article-head">${glyph(item.icon,'rose')}<div><h2>${esc(item.title)}</h2><p>${esc(item.sub)}</p></div></div>
     <div class="card article">${item.text.map(t=>`<p>${esc(t)}</p>`).join('')}</div>
     <div class="source-note">Информация — краткое изложение приложенного пособия, без индивидуальной диагностики и назначения препаратов.</div><button class="btn btn-outline" data-action="go-guide" style="margin-top:13px">← К разделам ухода</button>`;
}
function morePage(){
  return `${header()}<h1 class="page-title">Ещё</h1><p class="sub-title">Настройки, напоминания и сохранность данных.</p>
    <div class="card"><div class="setting"><div><strong>Ежедневное напоминание</strong><small>Уведомление примерно в 9:00: проверить задачи и влажность грунта.</small></div><button class="toggle ${reminderEnabled?'on':''}" role="switch" aria-checked="${reminderEnabled}" aria-label="Ежедневное напоминание" data-action="reminder"></button></div>
    <div class="setting"><div><strong>Резервная копия сада</strong><small>Сохраните растения, собственные сорта, историю и выполненные задачи в JSON-файл.</small></div><button class="btn btn-secondary" data-action="export">Сохранить</button></div>
    <div class="setting" style="border:0"><div><strong>Восстановить данные</strong><small>Загрузка резервной копии заменит текущие записи.</small></div><button class="btn btn-outline" data-action="import">Загрузить</button></div></div>
    <div class="card"><div class="mini-label">О ПРИЛОЖЕНИИ</div><h3 style="margin:10px 0 7px">Гортензия · Мой сад</h3><p class="intro">Версия 1.5 · Для метельчатой гортензии (Hydrangea paniculata). Личный дневник работает без интернета. Фотографии хранятся на этом телефоне и не входят в JSON-копию. Общий альбом доступен только после подключения сервиса и публикации по вашему согласию; анонимный аккаунт общего альбома привязан к устройству.</p></div>
    <div class="source-note">Советы основаны на предоставленном пользователем пособии. Календарь служит напоминанием об осмотре, а не автоматической инструкцией к поливу или применению средств защиты.</div>`;
}
function galleryPage(){
  return `${header()}<h1 class="page-title">Альбом сообщества 🌸</h1>
  <p class="sub-title">Сравнивайте цветение и уход. Фотографии публикуются только по желанию владельца и после проверки модератором.</p>
  <div class="card"><h3>Поделитесь результатом</h3><p class="intro">Откройте «Мой сад» → карточку куста → добавьте фото → «В альбом». Здесь нет личных сообщений, геолокации и публичных контактов.</p>
  ${onlineAvailable?`<button class="btn btn-outline" data-action="gallery-refresh" ${galleryBusy?'disabled':''}>${galleryBusy?'Загрузка…':'Обновить альбом'}</button>`:
  `<p class="intro">Общий альбом будет доступен после подключения владельцем приложения облачного хранилища. Личные фото уже можно сохранять без интернета.</p>`}</div>
  ${galleryError?`<div class="source-note">${esc(galleryError)}</div>`:''}
  ${galleryItems.map(item=>`<article class="card gallery-card">
    ${item.url?`<img class="gallery-image" src="${attr(item.url)}" alt="Метельчатая гортензия сорта ${attr(item.variety||'не указан')}" loading="lazy" referrerpolicy="no-referrer"/>`:'<p class="intro">Фотография временно недоступна.</p>'}
    <div class="row-line"><strong>${esc(item.nickname)}</strong><span class="pill">${esc(item.status==='pending'?'На проверке':item.variety||'Гортензия')}</span></div>
    ${item.caption?`<p class="intro">${esc(item.caption)}</p>`:''}
    <p class="muted tiny">${esc(item.variety||'Сорт не указан')} · ${esc((item.created_at||'').slice(0,10))}</p>
    ${item.mine?`<button class="btn btn-outline" data-action="remove-shared" data-photo="${attr(item.id)}">Удалить публикацию</button>`:
    `<button class="btn btn-outline" data-action="report-shared" data-photo="${attr(item.id)}">Пожаловаться</button>`}
  </article>`).join('')}
  ${onlineAvailable&&!galleryBusy&&!galleryItems.length&&!galleryError?'<p class="intro">Пока нет опубликованных фотографий. Новые фотографии сначала проверяет модератор.</p>':''}`;
}
async function refreshGallery(){
  if(!onlineAvailable)return;
  galleryBusy=true;galleryError='';render();
  try {const result=await cloud('list');galleryItems=Array.isArray(result.items)?result.items:[];}
  catch(e){galleryError=e.message||'Не удалось загрузить альбом';}
  finally{galleryBusy=false;if(current==='gallery')render();}
}
function photoSheet(plantId,photoId){
  const p=data.plants.find(x=>x.id===plantId && (x.photos||[]).includes(photoId));if(!p)return;
  const m=C.photoMetadata(p.photoMeta?.[photoId]);
  openSheet(`<h2 class="sheet-title">Фотография · ${esc(p.name)}</h2>${picture(photoId,p.name)}
    <p class="sheet-description">Дата и этап роста нужны только для вашей фотоистории. Они не публикуются вместе со снимком.</p>
    <form id="photo-form" data-id="${attr(plantId)}" data-photo="${attr(photoId)}">
      <label class="form-field"><span>Дата снимка</span><input class="input" name="day" type="date" max="${today()}" value="${attr(m.day)}" /></label>
      <label class="form-field"><span>Этап роста</span><select class="input" name="stage">${C.PHOTO_STAGES.map(x=>`<option value="${attr(x)}" ${x===m.stage?'selected':''}>${esc(x)}</option>`).join('')}</select></label>
      <label class="form-field"><span>Наблюдения</span><textarea class="input" name="note" maxlength="180" rows="3" placeholder="Размер соцветий, оттенок, погода…">${esc(m.note)}</textarea></label>
      <div class="btn-row"><button class="btn btn-primary" type="submit">Сохранить фотоисторию</button><button type="button" class="btn btn-outline" data-action="close">Отмена</button></div>
    </form>`);
}
function compareSheet(plantId){
  const p=data.plants.find(x=>x.id===plantId);if(!p||p.photos.length<2)return;
  const options=C.photoTimeline(p);
  comparePlantId=plantId;comparePhotos=[options[0].id,options[options.length-1].id];
  openSheet(`<h2 class="sheet-title">До и после · ${esc(p.name)}</h2><p class="sheet-description">Выберите любые два снимка, чтобы сопоставить рост и цветение одного куста.</p>
  <div class="compare-pickers"><label class="form-field"><span>Первый снимок</span><select class="input" data-compare="0">${options.map(photo=>`<option value="${attr(photo.id)}" ${photo.id===comparePhotos[0]?'selected':''}>${esc(photo.day?dayLabel(photo.day):'Без даты')} · ${esc(photo.stage)} · №${photo.index+1}</option>`).join('')}</select></label>
  <label class="form-field"><span>Второй снимок</span><select class="input" data-compare="1">${options.map(photo=>`<option value="${attr(photo.id)}" ${photo.id===comparePhotos[1]?'selected':''}>${esc(photo.day?dayLabel(photo.day):'Без даты')} · ${esc(photo.stage)} · №${photo.index+1}</option>`).join('')}</select></label></div>
  <div id="compare-result"></div><label class="form-field"><span>Название сравнения</span><input id="comparison-note" class="input" maxlength="180" placeholder="Например, цветение 2025 и 2026" /></label><div class="btn-row"><button class="btn btn-primary" data-action="save-comparison" data-id="${attr(plantId)}">Сохранить сравнение</button><button class="btn btn-outline" data-action="close">Закрыть</button></div>`);
  updateComparison(p);
}
function updateComparison(p){
  const target=overlay.querySelector('#compare-result');if(!target)return;
  target.innerHTML=comparePhotos[0]===comparePhotos[1]?'<p class="source-note">Выберите два разных снимка.</p>':
    `<div class="compare-grid">${comparePhotos.map((id,i)=>{const m=C.photoMetadata(p.photoMeta?.[id]);return `<div><div class="compare-label">${i===0?'ДО':'ПОСЛЕ'}</div>${picture(id,p.name)}<strong>${m.day?dayLabel(m.day):'Дата неизвестна'}</strong><small>${esc(m.stage)}</small>${m.note?`<p class="muted tiny">${esc(m.note)}</p>`:''}</div>`;}).join('')}</div>`;
}
function savedComparisons(p){
  const items=p.comparisons||[];
  return `<div class="section-head"><h2>Сохранённые сравнения</h2><span class="pill">${items.length}</span></div>
    ${items.length?items.map(c=>`<div class="saved-comparison card"><div class="saved-heading"><strong>${esc(c.note||'Сравнение фотографий')}</strong><small>${c.created?dayLabel(c.created):'Без даты'}</small></div><div class="saved-thumbs">${picture(c.first,p.name)}${picture(c.second,p.name)}</div><div class="btn-row"><button class="btn btn-outline" data-action="view-comparison" data-id="${attr(p.id)}" data-compare-id="${attr(c.id)}">Открыть</button><button class="btn btn-danger" data-action="delete-comparison" data-id="${attr(p.id)}" data-compare-id="${attr(c.id)}">Удалить</button></div></div>`).join(''):'<p class="intro">Сохраните сравнение двух снимков, чтобы вернуться к нему позднее.</p>'}`;
}
function bloomCalendar(p){
  const rows=C.bloomTimeline(p);
  const currentYear=new Date().getFullYear();
  return `<div class="section-head"><h2>Цветение по годам</h2><button class="aux" data-action="edit-bloom" data-id="${attr(p.id)}" data-year="${currentYear}">+ Записать</button></div>
    <p class="intro">Отмечайте начало и конец цветения самостоятельно. Датированные фото с этапом «Цветение» показываются как наблюдения, но не заменяют даты начала и окончания.</p>
    ${rows.length?rows.map(r=>`<div class="bloom-year card"><div class="saved-heading"><strong>${r.year} год</strong><button class="btn btn-outline" data-action="edit-bloom" data-id="${attr(p.id)}" data-year="${r.year}">Изменить</button></div>
    <div class="bloom-range"><span>Начало: <b>${r.start?dayLabel(r.start):'не отмечено'}</b></span><span>Конец: <b>${r.end?dayLabel(r.end):'не отмечено'}</b></span></div>
    ${r.start&&r.end?`<div class="bloom-duration">Продолжительность: ${C.daysSince(r.start,new Date(r.end+'T12:00:00'))+1} дн.</div>`:''}
    ${r.observations?`<small>Фото цветения: ${r.observations}; первое — ${dayLabel(r.firstPhoto)}, последнее — ${dayLabel(r.lastPhoto)}</small>`:''}
    ${r.note?`<p class="intro">${esc(r.note)}</p>`:''}</div>`).join(''):'<div class="card"><p class="intro">Записей о цветении пока нет. Добавьте дату начала или отметьте этап «Цветение» у фотографии.</p></div>'}`;
}
function bloomSheet(id,year){
  const p=data.plants.find(x=>x.id===id);if(!p)return;
  const y=Number(year),current=new Date().getFullYear();
  if(!Number.isInteger(y)||y<1900||y>current)return;
  const r=(p.bloomYears||[]).find(x=>x.year===y)||{year:y,start:'',end:'',note:''};
  openSheet(`<h2 class="sheet-title">Цветение · ${esc(p.name)}</h2><p class="sheet-description">Запишите наблюдения за ${y} год. Не указывайте предполагаемую дату как фактическую.</p>
  <form id="bloom-form" data-id="${attr(id)}" data-year="${y}">
  <label class="form-field"><span>Начало цветения</span><input class="input" type="date" name="start" min="${y}-01-01" max="${y===current?today():y+'-12-31'}" value="${attr(r.start)}" /></label>
  <label class="form-field"><span>Окончание цветения</span><input class="input" type="date" name="end" min="${y}-01-01" max="${y===current?today():y+'-12-31'}" value="${attr(r.end)}" /></label>
  <label class="form-field"><span>Заметка</span><textarea class="input" maxlength="180" name="note" placeholder="Цвет, обилие соцветий, погода…">${esc(r.note)}</textarea></label>
  <div class="btn-row"><button type="submit" class="btn btn-primary">Сохранить</button>${(p.bloomYears||[]).some(x=>x.year===y)?`<button type="button" class="btn btn-danger" data-action="delete-bloom" data-id="${attr(id)}" data-year="${y}">Удалить запись</button>`:''}</div></form>`);
}
function savedComparisonSheet(id,cmpId){
  const p=data.plants.find(x=>x.id===id),c=p?.comparisons?.find(x=>x.id===cmpId);if(!c)return;
  openSheet(`<h2 class="sheet-title">${esc(c.note||'Сравнение фотографий')}</h2><p class="sheet-description">Сохранено: ${c.created?dayLabel(c.created):'дата не указана'}</p>
  <div class="compare-grid">${[c.first,c.second].map((photo,i)=>{const m=C.photoMetadata(p.photoMeta?.[photo]);return `<div><div class="compare-label">${i?'ПОСЛЕ':'ДО'}</div>${picture(photo,p.name)}<strong>${m.day?dayLabel(m.day):'Дата неизвестна'}</strong><small>${esc(m.stage)}</small>${m.note?`<p class="muted tiny">${esc(m.note)}</p>`:''}</div>`}).join('')}</div><button class="btn btn-outline btn-block" data-action="close">Закрыть</button>`);
}
function sharingSheet(plant, photo){
  if(!onlineAvailable){toast('Владелец приложения ещё не подключил общий альбом');return;}
  const p=data.plants.find(x=>x.id===plant && (x.photos||[]).includes(photo));if(!p)return;
  uploadPlant=plant;uploadPhoto=photo;
  openSheet(`<h2 class="sheet-title">Опубликовать фотографию?</h2>
    ${picture(photo,p.name)}
    <p class="sheet-description">Фото увидят другие пользователи после проверки модератором. Можно указать только вымышленное имя и сорт; местоположение и личные заметки не отправляются. Публикацию можно удалить с этого устройства.</p>
    <form id="share-form"><label class="form-field"><span>Псевдоним (не настоящее имя) *</span><input class="input" name="nickname" maxlength="24" required placeholder="Например, Любитель цветов" /></label>
    <label class="form-field"><span>Сорт</span><input class="input" name="variety" maxlength="60" value="${attr(p.variety)}" /></label>
    <label class="form-field"><span>Описание цветения (не более 180 знаков)</span><textarea class="input" name="caption" maxlength="180" placeholder="Например, первое цветение в этом сезоне"></textarea></label>
    <label class="form-field"><input type="checkbox" name="consent" required /> На снимке только растения, без людей, адресов, номеров и другой личной информации. Я согласен(на) опубликовать эту фотографию для просмотра другими пользователями.</label>
    <div class="btn-row"><button type="submit" class="btn btn-primary">Отправить на проверку</button><button type="button" class="btn btn-outline" data-action="close">Отмена</button></div></form>`);
}
function render(){
  main.innerHTML=current==='today'?todayPage():current==='plants'?(plantId?plantDetail():plantsPage()):current==='calendar'?calendarPage():current==='guide'?guidePage():current==='gallery'?galleryPage():morePage();
  tabs.querySelectorAll('.tab').forEach(b=>{const active=b.dataset.tab===current;b.classList.toggle('active',active);b.setAttribute('aria-current',active?'page':'false');});
  if(current==='calendar') {const active=main.querySelector('.filter.selected');if(active)active.scrollIntoView({block:'nearest',inline:'center'});}
}
function openSheet(markup){overlay.innerHTML=`<div class="sheet" role="dialog" aria-modal="true"><div class="sheet-handle"></div>${markup}</div>`;overlay.classList.remove('hidden');}
function closeSheet(){overlay.classList.add('hidden');overlay.innerHTML='';}
function plantForm(id='',draft=null) {
  const p=draft||data.plants.find(p=>p.id===id)||{name:'',variety:'',planted:'',place:'',notes:''};
  openSheet(`<h2 class="sheet-title">${id?'Редактировать куст':'Новая гортензия 🌸'}</h2><p class="sheet-description">Заполните только то, что знаете. Остальное можно добавить позже.</p>
  <form id="plant-form" data-id="${attr(id)}">
    <label class="form-field"><span>Как назвать куст? *</span><input class="input" name="name" required maxlength="70" placeholder="Например, Гортензия у крыльца" value="${attr(p.name)}" /></label>
    <label class="form-field"><span>Сорт</span><input class="input" name="variety" maxlength="80" list="known-varieties" placeholder="Например, Limelight" value="${attr(p.variety)}"/><datalist id="known-varieties">${allVarieties().map(v=>`<option value="${attr(v.name)}"></option>`).join('')}</datalist></label>
    <button class="btn btn-outline" type="button" data-action="add-variety-from-plant" style="margin-bottom:16px">+ Добавить сорт в справочник</button>
    <label class="form-field"><span>Дата посадки</span><input class="input" name="planted" type="date" value="${attr(p.planted)}" /></label>
    <label class="form-field"><span>Место в саду</span><input class="input" name="place" maxlength="90" placeholder="У террасы, вдоль дорожки..." value="${attr(p.place)}" /></label>
    <label class="form-field"><span>Заметки</span><textarea class="input" name="notes" maxlength="400" rows="3" placeholder="Освещение, особенности, тип почвы...">${esc(p.notes)}</textarea></label>
    <div class="btn-row"><button class="btn btn-primary" type="submit">${id?'Сохранить изменения':'Добавить в сад'}</button><button class="btn btn-outline" type="button" data-action="close">Отмена</button></div>
  </form>`);
}
function varietySheet(id='',fromPlant=false,prefill='') {
  const v=data.customVarieties.find(x=>x.id===id)||{name:prefill,species:'Hydrangea paniculata',height:'',color:'',bloom:'Неизвестно',tag:'Другой',notes:''};
  editingVariety=id;returningToPlant=fromPlant;
  const options=(items,selected)=>items.map(x=>`<option value="${attr(x)}" ${x===selected?'selected':''}>${esc(x)}</option>`).join('');
  openSheet(`<h2 class="sheet-title">${id?'Изменить сорт':'Новый сорт гортензии 🌸'}</h2>
  <p class="sheet-description">Добавьте сведения о сорте из этикетки питомника или собственных наблюдений. Эта запись личная и не появится в общем альбоме автоматически.</p>
  <form id="variety-form" data-id="${attr(id)}">
  <label class="form-field"><span>Название сорта *</span><input class="input" name="name" required maxlength="80" value="${attr(v.name)}" placeholder="Например, Pink Diamond" /></label>
  <label class="form-field"><span>Ботанический вид</span><select class="input" name="species">${options((D.speciesList||[{latin:'Hydrangea paniculata'}]).map(s=>s.latin),v.species||'Hydrangea paniculata')}</select></label>
  <label class="form-field"><span>Высота взрослого куста</span><input class="input" name="height" maxlength="70" value="${attr(v.height)}" placeholder="Например, до 1,5 м" /></label>
  <label class="form-field"><span>Цвет соцветий</span><input class="input" name="color" maxlength="100" value="${attr(v.color)}" placeholder="Белый → розовый" /></label>
  <label class="form-field"><span>Срок цветения</span><select class="input" name="bloom">${options(C.BLOOM_TYPES,v.bloom)}</select></label>
  <label class="form-field"><span>Особенность сорта</span><select class="input" name="tag">${options(C.VARIETY_TAGS,v.tag)}</select></label>
  <label class="form-field"><span>Описание и заметки</span><textarea class="input" name="notes" maxlength="500" rows="3" placeholder="Особенности сорта, источник названия...">${esc(v.notes)}</textarea></label>
  <div class="btn-row"><button class="btn btn-primary" type="submit">Сохранить сорт</button><button class="btn btn-outline" type="button" data-action="cancel-variety">Отмена</button></div></form>`);
}
function capturePlantDraft(form){
  const v=new FormData(form);return {name:String(v.get('name')||''),variety:String(v.get('variety')||''),planted:String(v.get('planted')||''),place:String(v.get('place')||''),notes:String(v.get('notes')||'')};
}
function cancelVariety(){
  if(returningToPlant&&plantDraft){const draft=plantDraft;plantDraft=null;returningToPlant=false;plantForm(draft.id,draft);}
  else {closeSheet();returningToPlant=false;go('guide');}
}
function confirmVarietyDelete(id){
  const v=data.customVarieties.find(x=>x.id===id);if(!v)return;
  const n=data.plants.filter(p=>C.normalizedVarietyName(p.variety)===C.normalizedVarietyName(v.name)).length;
  openSheet(`<h2 class="sheet-title">Удалить сорт «${esc(v.name)}»?</h2>
    <p class="sheet-description">Сорт исчезнет из личного справочника. ${n?`У ${n} кустов название сорта останется в карточке, но сведения из справочника больше не будут доступны.`:'Карточки растений и фотографии не пострадают.'}</p>
    <div class="btn-row"><button class="btn btn-danger" data-action="delete-variety-confirm" data-id="${attr(id)}">Удалить сорт</button><button class="btn btn-outline" data-action="close">Отмена</button></div>`);
}
function moistureSheet(id){const p=data.plants.find(x=>x.id===id);if(!p)return;
  openSheet(`<h2 class="sheet-title">Проверка почвы</h2><p class="sheet-description">${esc(p.name)} · проверьте грунт на глубине нескольких сантиметров.</p>
    <button class="help-option" data-action="moisture-dry" data-id="${attr(id)}">${glyph('droplet','cream')}<span>Почва сухая<br/><small class="muted">Рассмотреть полив, если вода не застаивается</small></span><span class="chevron">›</span></button>
    <button class="help-option" data-action="moisture-moist" data-id="${attr(id)}">${glyph('leaf')}<span>Почва ещё влажная<br/><small class="muted">Отложить полив и отметить проверку</small></span><span class="chevron">›</span></button>
    <button class="btn btn-outline btn-block" data-action="close">Отмена</button>`);
}
function waterSheet(id) {const p=data.plants.find(x=>x.id===id);if(!p)return;
  openSheet(`<h2 class="sheet-title">Записать полив</h2><p class="sheet-description">${esc(p.name)} · отмечайте полив после проверки грунта. В сырую почву лишнюю воду не добавляйте.</p>
  <form id="water-form" data-id="${attr(id)}"><label class="form-field"><span>Дата</span><input class="input" name="day" type="date" required max="${today()}" value="${today()}" /></label><label class="form-field"><span>Заметка (по желанию)</span><input class="input" maxlength="160" name="note" placeholder="Например, грунт подсох после жары" /></label><div class="btn-row"><button class="btn btn-primary" type="submit">Сохранить полив</button><button type="button" class="btn btn-outline" data-action="close">Отмена</button></div></form>`);
}
function logSheet(id,kind){const p=data.plants.find(x=>x.id===id);if(!p)return;
  openSheet(`<h2 class="sheet-title">${historyLabel(kind)}</h2><p class="sheet-description">${esc(p.name)} · записать проведённую работу.</p><form id="log-form" data-id="${attr(id)}" data-kind="${attr(kind)}"><label class="form-field"><span>Дата</span><input class="input" type="date" name="day" required max="${today()}" value="${today()}" /></label><label class="form-field"><span>Что сделали?</span><input class="input" name="note" maxlength="160" placeholder="Краткая заметка" /></label><div class="btn-row"><button class="btn btn-primary" type="submit">Сохранить</button><button class="btn btn-outline" type="button" data-action="close">Отмена</button></div></form>`);
}
function record(id,kind,day,note=''){
  const p=data.plants.find(x=>x.id===id);if(!p || !C.parseDay(day))return;
  if(!Array.isArray(p.history))p.history=[];
  p.history.push({kind,day,note:C.safeString(note,160)});
  if(p.history.length>300)p.history=p.history.slice(-300);
  if(kind==='water') {p.lastWatered=day;p.lastCheck=day;}
  if(kind==='moisture')p.lastCheck=day;
  save();closeSheet();render();toast('Запись сохранена');
}
function confirmation(id){const p=data.plants.find(x=>x.id===id);if(!p)return;
  openSheet(`<h2 class="sheet-title">Удалить «${esc(p.name)}»?</h2><p class="sheet-description">История ухода за этим кустом будет удалена из приложения. Это действие нельзя отменить.</p><div class="btn-row"><button class="btn btn-danger" data-action="delete-confirm" data-id="${attr(id)}">Удалить куст</button><button class="btn btn-outline" data-action="close">Отмена</button></div>`);
}
function startExport(){const json=JSON.stringify(data,null,2);
  if(window.GardenAndroid){window.GardenAndroid.exportBackup(json);} else {
    const blob=new Blob([json],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download='gortenziya-moy-sad.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),3000);
  }
}
function startImport(){if(window.GardenAndroid)window.GardenAndroid.importBackup();else document.getElementById('backup-file').click();}
window.receiveImportBackup = function(text){
  try {const clean=C.sanitizeBackup(JSON.parse(text));
    openSheet(`<h2 class="sheet-title">Восстановить сад?</h2><p class="sheet-description">В файле ${clean.plants.length} растений. Текущие ${data.plants.length} растений и история ухода будут заменены данными из файла.</p><div class="btn-row"><button class="btn btn-primary" id="confirm-import">Заменить данные</button><button class="btn btn-outline" data-action="close">Отмена</button></div>`);
    const b=overlay.querySelector('#confirm-import');b.addEventListener('click',()=>{data=clean;save();closeSheet();go('plants');toast('Сад восстановлен');},{once:true});
  } catch(err){toast('Файл не подходит: '+(err.message||'ошибка формата'));}
};
window.nativeReminderStatus=function(enabled){reminderEnabled=!!enabled;if(current==='more')render();if(enabled)toast('Напоминания включены');};
if(window.GardenAndroid){try {reminderEnabled=window.GardenAndroid.getReminderState();}catch(e){reminderEnabled=false;}}
else {reminderEnabled=localStorage.getItem('garden_demo_reminder')==='yes';}

main.addEventListener('click',event=>handle(event));
tabs.addEventListener('click',e=>{const b=e.target.closest('[data-tab]');if(b){go(b.dataset.tab);if(b.dataset.tab==='gallery')refreshGallery();}});
overlay.addEventListener('click',e=>{if(e.target===overlay)closeSheet();else handle(e);});
overlay.addEventListener('change',e=>{
  const selected=e.target.closest('[data-compare]');if(!selected)return;
  comparePhotos[Number(selected.dataset.compare)]=selected.value;
  const p=data.plants.find(x=>x.id===plantId);if(p)updateComparison(p);
});
main.addEventListener('submit',e=>{
  if(e.target.id!=='plant-search-form')return;
  e.preventDefault();plantQuery=C.safeString(new FormData(e.target).get('query'),80);render();
});
document.getElementById('backup-file').addEventListener('change',async e=>{
  const f=e.target.files?.[0];if(!f)return;
  if(f.size>1_000_000){toast('Файл слишком большой');return;}
  window.receiveImportBackup(await f.text());e.target.value='';
});
function handle(e){
  const button=e.target.closest('[data-action]');if(!button)return;
  const act=button.dataset.action,id=button.dataset.id;
  switch(act){
    case 'gallery-refresh':refreshGallery();break;
    case 'plant-filter':plantFilter=button.dataset.filter;render();break;
    case 'clear-plant-search':plantQuery='';plantFilter='Все';render();break;
    case 'edit-photo':photoSheet(id,button.dataset.photo);break;
    case 'compare-photos':compareSheet(id);break;
    case 'save-comparison':{
      const p=data.plants.find(x=>x.id===id);
      if(!p||id!==comparePlantId||comparePhotos[0]===comparePhotos[1]||!comparePhotos.every(x=>p.photos.includes(x))){toast('Выберите два разных снимка');break;}
      p.comparisons=p.comparisons||[];
      if(p.comparisons.length>=100){toast('Достигнут лимит сравнений');break;}
      p.comparisons.push({id:'cmp-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,11),first:comparePhotos[0],second:comparePhotos[1],created:today(),note:C.safeString(overlay.querySelector('#comparison-note')?.value,180)});
      save();closeSheet();go('plants',{plant:id});toast('Сравнение сохранено');break;
    }
    case 'view-comparison':savedComparisonSheet(id,button.dataset.compareId);break;
    case 'delete-comparison':{
      const p=data.plants.find(x=>x.id===id);if(!p)break;
      p.comparisons=(p.comparisons||[]).filter(x=>x.id!==button.dataset.compareId);
      save();render();toast('Сравнение удалено');break;
    }
    case 'edit-bloom':bloomSheet(id,button.dataset.year);break;
    case 'delete-bloom':{
      const p=data.plants.find(x=>x.id===id);if(!p)break;
      p.bloomYears=(p.bloomYears||[]).filter(x=>x.year!==Number(button.dataset.year));
      save();closeSheet();go('plants',{plant:id});toast('Запись удалена');break;
    }
    case 'go-gallery':go('gallery');refreshGallery();break;
    case 'add-photo':
      if(!window.GardenAndroid){toast('Добавление фотографий доступно в Android-приложении');break;}
      window.GardenAndroid.pickPhoto(id);break;
    case 'delete-photo':{
      const p=data.plants.find(x=>x.id===id),photo=button.dataset.photo;
      if(!p||!(p.photos||[]).includes(photo))break;
      p.photos=p.photos.filter(x=>x!==photo);if(p.photoMeta)delete p.photoMeta[photo];p.comparisons=(p.comparisons||[]).filter(x=>x.first!==photo&&x.second!==photo);save();
      if(window.GardenAndroid)window.GardenAndroid.deleteLocalPhoto(photo);
      render();toast('Локальная фотография удалена. Опубликованное фото удаляется отдельно.');break;
    }
    case 'share-photo':sharingSheet(id,button.dataset.photo);break;
    case 'remove-shared':{
      if(!confirm('Удалить опубликованную фотографию и файл из общего альбома?'))break;
      cloud('remove',{id:button.dataset.photo}).then(()=>{toast('Публикация удалена');refreshGallery();}).catch(e=>toast(e.message));break;
    }
    case 'report-shared':{
      if(!confirm('Отправить жалобу модератору на эту фотографию?'))break;
      cloud('report',{id:button.dataset.photo}).then(()=>toast('Жалоба отправлена')).catch(e=>toast(e.message));break;
    }
    case 'open-settings':go('more');break;
    case 'go-plants':go('plants');break;
    case 'go-guide':go('guide');break;
    case 'open-plant':go('plants',{plant:id});break;
    case 'add-plant':plantForm();break;
    case 'edit-plant':plantForm(id);break;
    case 'add-variety':plantDraft=null;varietySheet();break;
    case 'add-variety-from-plant':{
      const form=overlay.querySelector('#plant-form');if(!form)break;
      plantDraft={...capturePlantDraft(form),id:form.dataset.id};
      varietySheet('',true,plantDraft.variety);break;
    }
    case 'edit-variety':plantDraft=null;varietySheet(id);break;
    case 'cancel-variety':cancelVariety();break;
    case 'delete-variety':confirmVarietyDelete(id);break;
    case 'delete-variety-confirm':{
      if(data.catalogPhotos[id]){window.GardenAndroid?.deleteLocalPhoto(data.catalogPhotos[id]);delete data.catalogPhotos[id];}
      selectedVariety='';data.customVarieties=data.customVarieties.filter(v=>v.id!==id);
      save();closeSheet();guideMode='sort';varietyFilter='Мои сорта';speciesFilter='Все виды';go('guide');toast('Сорт удалён; записи кустов сохранены');break;
    }
    case 'close':closeSheet();break;
    case 'delete-plant':confirmation(id);break;
    case 'delete-confirm':{
      const p=data.plants.find(x=>x.id===id);
      if(p&&window.GardenAndroid)(p.photos||[]).forEach(photo=>window.GardenAndroid.deleteLocalPhoto(photo));
      data.plants=data.plants.filter(p=>p.id!==id);save();closeSheet();go('plants');toast('Куст удалён; общие публикации удаляются отдельно');break;
    }
    case 'moisture':moistureSheet(id);break;
    case 'moisture-dry':record(id,'moisture',today(),'Почва сухая');toast('Проверьте, нужен ли полив');break;
    case 'moisture-moist':record(id,'moisture',today(),'Почва влажная, полив не нужен');break;
    case 'water':waterSheet(id);break;
    case 'log':logSheet(id,button.dataset.kind);break;
    case 'toggle-task':{
      const key=button.dataset.key;data.completed=data.completed.includes(key)?data.completed.filter(x=>x!==key):[...data.completed,key];
      save();render();break;
    }
    case 'month':month=Number(button.dataset.month);render();break;
    case 'guide-mode':guideMode=id;article='';selectedVariety='';render();break;
    case 'toggle-catalog-online':externalPhotosEnabled=!externalPhotosEnabled;render();break;
    case 'view-variety':if(isCatalogKey(id)){selectedVariety=id;render();window.scrollTo(0,0);}break;
    case 'variety-back':selectedVariety='';go('guide');break;
    case 'catalog-pick':if(!isCatalogKey(id))break;
      if(window.GardenAndroid)window.GardenAndroid.pickPhoto('catalog:'+id);
      else toast('Добавление фотографии доступно в Android-приложении');break;
    case 'catalog-remove':if(!isCatalogKey(id))break;
      if(data.catalogPhotos[id]){window.GardenAndroid?.deleteLocalPhoto(data.catalogPhotos[id]);delete data.catalogPhotos[id];save();render();}break;
    case 'photo-source':{
      const v=allVarieties().find(v=>catalogKey(v)===id);
      if(v?.onlinePhotoSource && window.GardenAndroid?.openPhotoSource)window.GardenAndroid.openPhotoSource(v.onlinePhotoSource);
      else toast('Источник фотографии указан в файле PHOTO_CREDITS.md');break;
    }
    case 'add-plant-variety':{
      const v=allVarieties().find(v=>catalogKey(v)===id);
      if(v)plantForm('',{name:'',variety:v.name,planted:'',place:'',notes:''});break;
    }
    case 'guide-article':go('guide',{article:id});break;
    case 'problem':go('guide',{article:id});break;
    case 'variety-filter':varietyFilter=button.dataset.filter;varietyShown=30;render();break;
    case 'variety-more':varietyShown+=30;render();break;
    case 'species-more':speciesShown+=30;render();break;
    case 'species-varieties':speciesFilter=id;varietyFilter='Все';varietySearch='';varietyShown=30;guideMode='sort';render();break;
    case 'open-kew':if(window.GardenAndroid?.openPhotoSource)window.GardenAndroid.openPhotoSource(D.catalogSources.sourceKew);else toast('Источник: Kew Plants of the World Online');break;
    case 'variety-reference':{const v=allVarieties().find(v=>catalogKey(v)===id);if(v?.reference&&window.GardenAndroid?.openPhotoSource)window.GardenAndroid.openPhotoSource(v.reference);else toast('Источник: каталог RHS');break;}
    case 'reminder':
      if(window.GardenAndroid)window.GardenAndroid.setReminderEnabled(!reminderEnabled);
      else {reminderEnabled=!reminderEnabled;localStorage.setItem('garden_demo_reminder',reminderEnabled?'yes':'no');toast('В браузерной версии системные уведомления недоступны');render();}
      break;
    case 'export':startExport();break;
    case 'import':startImport();break;
  }
}
main.addEventListener('change',e=>{
  if(e.target?.id==='variety-search'){varietySearch=e.target.value.slice(0,80);varietyShown=30;render();}
  if(e.target?.id==='species-search'){speciesSearch=e.target.value.slice(0,80);speciesShown=30;render();}
  if(e.target?.id==='species-filter'){speciesFilter=e.target.value;varietyShown=30;render();}
});
main.addEventListener('keydown',e=>{
  if(e.target?.id==='variety-search'&&e.key==='Enter'){e.preventDefault();varietySearch=e.target.value.slice(0,80);varietyShown=30;render();}
  if(e.target?.id==='species-search'&&e.key==='Enter'){e.preventDefault();speciesSearch=e.target.value.slice(0,80);speciesShown=30;render();}
});
overlay.addEventListener('submit',e=>{
  e.preventDefault();const form=e.target,inputs=new FormData(form);
  if(form.id==='bloom-form'){
    const p=data.plants.find(x=>x.id===form.dataset.id),year=Number(form.dataset.year);
    if(!p)return;
    const start=String(inputs.get('start')||''),end=String(inputs.get('end')||'');
    if((start&&(!C.parseDay(start)||!start.startsWith(year+'-')||start>today()))||(end&&(!C.parseDay(end)||!end.startsWith(year+'-')||end>today()))||(start&&end&&start>end)){
      toast('Проверьте даты начала и окончания цветения');return;
    }
    const note=C.safeString(inputs.get('note'),180);
    if(!start&&!end&&!note){toast('Укажите дату или заметку');return;}
    p.bloomYears=(p.bloomYears||[]).filter(x=>x.year!==year);
    p.bloomYears.push({year,start,end,note});p.bloomYears.sort((a,b)=>b.year-a.year);
    save();closeSheet();go('plants',{plant:p.id});toast('Календарь цветения сохранён');return;
  }
  if(form.id==='photo-form'){
    const p=data.plants.find(x=>x.id===form.dataset.id);
    if(!p || !(p.photos||[]).includes(form.dataset.photo))return;
    const day=String(inputs.get('day')||'');
    if(day && (!C.parseDay(day)||day>today())){toast('Дата снимка должна быть не позднее сегодняшней');return;}
    p.photoMeta=p.photoMeta||{};
    p.photoMeta[form.dataset.photo]=C.photoMetadata({day,stage:inputs.get('stage'),note:inputs.get('note')});
    save();closeSheet();go('plants',{plant:p.id});toast('Фотоистория сохранена');return;
  }
  if(form.id==='share-form'){
    const nickname=C.safeString(inputs.get('nickname'),24),variety=C.safeString(inputs.get('variety'),60),caption=C.safeString(inputs.get('caption'),180);
    if(!nickname||!inputs.get('consent')){toast('Нужны псевдоним и согласие');return;}
    const btn=form.querySelector('button[type=submit]');if(btn){btn.disabled=true;btn.textContent='Отправка…';}
    cloud('upload',{photoId:uploadPhoto,nickname,variety,caption,consent:true}).then(()=>{
      closeSheet();toast('Фотография отправлена на проверку');go('gallery');refreshGallery();
    }).catch(err=>{toast('Не удалось отправить: '+err.message);if(btn){btn.disabled=false;btn.textContent='Отправить на проверку';}});
    return;
  }
  if(form.id==='variety-form'){
    const name=C.safeString(inputs.get('name'),80);
    if(!name){toast('Введите название сорта');return;}
    const id=form.dataset.id;
    if(varietyExists(name,id)){toast('Такой сорт уже есть в справочнике');return;}
    const existing=data.customVarieties.find(v=>v.id===id);
    if(!existing&&data.customVarieties.length>=100){toast('Достигнут лимит: 100 собственных сортов');return;}
    const raw={id:id||'v-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,11),name,
      species:inputs.get('species'),height:inputs.get('height'),color:inputs.get('color'),bloom:inputs.get('bloom'),tag:inputs.get('tag'),notes:inputs.get('notes')};
    try{
      const clean=C.sanitizeVariety(raw);
      if(existing){
        const oldName=existing.name;
        Object.assign(existing,clean);
        if(C.normalizedVarietyName(oldName)!==C.normalizedVarietyName(clean.name))
          data.plants.forEach(p=>{if(C.normalizedVarietyName(p.variety)===C.normalizedVarietyName(oldName))p.variety=clean.name;});
      }else data.customVarieties.push(clean);
      save();closeSheet();
      if(returningToPlant&&plantDraft){const draft={...plantDraft,variety:clean.name};plantDraft=null;returningToPlant=false;plantForm(draft.id,draft);}
      else {guideMode='sort';varietyFilter='Мои сорта';speciesFilter='Все виды';go('guide');}
      toast('Сорт сохранён в личном справочнике');
    }catch(err){toast(err.message||'Не удалось сохранить сорт');}
    return;
  }
  if(form.id==='plant-form'){
    const name=C.safeString(inputs.get('name'),70);if(!name){toast('Введите название куста');return;}
    const id=form.dataset.id;let p=data.plants.find(x=>x.id===id);
    if(!p){p={id:`g-${Date.now()}-${Math.random().toString(36).slice(2,8)}`,lastCheck:'',lastWatered:'',history:[]};data.plants.push(p);}
    p.name=name;p.variety=C.safeString(inputs.get('variety'),80);p.planted=C.parseDay(inputs.get('planted'))?inputs.get('planted'):'';
    p.place=C.safeString(inputs.get('place'),90);p.notes=C.safeString(inputs.get('notes'),400);
    save();closeSheet();go('plants',{plant:p.id});toast('Куст сохранён');
  }
  if(form.id==='water-form'||form.id==='log-form'){
    const day=inputs.get('day');if(!C.parseDay(day)||day>today()){toast('Укажите корректную дату');return;}
    record(form.dataset.id,form.id==='water-form'?'water':form.dataset.kind,day,inputs.get('note'));
  }
});
render();
})();
