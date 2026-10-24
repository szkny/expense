const container = document.getElementById("asset-content");

async function loadAssetContent() {
  try {
    const response = await fetch("/api/asset_management/content");
    if (!response.ok) throw new Error("資産データを取得できませんでした。");

    const html = await response.text();
    const documentFragment = new DOMParser().parseFromString(html, "text/html");
    const content = documentFragment.getElementById("asset-content");
    if (!container || !content)
      throw new Error("資産管理画面を表示できません。");

    container.innerHTML = content.innerHTML;
    try {
      await import("./main.js");
    } catch (error) {
      console.error("Failed to initialize the asset management page:", error);
    }
    loadSpreadsheetUrl();
  } catch (error) {
    if (!container) return;
    const card = document.createElement("div");
    card.className = "card";
    const message = document.createElement("p");
    message.textContent = error.message;
    const reloadButton = document.createElement("button");
    reloadButton.type = "button";
    reloadButton.className = "btn";
    reloadButton.textContent = "再読み込み";
    reloadButton.addEventListener("click", () => location.reload());
    card.append(message, reloadButton);
    container.replaceChildren(card);
  }
}

async function loadSpreadsheetUrl() {
  try {
    const response = await fetch("/api/asset_spreadsheet_url");
    if (!response.ok) return;
    const { url } = await response.json();
    const link = document.getElementById("asset-spreadsheet-link");
    if (link && typeof url === "string" && url) {
      link.href = url;
      link.hidden = false;
    }
  } catch {
    // Spreadsheet navigation is optional for rendering the page.
  }
}

loadAssetContent();
