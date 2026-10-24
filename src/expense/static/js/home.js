const container = document.getElementById("home-content");
const registerTrigger = document.querySelector(
  '.collapsible-trigger[data-key="register"]',
);

if (registerTrigger) {
  const registerContainer = document.getElementById("register-container");
  registerTrigger.dataset.collapsibleInitialized = "true";
  registerTrigger.setAttribute(
    "aria-expanded",
    String(document.documentElement.classList.contains("register-open")),
  );
  registerTrigger.addEventListener("click", () => {
    const collapsed =
      !document.documentElement.classList.contains("register-collapsed");
    document.documentElement.classList.toggle("register-collapsed", collapsed);
    document.documentElement.classList.toggle("register-open", !collapsed);
    registerContainer?.classList.toggle("is-open", !collapsed);
    registerTrigger.setAttribute("aria-expanded", String(!collapsed));
    try {
      localStorage.setItem("registerCollapsed", String(collapsed));
    } catch {
      // The input section remains usable when storage is unavailable.
    }
  });
}

async function loadHomeContent() {
  try {
    const response = await fetch("/api/home");
    if (!response.ok) throw new Error("家計簿データを取得できませんでした。");

    const html = await response.text();
    const documentFragment = new DOMParser().parseFromString(html, "text/html");
    const content = documentFragment.getElementById("home-content");
    if (!container || !content) throw new Error("家計簿画面を表示できません。");

    const currentTypeSelect = document.getElementById("expense-type");
    const loadedTypeSelect = documentFragment.getElementById("expense-type");
    if (currentTypeSelect && loadedTypeSelect) {
      const selectedType = currentTypeSelect.value;
      const wasFocused = document.activeElement === currentTypeSelect;
      currentTypeSelect.replaceChildren(
        ...Array.from(loadedTypeSelect.options, (option) =>
          option.cloneNode(true),
        ),
      );
      if (
        Array.from(currentTypeSelect.options).some(
          (option) => option.value === selectedType,
        )
      ) {
        currentTypeSelect.value = selectedType;
      }
      if (wasFocused) currentTypeSelect.focus({ preventScroll: true });
    }

    const registerCard = container.querySelector('[data-card-key="register"]');
    const loadedCards = Array.from(content.children).filter(
      (card) => card.dataset.cardKey !== "register",
    );
    container.replaceChildren(registerCard, ...loadedCards);
    try {
      await import("./main.js");
    } catch (error) {
      console.error("Failed to initialize the home page:", error);
    }
    loadSpreadsheetUrl();
  } catch (error) {
    if (container) {
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
      const registerCard = container.querySelector(
        '[data-card-key="register"]',
      );
      if (registerCard) {
        container.replaceChildren(registerCard, card);
      } else {
        container.replaceChildren(card);
      }
    }
  }
}

async function loadSpreadsheetUrl() {
  try {
    const response = await fetch("/api/spreadsheet_url");
    if (!response.ok) return;
    const { url } = await response.json();
    const link = document.getElementById("spreadsheet-link");
    if (link && typeof url === "string" && url) {
      link.href = url;
      link.hidden = false;
    }
  } catch {
    // Spreadsheet navigation is optional for rendering the page.
  }
}

loadHomeContent();
