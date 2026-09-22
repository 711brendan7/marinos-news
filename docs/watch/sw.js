// 物件ウォッチ PWA の Service Worker。
// 役割は「push通知を受けてアプリアイコンにバッジを立てる」ことだけ（オフラインキャッシュ等は行わない）。
// スコープを /watch/ 配下に閉じてあるので、同じリポジトリの他アプリ（REINS仕入れ等）の
// 登録を奪わない＝アプリごとに独立したバッジになる。
const SW_VERSION = 'watch-sw-1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

// setAppBadge() は上書きなので、開かれずに複数回巡回が走っても件数が積み上がるよう
// バッジ数だけ Cache Storage に保持する（IndexedDB を使うまでもない単純なカウンタ）。
async function addBadgeCount(delta) {
  const cache = await caches.open('watch-badge-count');
  const res = await cache.match('count');
  const cur = res ? (Number(await res.text()) || 0) : 0;
  const next = Math.max(0, cur + delta);
  await cache.put('count', new Response(String(next)));
  return next;
}
async function resetBadgeCount() {
  const cache = await caches.open('watch-badge-count');
  await cache.put('count', new Response('0'));
}

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) { data = {}; }
  const delta = Number(data.count || 0);
  const title = data.title || '物件ウォッチ';
  const body  = data.body  || (delta ? `新着 ${delta}件` : '新着があります');

  event.waitUntil((async () => {
    const total = await addBadgeCount(delta);
    const tasks = [
      self.registration.showNotification(title, {
        body,
        icon: 'icon-192.png',
        badge: 'icon-192.png',
        tag: 'watch-new',
        renotify: true,
        data: { url: data.url || './' },
      }),
    ];
    if ('setAppBadge' in self.navigator) {
      tasks.push(total > 0 ? self.navigator.setAppBadge(total) : self.navigator.clearAppBadge());
    }
    await Promise.all(tasks);
  })());
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || './';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const c of list) { if ('focus' in c) return c.focus(); }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});

// アプリを開いた側（index.html）から「見た」通知が来たらバッジを0に戻す。
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'clearBadge') {
    event.waitUntil((async () => {
      await resetBadgeCount();
      if ('clearAppBadge' in self.navigator) await self.navigator.clearAppBadge();
    })());
  }
});

// ページ本体は必ずネットワークから取り直す。iOSのホーム画面アプリは
// 古いHTMLを掴んだままになることがあり、修正を入れても端末に届かない。
// 取れなかったときだけ前回のページを返す（機内モード等のフォールバック）。
self.addEventListener('fetch', (event) => {
  if (event.request.mode !== 'navigate') return;
  event.respondWith((async () => {
    try {
      const res = await fetch(event.request, { cache: 'no-store' });
      const cache = await caches.open('watch-pages');
      cache.put(event.request, res.clone());
      return res;
    } catch (_) {
      const cached = await caches.match(event.request);
      return cached || Response.error();
    }
  })());
});
