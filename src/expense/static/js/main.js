// src/expense/static/js/main.js
import { initializeCharts } from "./chart.js";
import { initializeTableFilter } from "./table.js";
import { initSimulator } from "./simulator.js";
import { initNotifications } from "./notifications.js";
import {
  initMenu,
  initClosableMessages,
  initExpenseForm,
  initRecurringExpenseDialog,
  initFormLoaders,
  initThemeToggle,
  initScreenshotZoom,
  initOcrReload,
  initCollapsibleSections,
  initRecordEditor,
  initPwaInstall,
  initAssetMasking,
  initMemoAutocomplete,
  initChartReloadUI,
  initAssetAllocationLongPress,
  initCardReordering,
} from "./ui.js";

function onDOMContentLoaded() {
  initCardReordering();
  initCollapsibleSections();
  initAssetAdvisor();
  initializeCharts();
  initChartReloadUI();
  initializeTableFilter();
  initMenu();
  initClosableMessages();
  initExpenseForm();
  initRecurringExpenseDialog();
  initFormLoaders();
  initThemeToggle();
  initScreenshotZoom();
  initOcrReload();
  initRecordEditor();
  initPwaInstall();
  initAssetMasking();
  initMemoAutocomplete();
  initSimulator();
  initAssetAllocationLongPress();
  initNotifications().catch(() => {
    console.error("Web Push initialization failed");
  });
}

