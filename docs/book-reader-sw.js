// book-reader.html 専用のネットワーク優先 Service Worker。
// オンライン時は常に最新HTMLを取得し、オフライン時のみキャッシュを返す。
// スコープは /marinos-news/ だが、book-reader.html 以外のリクエストは
// 一切 respondWith しないため、同ディレクトリの他アプリ（todo/receipt 等）には影響しない。
const CACHE = 'book-reader-v1';
const APP_PATH = '/marinos-news/book-reader.html';

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys.filter(k => k.startsWith('book-reader-') && k !== CACHE).map(k => caches.delete(k))
    );
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  const isApp = url.origin === self.location.origin && url.pathname.endsWith('/book-reader.html');
  if (!isApp) return; // 他アプリ・API・画像などは既定動作にまかせる

  event.respondWith((async () => {
    try {
      const fresh = await fetch(event.request, { cache: 'no-store' });
      const cache = await caches.open(CACHE);
      cache.put(APP_PATH, fresh.clone());
      return fresh;
    } catch (err) {
      const cached = await caches.match(APP_PATH);
      return cached || Response.error();
    }
  })());
});
