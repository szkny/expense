function decodeBase64Url(value) {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(base64);
  return Uint8Array.from(raw, (character) => character.charCodeAt(0));
}

export async function initNotifications() {
  const enableButton = document.getElementById("notification-btn");
  if (
    !("serviceWorker" in navigator) ||
    !("PushManager" in window) ||
    !("Notification" in window)
  )
    return;

  const configResponse = await fetch("/api/notifications/config");
  if (!configResponse.ok) {
    const result = await configResponse.json().catch(() => ({}));
    const detail =
      result.error ||
      `通知設定の取得に失敗しました (HTTP ${configResponse.status})`;
    if (enableButton) {
      enableButton.hidden = false;
      enableButton.disabled = true;
      enableButton.textContent = `通知設定エラー: ${detail}`;
      enableButton.title = detail;
    }
    return;
  }
  const config = await configResponse.json();
  if (!config.enabled || !config.public_key) return;

  const subscribe = async () => {
    if (enableButton) {
      enableButton.disabled = true;
      enableButton.textContent = "通知を登録中...";
    }
    const permission =
      Notification.permission === "default"
        ? await Notification.requestPermission()
        : Notification.permission;
    if (permission !== "granted") {
      if (enableButton) {
        enableButton.disabled = false;
        enableButton.textContent =
          permission === "denied"
            ? "ブラウザ設定で通知を許可してください"
            : "🔔 通知を有効化";
      }
      return;
    }

    const registration = await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: decodeBase64Url(config.public_key),
      });
    }

    const response = await fetch("/api/notifications/subscription", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(subscription),
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(
        result.error || `購読登録に失敗しました (HTTP ${response.status})`,
      );
    }
    if (enableButton) enableButton.hidden = true;
  };

  const showRetryButton = (error) => {
    console.error("Web Push subscription failed", error);
    if (!enableButton) return;
    enableButton.hidden = false;
    enableButton.disabled = false;
    const detail = error instanceof Error ? error.message : String(error);
    enableButton.textContent = `通知登録失敗: ${detail}`;
    enableButton.title = detail;
  };

  if (enableButton) {
    enableButton.hidden = Notification.permission === "granted";
    enableButton.addEventListener("click", () => {
      subscribe().catch(showRetryButton);
    });
  }

  if (Notification.permission === "granted") {
    try {
      await subscribe();
    } catch (error) {
      showRetryButton(error);
    }
  } else if (enableButton) {
    enableButton.hidden = false;
  }
}
