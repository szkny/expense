const lastPageStorageKey = "expense.lastPage";
const pagePaths = ["/", "/asset_management", "/simulator"];

try {
  const currentPath = location.pathname;
  const lastPage = localStorage.getItem(lastPageStorageKey);

  // ルートへの再訪時だけ、前回開いていたページへ戻す。
  if (currentPath === "/" && pagePaths.includes(lastPage) && lastPage !== "/") {
    location.replace(lastPage);
  } else if (pagePaths.includes(currentPath)) {
    localStorage.setItem(lastPageStorageKey, currentPath);
  }

  // メニューのフォーム遷移では、リダイレクト前に遷移先を保存する。
  document.addEventListener("click", (event) => {
    const form = event.target.closest("form");
    if (!form) return;

    const targetPath = new URL(form.action, location.href).pathname;
    if (pagePaths.includes(targetPath)) {
      localStorage.setItem(lastPageStorageKey, targetPath);
    }
  });
} catch {
  // localStorageが利用できない環境でもページ自体は表示する。
}

if (localStorage.getItem("theme") === "dark")
  document.documentElement.classList.add("dark");

if (localStorage.getItem("isAssetMasked") === "true")
  document.documentElement.classList.add("asset-masked");

(function () {
  const keys = [
    "register",
    "ocr",
    "record",
    "report",
    "asset-record",
    "asset-chart",
    "asset-allocation",
    "asset-report",
  ];
  keys.forEach((key) => {
    const isCollapsed = localStorage.getItem(key + "Collapsed");
    let shouldBeOpen;
    if (isCollapsed === null) {
      // 初回アクセス時はレポート系のみ開く
      shouldBeOpen = key.includes("report");
    } else {
      shouldBeOpen = isCollapsed === "false";
    }
    document.documentElement.classList.add(
      shouldBeOpen ? key + "-open" : key + "-collapsed",
    );
  });
})();
