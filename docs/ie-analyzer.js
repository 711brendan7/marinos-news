'use strict';
/* IE分析アプリ：作業名をタップするだけで時間観測・稼働分析ができ、ログをCSVで持ち出せる。音声でも操作できる。 */
const IEAnalyzer=(()=>{
const KEY='kaizen-ie-analyzer-v1',LOGS='kaizen-ie-logs-v1',TYPES=['主体','付随','ムダ'];
const PRESETS={
  '組立作業':[['部品を取る','付随'],['組み付ける','主体'],['締結する','主体'],['検査する','付随'],['運搬する','ムダ'],['手待ち','ムダ']],
  '出荷・物流':[['ピッキング','主体'],['梱包','主体'],['ラベル貼り','付随'],['台車移動','ムダ'],['伝票探し','ムダ']],
  '稼働分析（4分類）':[['正味作業','主体'],['付随作業','付随'],['運搬・移動','ムダ'],['手待ち・停止','ムダ']],
  '設備オペレーター':[['段取り','付随'],['加工（自動）','主体'],['材料補給','付随'],['品質確認','付随'],['チョコ停対応','ムダ'],['手待ち','ムダ']]
};
const blank=()=>({mode:'time',name:'',place:'',observer:'',elements:PRESETS['稼働分析（4分類）'].map(([name,type])=>({name,type})),running:false,startedAt:null,current:null,laps:[],samples:[],notes:[]});
let s=blank(),tab='setup',timer=null,rec=null,listening=false,heard='',ok=true;

const esc=t=>String(t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const load=()=>{try{const v=JSON.parse(localStorage.getItem(KEY)||'null');if(v&&Array.isArray(v.elements))s=Object.assign(blank(),v)}catch{ok=false}};
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(s))}catch{ok=false}};
const logs=()=>{try{const v=JSON.parse(localStorage.getItem(LOGS)||'[]');return Array.isArray(v)?v:[]}catch{return[]}};
const clock=ms=>{const t=Math.max(0,Math.round(ms/1000)),h=Math.floor(t/3600),m=Math.floor(t%3600/60),x=t%60;return (h?h+':'+String(m).padStart(2,'0'):m)+':'+String(x).padStart(2,'0')};
const hhmmss=ts=>new Date(ts).toLocaleTimeString('ja-JP',{hour12:false});
const sec=ms=>(ms/1000).toFixed(1);
const title=()=>s.name.trim()||'無題の観測';

/* ---- 集計 ---- */
function summary(){
  const now=Date.now(),rows=new Map();
  s.elements.forEach(e=>rows.set(e.name,{name:e.name,type:e.type,count:0,total:0}));
  const put=(name,type,ms)=>{if(!rows.has(name))rows.set(name,{name,type,count:0,total:0});const r=rows.get(name);r.count++;r.total+=ms};
  if(s.mode==='time')s.laps.forEach(l=>put(l.name,l.type,(l.end||now)-l.start));
  else s.samples.forEach(o=>put(o.name,o.type,0));
  const list=[...rows.values()],grand=s.mode==='time'?list.reduce((a,b)=>a+b.total,0):list.reduce((a,b)=>a+b.count,0);
  list.forEach(r=>r.ratio=grand?(s.mode==='time'?r.total:r.count)/grand:0);
  const byType=TYPES.map(t=>({type:t,ratio:list.filter(r=>r.type===t).reduce((a,b)=>a+b.ratio,0)}));
  return {list:list.sort((a,b)=>b.ratio-a.ratio),grand,byType,
    n:s.mode==='time'?s.laps.length:s.samples.length,
    elapsed:s.startedAt?(s.running?now:(s.laps.length?(s.laps[s.laps.length-1].end||now):now))-s.startedAt:0};
}

