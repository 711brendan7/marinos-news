// REINS仕入れ PWA の Service Worker。
// 役割は「push通知を受けてアプリアイコンにバッジを立てる」ことだけ（オフラインキャッシュ等は行わない）。
// スコープを /reins/ 配下に閉じてあるので、同じリポジトリの他アプリ（物件ウォッチ等）の
// 登録を奪わない＝アプリごとに独立したバッジになる。
const SW_VERSION = 'reins-sw-1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

// setAppBadge() は上書きなので、開かれずに複数回巡回が走っても件数が積み上がるよう
// バッジ数だけ Cache Storage に保持する（IndexedDB を使うまでもない単純なカウンタ）。
async function addBadgeCount(delta) {
  const cache = await caches.open('reins-badge-count');
  const res = await cache.match('count');
  const cur = res ? (Number(await res.text()) || 0) : 0;
  const next = Math.max(0, cur + delta);
  await cache.put('count', new Response(String(next)));
  return next;
}
async function resetBadgeCount() {
  const cache = await caches.open('reins-badge-count');
  await cache.put('count', new Response('0'));
}

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) { data = {}; }
  const delta = Number(data.count || 0);
  const title = data.title || 'REINS仕入れ';
  const body  = data.body  || (delta ? `新着 ${delta}件` : '新着があります');

  event.waitUntil((async () => {
    const total = await addBadgeCount(delta);
    const tasks = [
      self.registration.showNotification(title, {
        body,
        icon: 'reins-icon-192.png',
        badge: 'reins-icon-192.png',
        tag: 'reins-new',
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

// アプリを開いた側（index.html）から「見た」通知が来たらバッジを0に戻す。
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'clearBadge') {
    event.waitUntil((async () => {
      await resetBadgeCount();
      if ('clearAppBadge' in self.navigator) await self.navigator.clearAppBadge();
    })());
  }
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

// ブラウザ側で購読が失効/更新された場合。サーバ側の登録簿は古い endpoint のままになるが、
// 次に有効な購読からのpushが届く方の endpoint で上書き登録されるため実害は小さい。
self.addEventListener('pushsubscriptionchange', (event) => {
  event.waitUntil(
    self.registration.pushManager.subscribe(event.oldSubscription ? event.oldSubscription.options : { userVisibleOnly: true })
      .then((sub) => self.clients.matchAll())
      .catch(() => {})
  );
});
