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