/* ---- 記録操作 ---- */
function tap(i){
  const e=s.elements[i];if(!e||!e.name.trim())return;
  const now=Date.now();
  if(!s.startedAt)s.startedAt=now;
  s.running=true;
  if(s.mode==='time'){
    const open=s.laps[s.laps.length-1];
    if(open&&!open.end){if(now-open.start<300)return;open.end=now;open.dur=open.end-open.start}
    s.laps.push({name:e.name,type:e.type,start:now,end:null,dur:null});
  }else{
    s.samples.push({name:e.name,type:e.type,t:now});
  }
  s.current=i;save();render()
}
function stopObs(){
  const open=s.laps[s.laps.length-1];
  if(s.mode==='time'&&open&&!open.end){open.end=Date.now();open.dur=open.end-open.start}
  s.running=false;s.current=null;stopVoice();save();render()
}
function resetObs(){
  if(!confirm('現在の観測ログを消去します。よろしいですか？（保存済みログは残ります）'))return;
  s.running=false;s.startedAt=null;s.current=null;s.laps=[];s.samples=[];s.notes=[];save();render()
}
function undo(){
  if(s.mode==='time'){s.laps.pop();const last=s.laps[s.laps.length-1];if(last){last.end=null;last.dur=null;s.current=s.elements.findIndex(e=>e.name===last.name)}else{s.startedAt=null;s.running=false;s.current=null}}
  else s.samples.pop();
  save();render()
}

/* ---- 音声入力 ---- */
function voiceSupported(){return !!(window.SpeechRecognition||window.webkitSpeechRecognition)}
function normalize(t){return String(t).replace(/[\s、。,.　]/g,'')}
function matchElement(text){
  const t=normalize(text);let best=-1,len=0;
  s.elements.forEach((e,i)=>{const n=normalize(e.name);if(n&&t.includes(n)&&n.length>len){best=i;len=n.length}});
  if(best>=0)return best;
  const m=t.match(/(\d+)ばん|ばん(\d+)|([1-9])$/);
  if(m){const i=Number(m[1]||m[2]||m[3])-1;if(s.elements[i])return i}
  return -1;
}
function heardText(text){
  heard=text;
  if(/(観測|記録)?(しゅうりょう|終了|停止|ストップ|とめて|止めて)/.test(text)){stopObs();return}
  if(/^(メモ|めも)/.test(normalize(text))){s.notes.push({t:Date.now(),text:text.replace(/^\s*(メモ|めも)/,'').trim()});save();render();return}
  const i=matchElement(text);
  if(i>=0)tap(i);else{const el=document.getElementById('voice-heard');if(el)el.textContent='「'+text+'」→ 該当する作業名がありません';}
}
function startVoice(){
  const C=window.SpeechRecognition||window.webkitSpeechRecognition;if(!C)return;
  try{rec=new C()}catch{return}
  rec.lang='ja-JP';rec.continuous=true;rec.interimResults=true;
  rec.onresult=ev=>{for(let i=ev.resultIndex;i<ev.results.length;i++){const r=ev.results[i],text=r[0].transcript.trim();if(!text)continue;
    if(r.isFinal)heardText(text);else{const el=document.getElementById('voice-heard');if(el)el.textContent='聞き取り中：'+text}}};
  rec.onerror=ev=>{const el=document.getElementById('voice-heard');if(el)el.textContent=ev.error==='not-allowed'?'マイクの使用が許可されていません。ブラウザの設定を確認してください。':'音声を認識できませんでした（'+ev.error+'）';if(ev.error==='not-allowed'){listening=false;render()}};
  rec.onend=()=>{if(listening){try{rec.start()}catch{}}};
  try{rec.start();listening=true;heard=''}catch{listening=false}
  render()
}
function stopVoice(){listening=false;if(rec){rec.onend=null;try{rec.stop()}catch{}rec=null}}

