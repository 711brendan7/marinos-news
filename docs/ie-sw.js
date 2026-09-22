/* IE分析アプリ：電波の届かない現場でも動くようにキャッシュする */
const CACHE='ie-analyzer-v1';
const ASSETS=['ie.html','ie-analyzer.js','ie-analyzer.css','ie.webmanifest','ie-icon-192.png','ie-icon-512.png','ie-icon-180.png'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting()))});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  e.respondWith(caches.match(e.request,{ignoreSearch:true}).then(hit=>{
    const net=fetch(e.request).then(res=>{
      if(res&&res.ok)caches.open(CACHE).then(c=>c.put(e.request,res.clone()));
      return res}).catch(()=>hit);
    return hit||net}));
});
