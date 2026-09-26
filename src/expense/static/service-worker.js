const CACHE_NAME = "expense-cache-v3";
const urlsToCache = [
  "/",
  "/asset_management",
  "/static/style.css",
  "/static/js/main.js",
  "/static/js/chart.js",
  "/static/js/plotly_yaxis_autoscale.js",
  "/static/js/ui.js",
  "/static/js/table.js",
  "/static/preload.js",
  "/static/manifest.json",
  "/static/icon.png",
  "/static/js/notifications.js",
];

// 1. インストールイベント: アプリケーションシェルをキャッシュする
self.addEventListener("install", (event) => {
  console.log("Service Worker: Installing...");
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => {
        console.log("Service Worker: Caching app shell");
        return cache.addAll(urlsToCache);
      })
      .then(() => {
        self.skipWaiting(); // 新しいService Workerを即座に有効化する
      }),
  );
});

// 2. アクティベートイベント: 古いキャッシュを削除する
self.addEventListener("activate", (event) => {
  console.log("Service Worker: Activating...");
  event.waitUntil(
    caches
      .keys()
      .then((cacheNames) => {
        return Promise.all(
          cacheNames.map((cacheName) => {
            if (cacheName !== CACHE_NAME) {
              console.log("Service Worker: Deleting old cache", cacheName);
              return caches.delete(cacheName);
            }
          }),
        );
      })
      .then(() => self.clients.claim()), // すべてのクライアントを制御下に置く
  );
});

self.addEventListener("push", (event) => {
  let data = { title: "Expense", body: "通知があります。" };
  try {
    data = event.data ? event.data.json() : data;
  } catch {
    // 不正な通知データでも既定の通知を表示する。
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "Expense", {
      body: data.body || "通知があります。",
      icon: "/static/icon.png",
      tag: "expense-notification",
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clients) => {
        const client = clients.find((item) => "focus" in item);
        return client ? client.focus() : self.clients.openWindow("/");
      }),
  );
});

// 3. フェッチイベント: ネットワークファースト戦略
self.addEventListener("fetch", (event) => {
  // APIリクエストはキャッシュしない
  if (event.request.url.includes("/api/")) {
    event.respondWith(fetch(event.request));
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // ネットワークからのレスポンスが正常な場合
        // レスポンスをクローンしてキャッシュに保存
        const responseToCache = response.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(event.request, responseToCache);
        });
        return response;
      })
      .catch(() => {
        // ネットワークエラーの場合、キャッシュから返す
        console.log(
          "Service Worker: Fetch failed, returning from cache.",
          event.request.url,
        );
        return caches.match(event.request);
      }),
  );
});
