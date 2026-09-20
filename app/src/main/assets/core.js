/* Чистые функции для интерфейса, браузерных и Node.js тестов. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.GardenCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const MONTHS = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
  const MONTH_LABELS = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
  function dateKey(date) {
    const d = date instanceof Date ? date : new Date(date);
    if (Number.isNaN(d.getTime())) return '';
    return [d.getFullYear(), String(d.getMonth()+1).padStart(2,'0'), String(d.getDate()).padStart(2,'0')].join('-');
  }
  function parseDay(str) {
    if (typeof str !== 'string' || !/^\d{4}-\d\d-\d\d$/.test(str)) return null;
    const [y,m,d] = str.split('-').map(Number);
    const v = new Date(y,m-1,d);
    return v.getFullYear() === y && v.getMonth() === m-1 && v.getDate() === d ? v : null;
  }
  function daysSince(day, now = new Date()) {
    const start = parseDay(day);
    if (!start) return null;
    const current = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    return Math.round((Date.UTC(current.getFullYear(),current.getMonth(),current.getDate()) - Date.UTC(start.getFullYear(),start.getMonth(),start.getDate())) / 86400000);
  }
  function moistureStatus(plant, now = new Date()) {
    const n = daysSince(plant.lastCheck, now);
    const month = now.getMonth();
    const gap = [5,5,3,3,2,2,2,2,2,3,4,5][month];
    if (n === null || n >= gap) return { due: true, text: 'Проверьте влажность грунта', secondary: 'Поливать только если почва подсохла' };
    return { due: false, text: 'Проверка влажности проведена', secondary: `Следующая проверка примерно через ${gap-n} дн.` };
  }
  function checklistKey(taskId, monthIndex, year) { return `${year}-${String(monthIndex+1).padStart(2,'0')}:${taskId}`; }
  function safeString(value, max=120) { return typeof value === 'string' ? value.trim().slice(0, max) : ''; }
  const VARIETY_TAGS = ['Компактный','Ранний','Поздний','Высокий','Двухцветный','Лаймовый','Яркий','Крупные соцветия','Другой'];
  const BLOOM_TYPES = ['Ранний','Среднеранний','Средний','Поздний','Неизвестно'];
  function normalizedVarietyName(value) { return safeString(value,80).normalize('NFKC').toLocaleLowerCase().replace(/\s+/g,' '); }
  function sanitizeVariety(input) {
    if (!input || typeof input !== 'object') throw Error('Некорректный сорт');
    const id=safeString(input.id,70), name=safeString(input.name,80);
    if (!/^v-[a-z0-9-]{8,64}$/.test(id) || !name || !name.trim()) throw Error('Некорректный ID или название сорта');
    return {id,name,species:/^Hydrangea(?: [×a-z-]+){1,2}$/i.test(input.species||'')?safeString(input.species,90):'Hydrangea paniculata',height:safeString(input.height,70),color:safeString(input.color,100),
      bloom:BLOOM_TYPES.includes(input.bloom)?input.bloom:'Неизвестно',
      tag:VARIETY_TAGS.includes(input.tag)?input.tag:'Другой',notes:safeString(input.notes,500)};
  }
  function sanitizeVarieties(input) {
    if (input === undefined) return []; // Совместимость с резервными копиями 1.0 и 1.1.
    if (!Array.isArray(input) || input.length > 100) throw Error('Слишком много новых сортов');
    const ids=new Set(),names=new Set();
    return input.map(sanitizeVariety).map(v=>{
      const key=normalizedVarietyName(v.name);
      if(ids.has(v.id)||names.has(key)) throw Error('Повторяющийся сорт или ID');
      ids.add(v.id);names.add(key);return v;
    });
  }
  const PHOTO_STAGES = ['Не указана','Рост побегов','Бутонизация','Цветение','После цветения','Подготовка к зиме'];
  function photoMetadata(input) {
    const v=input && typeof input === 'object' ? input : {};
    return {day:parseDay(v.day)?v.day:'',stage:PHOTO_STAGES.includes(v.stage)?v.stage:'Не указана',
      note:safeString(v.note,180)};
  }
  function photoTimeline(plant) {
    const meta=plant.photoMeta||{};
    return (plant.photos||[]).map((id,index)=>({id,index,...photoMetadata(meta[id])}))
      .sort((a,b)=>a.day.localeCompare(b.day)||a.index-b.index);
  }
  function sanitizeComparisons(input, photos) {
    if (input === undefined) return [];
    if (!Array.isArray(input)) throw Error('Неверный формат сохранённых сравнений');
    const allowed=new Set(photos), ids=new Set();
    return input.slice(0,100).map(item=>{
      if(!item || typeof item!=='object') return null;
      const id=safeString(item.id,70),first=safeString(item.first,70),second=safeString(item.second,70);
      if(!/^cmp-[a-z0-9-]{8,64}$/.test(id)||ids.has(id)||first===second||!allowed.has(first)||!allowed.has(second))return null;
      ids.add(id);
      return {id,first,second,created:parseDay(item.created)?item.created:'',note:safeString(item.note,180)};
    }).filter(Boolean);
  }
  function sanitizeBloomYears(input) {
    if (input === undefined) return [];
    if (!Array.isArray(input)) throw Error('Неверный формат календаря цветения');
    const years=new Set();
    return input.slice(0,100).map(item=>{
      if(!item||typeof item!=='object')return null;
      const year=Number(item.year),start=parseDay(item.start)?item.start:'',end=parseDay(item.end)?item.end:'';
      if(!Number.isInteger(year)||year<1900||year>2100||years.has(year)||start&&!start.startsWith(year+'-')||end&&!end.startsWith(year+'-')||start&&end&&end<start)return null;
      years.add(year);
      return {year,start,end,note:safeString(item.note,180)};
    }).filter(Boolean).sort((a,b)=>b.year-a.year);
  }
  function bloomTimeline(plant) {
    // Only explicitly dated observations are included; undated photographs do not establish flowering dates.
    const marked=new Map();
    for(const p of photoTimeline(plant))if(p.day&&p.stage==='Цветение'){
      const year=Number(p.day.slice(0,4));
      if(!marked.has(year))marked.set(year,[]);
      marked.get(year).push(p.day);
    }
    const all=new Set([...((plant.bloomYears||[]).map(x=>x.year)),...marked.keys()]);
    return [...all].filter(y=>Number.isInteger(y)).sort((a,b)=>b-a).map(year=>{
      const record=(plant.bloomYears||[]).find(x=>x.year===year)||{year,start:'',end:'',note:''};
      const observations=marked.get(year)||[];
      return {...record,observations:observations.length,firstPhoto:observations[0]||'',lastPhoto:observations[observations.length-1]||''};
    });
  }
  function filterPlants(plants, query='', filter='Все') {
    const q=normalizedVarietyName(query);
    return plants.filter(p=>{
      if(filter==='Проверить почву'&&!moistureStatus(p).due)return false;
      if(filter==='С фотографиями'&&!(p.photos||[]).length)return false;
      return !q||[p.name,p.variety,p.place].some(value=>normalizedVarietyName(value).includes(q));
    });
  }
  const CATALOG_IMAGE_KEY = /^(?:b(?:[0-9]|[1-9][0-9]|10[0-9])|v-[a-z0-9-]{8,64})$/;
  const LOCAL_PHOTO_ID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
  function sanitizeCatalogPhotos(input){
    if(input === undefined)return {};
    if(!input || typeof input !== 'object' || Array.isArray(input))throw Error('Некорректные фото справочника');
    const output=Object.create(null),entries=Object.entries(input);
    if(entries.length>209)throw Error('Превышен лимит фотографий справочника');
    for(const [key,id] of entries){
      if(!CATALOG_IMAGE_KEY.test(key) || typeof id!=='string' || !LOCAL_PHOTO_ID.test(id))
        throw Error('Некорректная ссылка на фото сорта');
      output[key]=id;
    }
    return output;
  }
  function sanitizeBackup(input) {
    if (!input || typeof input !== 'object' || input.version !== 1 || !Array.isArray(input.plants) || !Array.isArray(input.completed)) throw Error('Неверный формат резервной копии');
    if (input.plants.length > 200 || input.completed.length > 2000) throw Error('Слишком много данных');
    const customVarieties = sanitizeVarieties(input.customVarieties);
    const catalogPhotos = sanitizeCatalogPhotos(input.catalogPhotos);
    const ids = new Set();
    const plants = input.plants.map((p, idx) => {
      if (!p || typeof p !== 'object') throw Error('Ошибка записи растения');
      const id = safeString(p.id, 70);
      const name = safeString(p.name, 70);
      if (!id || !name || ids.has(id)) throw Error('Некорректное название или ID растения');
      ids.add(id);
      const history = Array.isArray(p.history) ? p.history.slice(0, 300).map(h => ({
        kind: safeString(h.kind, 32), day: parseDay(h.day) ? h.day : '', note: safeString(h.note, 160)
      })).filter(h => h.day) : [];
      const photos=Array.isArray(p.photos)?[...new Set(p.photos.filter(x=>typeof x==='string'&&/^[a-f0-9-]{36}$/.test(x)))].slice(0,12):[];
      const photoMeta={};
      if(p.photoMeta && typeof p.photoMeta==='object' && !Array.isArray(p.photoMeta))
        for (const photo of photos) if(Object.hasOwn(p.photoMeta,photo)) photoMeta[photo]=photoMetadata(p.photoMeta[photo]);
      return {id, name, variety:safeString(p.variety, 80), planted:parseDay(p.planted)?p.planted:'',
        place:safeString(p.place, 90), notes:safeString(p.notes, 400), lastCheck:parseDay(p.lastCheck)?p.lastCheck:'',
        lastWatered:parseDay(p.lastWatered)?p.lastWatered:'', history,
        photos,photoMeta,comparisons:sanitizeComparisons(p.comparisons,photos),bloomYears:sanitizeBloomYears(p.bloomYears)};
    });
    return {version:1,plants,customVarieties,catalogPhotos,completed:input.completed.filter(x=>typeof x==='string' && /^[0-9]{4}-[0-9]{2}:[a-z0-9-]{1,50}$/.test(x)).slice(0,2000)};
  }
  return {MONTHS,MONTH_LABELS,dateKey,parseDay,daysSince,moistureStatus,checklistKey,safeString,VARIETY_TAGS,BLOOM_TYPES,normalizedVarietyName,sanitizeVariety,sanitizeVarieties,sanitizeCatalogPhotos,PHOTO_STAGES,photoMetadata,photoTimeline,sanitizeComparisons,sanitizeBloomYears,bloomTimeline,filterPlants,sanitizeBackup};
});