/* ---- 出力 ---- */
function download(name,text,type){
  const url=URL.createObjectURL(new Blob([new Uint8Array([0xEF,0xBB,0xBF]),text],{type:type||'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
const cell=v=>'"'+String(v==null?'':v).replace(/"/g,'""')+'"';
function csv(){
  const head=['観測名','場所','観測者','モード','開始時刻'],meta=[title(),s.place,s.observer,s.mode==='time'?'時間観測':'稼働分析（ワークサンプリング）',s.startedAt?new Date(s.startedAt).toLocaleString('ja-JP'):''];
  const out=[head.map(cell).join(','),meta.map(cell).join(','),''];
  if(s.mode==='time'){
    out.push(['No','作業名','区分','開始時刻','終了時刻','所要秒','累積秒'].map(cell).join(','));
    let acc=0;s.laps.forEach((l,i)=>{const d=((l.end||Date.now())-l.start)/1000;acc+=d;
      out.push([i+1,l.name,l.type,hhmmss(l.start),l.end?hhmmss(l.end):'観測中',d.toFixed(1),acc.toFixed(1)].map(cell).join(','))});
  }else{
    out.push(['No','作業名','区分','観測時刻'].map(cell).join(','));
    s.samples.forEach((o,i)=>out.push([i+1,o.name,o.type,hhmmss(o.t)].map(cell).join(',')));
  }
  const sm=summary();
  out.push('',['集計','区分',s.mode==='time'?'合計秒':'観測回数','回数','構成比%'].map(cell).join(','));
  sm.list.forEach(r=>out.push([r.name,r.type,s.mode==='time'?(r.total/1000).toFixed(1):r.count,r.count,(r.ratio*100).toFixed(1)].map(cell).join(',')));
  out.push('',['区分別','構成比%'].map(cell).join(','));
  sm.byType.forEach(t=>out.push([t.type,(t.ratio*100).toFixed(1)].map(cell).join(',')));
  if(s.notes.length){out.push('',['音声メモ時刻','内容'].map(cell).join(','));s.notes.forEach(n=>out.push([hhmmss(n.t),n.text].map(cell).join(',')))}
  return out.join('\r\n');
}
const stamp=()=>new Date().toISOString().slice(0,16).replace(/[-:T]/g,'');
function exportCsv(){download('IE分析_'+title()+'_'+stamp()+'.csv',csv())}
function exportJson(){download('IE分析_'+title()+'_'+stamp()+'.json',JSON.stringify({title:title(),place:s.place,observer:s.observer,mode:s.mode,startedAt:s.startedAt,elements:s.elements,laps:s.laps,samples:s.samples,notes:s.notes,summary:summary()},null,2),'application/json;charset=utf-8')}
async function copyCsv(){
  const text=csv();
  try{await navigator.clipboard.writeText(text);alert('ログをコピーしました。Excelやメールに貼り付けられます。')}
  catch{download('IE分析_'+title()+'_'+stamp()+'.csv',text)}
}
function saveLog(){
  if(!summary().n){alert('保存できる記録がありません。');return}
  const all=logs();
  all.unshift({id:Date.now(),title:title(),mode:s.mode,place:s.place,observer:s.observer,savedAt:Date.now(),startedAt:s.startedAt,elements:s.elements,laps:s.laps,samples:s.samples,notes:s.notes});
  try{localStorage.setItem(LOGS,JSON.stringify(all.slice(0,50)));alert('この端末に保存しました。「保存したログ」から呼び出せます。')}
  catch{alert('保存できませんでした。CSVでダウンロードして残してください。')}
  render()
}
function openLog(id){
  const l=logs().find(x=>x.id===id);if(!l)return;
  s=Object.assign(blank(),{name:l.title,place:l.place||'',observer:l.observer||'',mode:l.mode,startedAt:l.startedAt,elements:l.elements,laps:l.laps||[],samples:l.samples||[],notes:l.notes||[],running:false});
  save();tab='result';render()
}
function deleteLog(id){
  if(!confirm('この保存ログを削除します。よろしいですか？'))return;
  try{localStorage.setItem(LOGS,JSON.stringify(logs().filter(x=>x.id!==id)))}catch{}
  render()
}

/* ---- 画面 ---- */
function setupView(){
  return `<section class="ana-card"><h2>1. 観測の条件</h2><p class="hint">あとでログに残る情報です。空欄でも始められます。</p>
<label class="ana-field"><span>観測名（工程・製品など）</span><input id="ana-name" type="text" maxlength="60" value="${esc(s.name)}" placeholder="例）第2ライン 組立A"></label>
<div class="ana-actions" style="gap:12px">
<label class="ana-field" style="flex:1 1 180px;margin:0"><span>場所・ライン</span><input id="ana-place" type="text" maxlength="60" value="${esc(s.place)}" placeholder="例）第1工場"></label>
<label class="ana-field" style="flex:1 1 180px;margin:0"><span>観測者</span><input id="ana-observer" type="text" maxlength="40" value="${esc(s.observer)}" placeholder="例）山田"></label></div></section>

<section class="ana-card"><h2>2. 分析の方法</h2>
<div class="ana-modes">
<label><input type="radio" name="ana-mode" value="time" ${s.mode==='time'?'checked':''}><b>時間観測（連続観測）</b><small>作業名をタップした瞬間に前の要素が終わり、次が始まる。要素別の所要時間を測る。</small></label>
<label><input type="radio" name="ana-mode" value="sampling" ${s.mode==='sampling'?'checked':''}><b>稼働分析（ワークサンプリング）</b><small>見た瞬間の状態をタップして1件記録。回数の比率で稼働率・ムダの割合をつかむ。</small></label>
</div></section>

<section class="ana-card"><h2>3. 作業名（観測要素）</h2><p class="hint">この名前がそのまま観測ボタンになり、音声のキーワードにもなります。区分は主体作業・付随作業・ムダで分けます。</p>
<div class="ana-preset">${Object.keys(PRESETS).map(k=>`<button type="button" data-preset="${esc(k)}">${esc(k)}を読み込む</button>`).join('')}</div>
<div id="ana-elements">${s.elements.map((e,i)=>`<div class="el-row"><input type="text" maxlength="30" value="${esc(e.name)}" data-el="${i}" placeholder="作業名"><select data-type="${i}">${TYPES.map(t=>`<option ${e.type===t?'selected':''}>${t}</option>`).join('')}</select><button type="button" class="del" data-del="${i}" aria-label="${esc(e.name)}を削除">×</button></div>`).join('')}</div>
<div class="ana-actions"><button type="button" class="secondary" id="ana-add">＋ 作業名を追加</button>
<button type="button" class="primary" id="ana-go">観測をはじめる →</button></div></section>

${savedView()}`;
}
function savedView(){
  const all=logs();if(!all.length)return '';
  return `<section class="ana-card"><h2>保存したログ</h2><p class="hint">この端末に最大50件まで残ります。CSVでの持ち出しを推奨します。</p>
${all.map(l=>`<div class="ana-saved"><div><b>${esc(l.title)}</b><small>${new Date(l.savedAt).toLocaleString('ja-JP')} / ${l.mode==='time'?'時間観測':'稼働分析'} / ${(l.mode==='time'?(l.laps||[]).length:(l.samples||[]).length)}件</small></div><button type="button" class="secondary" data-open="${l.id}">開く</button><button type="button" class="secondary" data-delete="${l.id}">削除</button></div>`).join('')}</section>`;
}
function observeView(){
  const sm=summary(),now=Date.now(),open=s.laps[s.laps.length-1];
  const cur=s.current!=null?s.elements[s.current]:null;
  return `<div class="obs-bar"><div><div class="obs-clock" id="obs-clock">${clock(sm.elapsed)}</div></div>
<div class="obs-now"><b id="obs-current">${cur?esc(cur.name):(s.running?'—':'作業名をタップして開始')}</b>${s.mode==='time'?'現在の要素 <span id="obs-lap">'+(open&&!open.end?clock(now-open.start):'0:00')+'</span> 経過':'記録 '+sm.n+' 件'}</div></div>

<div class="obs-grid">${s.elements.map((e,i)=>{
  const r=sm.list.find(x=>x.name===e.name)||{count:0,total:0};
  return `<button type="button" class="obs-btn ${s.current===i?'current':''}" data-tap="${i}" data-type="${esc(e.type)}"><b>${esc(e.name)}</b><small><span>${esc(e.type)}</span><span data-stat="${i}">${s.mode==='time'?clock(r.total)+' / '+r.count+'回':r.count+'回'}</span></small></button>`}).join('')}</div>

<div class="obs-foot">
<button type="button" class="secondary" id="obs-undo">↶ 1つ取り消し</button>
<button type="button" class="danger" id="obs-stop">■ 観測を終える</button>
<button type="button" class="primary" id="obs-result">結果を見る →</button></div>

<div class="voice-box ${listening?'on':''}"><div class="voice-head"><b>🎙 音声で記録する</b>
${voiceSupported()?`<button type="button" class="mic ${listening?'on':''}" id="voice-toggle">${listening?'■ 音声を止める':'● 音声をはじめる'}</button>`:'<span class="muted">この端末・ブラウザでは音声入力に対応していません（iPhoneはSafari、PCはChromeで利用できます）</span>'}</div>
<p class="voice-heard" id="voice-heard">${esc(heard)}</p>
<p class="voice-help">作業名をそのまま声に出すと、その要素に切り替わります。「1番」のように番号でも指定できます。<br>「終了」「停止」で観測を終え、「メモ ○○」と言うと備考として記録されます。手が塞がっている観測で使ってください。</p></div>

${s.notes.length?`<section class="ana-card"><h2>音声メモ</h2><ul class="log-list">${s.notes.map(n=>`<li><span>${hhmmss(n.t)}</span><span>${esc(n.text)}</span></li>`).join('')}</ul></section>`:''}`;
}
function resultView(){
  const sm=summary();
  if(!sm.n)return `<section class="ana-card"><h2>まだ記録がありません</h2><p class="hint">「観測」タブで作業名をタップすると、ここに集計とログが出ます。</p><button type="button" class="primary" id="ana-to-observe">観測画面へ →</button></section>`;
  const work=sm.byType.find(t=>t.type==='主体').ratio,muda=sm.byType.find(t=>t.type==='ムダ').ratio;
  return `<div class="sum-cards">
<div class="sum-card"><strong>${(work*100).toFixed(1)}<small>%</small></strong><small>主体作業（正味）</small></div>
<div class="sum-card"><strong>${(muda*100).toFixed(1)}<small>%</small></strong><small>ムダ</small></div>
<div class="sum-card"><strong>${s.mode==='time'?clock(sm.elapsed):sm.n}</strong><small>${s.mode==='time'?'観測時間':'観測回数'}</small></div></div>

<section class="ana-card"><h2>要素別の構成比</h2>
${sm.list.map(r=>`<div class="bar-row"><span>${esc(r.name)}</span><div><i class="t${esc(r.type)}" style="width:${(r.ratio*100).toFixed(1)}%"></i></div><b>${(r.ratio*100).toFixed(1)}%</b></div>`).join('')}
<div class="ana-table" style="margin-top:16px"><table><thead><tr><th>作業名</th><th>区分</th><th>${s.mode==='time'?'合計':'回数'}</th><th>回数</th><th>${s.mode==='time'?'平均':'構成比'}</th><th>構成比</th></tr></thead>
<tbody>${sm.list.map(r=>`<tr><td>${esc(r.name)}</td><td>${esc(r.type)}</td><td class="num">${s.mode==='time'?sec(r.total)+'秒':r.count}</td><td class="num">${r.count}</td><td class="num">${s.mode==='time'?(r.count?sec(r.total/r.count)+'秒':'—'):(r.ratio*100).toFixed(1)+'%'}</td><td class="num">${(r.ratio*100).toFixed(1)}%</td></tr>`).join('')}</tbody></table></div>
<p class="storage-note">構成比は${s.mode==='time'?'観測した要素時間の合計':'観測回数'}に対する割合です。標準時間を出す場合は、レイティングと余裕率を別途かけてください。</p></section>

<section class="ana-card"><h2>ログ（${sm.n}件）</h2>
<ul class="log-list">${(s.mode==='time'?s.laps:s.samples).slice().reverse().slice(0,120).map((l,i)=>`<li><span>${hhmmss(s.mode==='time'?l.start:l.t)}</span><span>${esc(l.name)}<small class="muted"> ${esc(l.type)}</small></span>${s.mode==='time'?`<b>${l.end?sec(l.end-l.start)+'秒':'観測中'}</b>`:''}</li>`).join('')}</ul></section>

<section class="ana-card"><h2>ログを他で活用する</h2><p class="hint">CSVはExcel・スプレッドシートでそのまま開けます（BOM付きUTF-8）。集計表と区分別の比率も同じファイルに入ります。</p>
<div class="ana-actions">
<button type="button" class="primary" id="ana-csv">CSVをダウンロード</button>
<button type="button" class="secondary" id="ana-copy">ログをコピー</button>
<button type="button" class="secondary" id="ana-json">JSONで書き出す</button>
<button type="button" class="secondary" id="ana-save">この端末に保存</button>
<button type="button" class="danger" id="ana-reset">記録を消去</button></div>
<p class="storage-note">${ok?'観測データはこのブラウザに自動保存されます。別の端末とは同期しません。':'保存できない設定のため、画面を閉じると記録は消えます。こまめにCSVで書き出してください。'}</p></section>

${savedView()}`;
}
function render(){
  const main=document.getElementById('main');if(!main||!main.dataset.analyzer)return;
  const bc=document.getElementById('breadcrumb');if(bc)bc.textContent='IE分析アプリ';
  main.innerHTML=`<div class="ana-head"><div class="overline">FIELD TOOL / 現場で使う</div>
<h1>IE分析アプリ</h1><p>作業名をタップするだけで、時間観測と稼働分析ができます。声でも記録でき、ログはCSVで持ち出せます。</p></div>
<div class="ana-tabs">${[['setup','① 準備'],['observe','② 観測'],['result','③ 結果・ログ']].map(([k,l])=>`<button type="button" data-tab="${k}" class="${tab===k?'active':''}">${l}</button>`).join('')}</div>
${tab==='setup'?setupView():tab==='observe'?observeView():resultView()}`;
  bind(main);ticker()
}
function ticker(){
  clearInterval(timer);timer=null;
  if(tab!=='observe'||!s.running||s.mode!=='time')return;
  timer=setInterval(()=>{
    const sm=summary(),open=s.laps[s.laps.length-1];
    const c=document.getElementById('obs-clock');if(!c){clearInterval(timer);timer=null;return}
    c.textContent=clock(sm.elapsed);
    const lap=document.getElementById('obs-lap');if(lap&&open&&!open.end)lap.textContent=clock(Date.now()-open.start);
    s.elements.forEach((e,i)=>{const el=document.querySelector('[data-stat="'+i+'"]'),r=sm.list.find(x=>x.name===e.name);if(el&&r)el.textContent=clock(r.total)+' / '+r.count+'回'});
  },500)
}
function bind(main){
  main.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{tab=b.dataset.tab;render()}));
  main.querySelectorAll('[data-open]').forEach(b=>b.addEventListener('click',()=>openLog(Number(b.dataset.open))));
  main.querySelectorAll('[data-delete]').forEach(b=>b.addEventListener('click',()=>deleteLog(Number(b.dataset.delete))));
  if(tab==='setup'){
    const keep=()=>{s.name=main.querySelector('#ana-name').value;s.place=main.querySelector('#ana-place').value;s.observer=main.querySelector('#ana-observer').value;save()};
    ['#ana-name','#ana-place','#ana-observer'].forEach(sel=>main.querySelector(sel).addEventListener('input',keep));
    main.querySelectorAll('[name=ana-mode]').forEach(r=>r.addEventListener('change',()=>{s.mode=r.value;save();render()}));
    main.querySelectorAll('[data-el]').forEach(i=>i.addEventListener('input',()=>{s.elements[Number(i.dataset.el)].name=i.value;save()}));
    main.querySelectorAll('[data-type]').forEach(sel=>sel.addEventListener('change',()=>{s.elements[Number(sel.dataset.type)].type=sel.value;save();render()}));
    main.querySelectorAll('[data-del]').forEach(b=>b.addEventListener('click',()=>{s.elements.splice(Number(b.dataset.del),1);save();render()}));
    main.querySelectorAll('[data-preset]').forEach(b=>b.addEventListener('click',()=>{s.elements=PRESETS[b.dataset.preset].map(([name,type])=>({name,type}));save();render()}));
    main.querySelector('#ana-add').addEventListener('click',()=>{s.elements.push({name:'',type:'主体'});save();render()});
    main.querySelector('#ana-go').addEventListener('click',()=>{
      s.elements=s.elements.filter(e=>e.name.trim());
      if(!s.elements.length){alert('作業名を1つ以上入力してください。');return}
      save();tab='observe';render()});
  }
  if(tab==='observe'){
    main.querySelectorAll('[data-tap]').forEach(b=>b.addEventListener('click',()=>tap(Number(b.dataset.tap))));
    main.querySelector('#obs-undo').addEventListener('click',undo);
    main.querySelector('#obs-stop').addEventListener('click',stopObs);
    main.querySelector('#obs-result').addEventListener('click',()=>{tab='result';render()});
    const mic=main.querySelector('#voice-toggle');
    if(mic)mic.addEventListener('click',()=>{listening?(stopVoice(),render()):startVoice()});
  }
  if(tab==='result'){
    const to=main.querySelector('#ana-to-observe');if(to)to.addEventListener('click',()=>{tab='observe';render()});
    const on=(sel,fn)=>{const el=main.querySelector(sel);if(el)el.addEventListener('click',fn)};
    on('#ana-csv',exportCsv);on('#ana-copy',copyCsv);on('#ana-json',exportJson);on('#ana-save',saveLog);on('#ana-reset',resetObs);
  }
}
load();
return {
  open(){const main=document.getElementById('main');main.dataset.analyzer='1';delete main.dataset.video;document.title='IE分析アプリ | 改善の学校';
    document.querySelectorAll('.nav-item').forEach(el=>{const a=el.classList.contains('analyze-nav');el.classList.toggle('active',a);el.setAttribute('aria-current',a?'page':'false')});
    render()},
  stop(){stopVoice();clearInterval(timer);timer=null;const main=document.getElementById('main');if(main)delete main.dataset.analyzer}
};
})();