function initAssetAdviceChat(adviceContent) {
  const chat = document.getElementById("asset-advice-chat");
  const messagesContainer = document.getElementById(
    "asset-advice-chat-messages",
  );
  const status = document.getElementById("asset-advice-chat-status");
  const form = document.getElementById("asset-advice-chat-form");
  const input = document.getElementById("asset-advice-chat-input");
  const sendButton = document.getElementById("asset-advice-chat-send");
  const resetButton = document.getElementById("asset-advice-chat-reset");
  if (
    !chat ||
    !messagesContainer ||
    !status ||
    !form ||
    !input ||
    !sendButton ||
    !resetButton
  ) {
    return { resetForAdviceReload: () => {}, setReady: () => {} };
  }

  const storageKey = "expense.assetAdviceChat.v1";
  const history = [];
  const maxMessages = 20;
  let ready = false;
  let sending = false;

  const clearStoredHistory = () => {
    try {
      sessionStorage.removeItem(storageKey);
    } catch {
      // Chat remains usable when browser storage is unavailable.
    }
  };
  const saveHistory = () => {
    try {
      sessionStorage.setItem(
        storageKey,
        JSON.stringify({
          advice: adviceContent.innerText || adviceContent.textContent || "",
          messages: history,
        }),
      );
    } catch {
      // Chat remains usable when browser storage is unavailable or full.
    }
  };
  const restoreReplyHtml = (html) => {
    const template = document.createElement("template");
    template.innerHTML = html;
    const allowedTags = new Set([
      "A",
      "BLOCKQUOTE",
      "BR",
      "CODE",
      "DEL",
      "EM",
      "H1",
      "H2",
      "H3",
      "H4",
      "H5",
      "H6",
      "HR",
      "LI",
      "OL",
      "P",
      "PRE",
      "S",
      "STRONG",
      "SUB",
      "SUP",
      "TABLE",
      "TBODY",
      "TD",
      "TH",
      "THEAD",
      "TR",
      "UL",
    ]);
    const copyNode = (node) => {
      if (node.nodeType === Node.TEXT_NODE)
        return document.createTextNode(node.textContent || "");
      if (node.nodeType !== Node.ELEMENT_NODE)
        return document.createDocumentFragment();

      if (!allowedTags.has(node.tagName)) {
        const fragment = document.createDocumentFragment();
        for (const child of node.childNodes) fragment.append(copyNode(child));
        return fragment;
      }
      const element = document.createElement(node.tagName.toLowerCase());
      for (const child of node.childNodes) element.append(copyNode(child));
      if (node.tagName === "A") {
        try {
          const url = new URL(node.getAttribute("href"), window.location.href);
          if (!["http:", "https:"].includes(url.protocol))
            return document.createDocumentFragment();
          element.href = url.href;
          element.target = "_blank";
          element.rel = "noopener noreferrer";
        } catch {
          return document.createDocumentFragment();
        }
      }
      return element;
    };
    const fragment = document.createDocumentFragment();
    for (const child of template.content.childNodes)
      fragment.append(copyNode(child));
    return fragment;
  };
  const restoreHistory = () => {
    try {
      const stored = JSON.parse(sessionStorage.getItem(storageKey) || "null");
      const advice = adviceContent.innerText || adviceContent.textContent || "";
      if (
        stored?.advice !== advice ||
        !Array.isArray(stored.messages) ||
        stored.messages.length > maxMessages ||
        stored.messages.length % 2 !== 0
      ) {
        clearStoredHistory();
        return;
      }
      const validMessages = stored.messages.every((message, index) => {
        const expectedRole = index % 2 === 0 ? "user" : "assistant";
        const maxLength = expectedRole === "user" ? 1500 : 6000;
        return (
          message?.role === expectedRole &&
          typeof message.content === "string" &&
          message.content.trim().length > 0 &&
          message.content.length <= maxLength &&
          (message.timestamp === undefined ||
            (typeof message.timestamp === "string" &&
              Number.isFinite(Date.parse(message.timestamp)))) &&
          (expectedRole === "user" ||
            (typeof message.html === "string" && message.html.length <= 50000))
        );
      });
      if (!validMessages) {
        clearStoredHistory();
        return;
      }

      history.push(...stored.messages);
      for (const message of history) {
        if (message.role === "user") {
          const bubble = appendMessage("user", message.content);
          appendMessageTime(bubble, message.timestamp);
        } else {
          const bubble = appendMessage("assistant", "");
          bubble.append(restoreReplyHtml(message.html));
          appendMessageTime(bubble, message.timestamp);
        }
      }
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
      status.textContent = `${history.length / 2}/10往復`;
    } catch {
      clearStoredHistory();
    }
  };

  const updateControls = () => {
    sendButton.disabled =
      !ready || sending || !input.value.trim() || history.length >= maxMessages;
    input.disabled = !ready || sending;
    resetButton.disabled = sending;
  };
  const appendMessage = (role, text, html = null, pending = false) => {
    const message = document.createElement("div");
    message.className = `asset-advice-chat-message ${role}`;
    if (pending) message.classList.add("pending");
    if (html !== null) message.innerHTML = html;
    else message.textContent = text;
    messagesContainer.append(message);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return message;
  };
  const appendMessageTime = (message, timestamp) => {
    if (typeof timestamp !== "string") return;
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return;
    const time = document.createElement("time");
    time.className = "asset-advice-chat-time";
    time.dateTime = date.toISOString();
    time.textContent = new Intl.DateTimeFormat("ja-JP", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
    message.append(time);
  };
  const appendSources = (message, sources) => {
    if (!Array.isArray(sources)) return;
    const links = sources.flatMap((source) => {
      if (typeof source?.title !== "string" || typeof source?.url !== "string")
        return [];
      try {
        const url = new URL(source.url);
        return url.protocol === "https:" ? [{ title: source.title, url }] : [];
      } catch {
        return [];
      }
    });
    if (links.length === 0) return;

    const section = document.createElement("div");
    section.className = "asset-advice-chat-sources";
    const heading = document.createElement("p");
    heading.textContent = "参照したWeb情報";
    section.append(heading);
    const list = document.createElement("ul");
    for (const source of links) {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = source.url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = source.title || source.url.hostname;
      item.append(link);
      list.append(item);
    }
    section.append(list);
    message.append(section);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  };
  const reset = (hide) => {
    history.length = 0;
    clearStoredHistory();
    messagesContainer.replaceChildren();
    status.textContent = "";
    input.value = "";
    chat.hidden = hide;
    updateControls();
  };
  const setReady = (value) => {
    ready = value;
    chat.hidden = !ready;
    if (ready && history.length === 0) restoreHistory();
    updateControls();
  };

  input.addEventListener("input", updateControls);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  resetButton.addEventListener("click", () => reset(false));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question || sending || !ready) return;
    if (history.length >= maxMessages) {
      status.textContent = "会話は10往復までです。リセットして続けてください。";
      return;
    }

    const userMessage = {
      role: "user",
      content: question,
      timestamp: new Date().toISOString(),
    };
    const userBubble = appendMessage("user", question);
    appendMessageTime(userBubble, userMessage.timestamp);
    const pendingBubble = appendMessage(
      "assistant",
      "AIが回答を生成中",
      null,
      true,
    );
    pendingBubble.setAttribute("role", "status");
    const typingIndicator = document.createElement("span");
    typingIndicator.className = "asset-advice-typing-indicator";
    typingIndicator.setAttribute("aria-hidden", "true");
    for (let index = 0; index < 3; index += 1) {
      typingIndicator.append(document.createElement("span"));
    }
    pendingBubble.append(typingIndicator);
    sending = true;
    status.textContent = "";
    input.value = "";
    updateControls();
    try {
      const response = await fetch("/api/asset_advice/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          advice: adviceContent.innerText || adviceContent.textContent,
          messages: [
            ...history.map(({ role, content }) => ({ role, content })),
            { role: userMessage.role, content: userMessage.content },
          ],
        }),
      });
      if (!response.ok) {
        const result = await response.json();
        throw new Error(result.error || `HTTP ${response.status}`);
      }
      if (!response.body) throw new Error("応答を受信できません。");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let replyMarkdown = "";
      let replyHtml = "";
      let replyTimestamp = "";
      let completed = false;
      while (!completed) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), {
          stream: !done,
        });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";
        for (const eventText of events) {
          const dataLine = eventText
            .split("\n")
            .find((line) => line.startsWith("data: "));
          if (!dataLine) continue;
          const result = JSON.parse(dataLine.slice(6));
          if (result.error) throw new Error(result.error);
          if (typeof result.reply_html === "string") {
            if (result.reply_html.trim()) {
              pendingBubble.innerHTML = result.reply_html;
              pendingBubble.classList.remove("pending");
              pendingBubble.removeAttribute("role");
              messagesContainer.scrollTop = messagesContainer.scrollHeight;
            }
          }
          if (result.done) {
            if (typeof result.reply_markdown !== "string")
              throw new Error("返答を取得できませんでした。");
            replyMarkdown = result.reply_markdown;
            appendSources(pendingBubble, result.sources);
            replyHtml = pendingBubble.innerHTML;
            replyTimestamp = new Date().toISOString();
            appendMessageTime(pendingBubble, replyTimestamp);
            completed = true;
            break;
          }
        }
        if (done) break;
      }
      if (!completed) throw new Error("応答が途中で終了しました。");

      history.push(userMessage, {
        role: "assistant",
        content: replyMarkdown,
        html: replyHtml,
        timestamp: replyTimestamp,
      });
      saveHistory();
      status.textContent =
        history.length >= maxMessages
          ? "10/10往復に達しました。リセットして続けてください。"
          : `${history.length / 2}/10往復`;
    } catch (error) {
      userBubble.remove();
      pendingBubble.remove();
      input.value = question;
      status.textContent = error.message;
    } finally {
      sending = false;
      updateControls();
    }
  });

  return {
    resetForAdviceReload: () => {
      ready = false;
      reset(true);
    },
    setReady,
  };
}

