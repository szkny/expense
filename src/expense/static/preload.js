if (localStorage.getItem("theme") === "dark")
  document.documentElement.classList.add("dark");

(function() {
  function preloadCollapsedOrOpen(key) {
    if (!key) return;
    document.documentElement.classList.add(
      localStorage.getItem(key + "Collapsed") === "true"
        ? key + "-collapsed"
        : key + "-open",
    );
  }
  preloadCollapsedOrOpen("ocr");
  preloadCollapsedOrOpen("record");
  preloadCollapsedOrOpen("report");
  preloadCollapsedOrOpen("asset-record");
  preloadCollapsedOrOpen("asset-report");
})();
