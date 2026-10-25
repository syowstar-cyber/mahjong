// 普段の回のページの読み込みの手伝い（ホーム画面のアプリ用）。ページの見た目（HTML・アイコン・manifest）だけを手元に置く。
// 設定と組み合わせ（.json）、受け口（script.google.com）は手元に置かず、いつも新しく読む（古い点数を出さない）
const CACHE = 'kai-v1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())
));

self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin) return;
  if (u.pathname.endsWith('.json') && !u.pathname.endsWith('/manifest.json')) return;
  // まず新しく取りに行き、取れなければ手元の写し（電波が弱いときでもページだけは開ける）。?g= は違っても同じページ
  e.respondWith(
    fetch(e.request).then(r => {
      if (r.ok) { const c = r.clone(); caches.open(CACHE).then(x => x.put(e.request, c)); }
      return r;
    }).catch(() => caches.match(e.request, { ignoreSearch: true }).then(r => r || Response.error()))
  );
});