function initAssetAdvisor() {
  const card = document.querySelector('[data-card-key="asset-advice"]');
  const trigger = card?.querySelector(".collapsible-trigger");
  const status = document.getElementById("asset-advice-status");
  const content = document.getElementById("asset-advice-content");
  const retryButton = document.getElementById("asset-advice-retry");
  if (!card || !trigger || !status || !content || !retryButton) return;

  const chat = initAssetAdviceChat(content);
  let loading = false;
  const formatGeneratedAt = (generatedAt) => {
    const date = new Date(generatedAt);
    if (Number.isNaN(date.getTime())) return "";
    const pad = (value) => String(value).padStart(2, "0");
    return `${date.getFullYear()}年${pad(date.getMonth() + 1)}月${pad(
      date.getDate(),
    )}日 ${pad(date.getHours())}:${pad(date.getMinutes())}時点`;
  };
  const loadAdvice = async (force = false) => {
    if (loading) return;
    loading = true;
    const previousAdvice = force
      ? { html: content.innerHTML, hidden: content.hidden }
      : null;
    if (force) chat.resetForAdviceReload();
    retryButton.hidden = true;
    status.textContent = "資産データをもとに分析中...";
    try {
      const endpoint = force
        ? "/api/asset_advice/stream?force=true"
        : "/api/asset_advice/stream";
      const response = await fetch(endpoint, { method: "POST" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      if (!response.body) throw new Error("ストリームを受信できません。");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;
      while (!completed) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";
        for (const eventText of events) {
          const dataLine = eventText
            .split("\n")
            .find((line) => line.startsWith("data: "));
          if (!dataLine) continue;
          const result = JSON.parse(dataLine.slice(6));
          if (result.error) throw new Error(result.error);
          content.innerHTML = result.advice_html;
          content.hidden = false;
          status.textContent = result.done
            ? formatGeneratedAt(result.generated_at) || "生成日時不明"
            : "資産データをもとに分析中...";
          completed = result.done;
        }
        if (done) break;
      }
      if (!completed) throw new Error("分析結果の受信が途中で終了しました。");
      retryButton.hidden = false;
      chat.setReady(true);
    } catch (error) {
      if (previousAdvice && !previousAdvice.hidden)
        content.innerHTML = previousAdvice.html;
      status.textContent = error.message;
      retryButton.hidden = false;
      chat.setReady(Boolean(previousAdvice && !previousAdvice.hidden));
    } finally {
      loading = false;
    }
  };

  retryButton.addEventListener("click", () => loadAdvice(true));
  let cardVisible = false;
  let observer = null;
  const loadWhenOpenAndVisible = () => {
    if (cardVisible && trigger.getAttribute("aria-expanded") === "true") {
      observer?.disconnect();
      loadAdvice();
    }
  };
  trigger.addEventListener("click", loadWhenOpenAndVisible);

  if ("IntersectionObserver" in window) {
    observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        cardVisible = true;
        loadWhenOpenAndVisible();
      },
      { rootMargin: "160px" },
    );
    observer.observe(card);
  } else {
    window.setTimeout(() => {
      cardVisible = true;
      loadWhenOpenAndVisible();
    }, 0);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", onDOMContentLoaded);
} else {
  onDOMContentLoaded();
}
