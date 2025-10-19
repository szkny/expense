// src/expense/static/js/table.js

const HIRAGANA_START = "ぁ".charCodeAt(0);
const KATAKANA_START = "ァ".charCodeAt(0);
const KATAKANA_END = "ヶ".charCodeAt(0);
const OFFSET = KATAKANA_START - HIRAGANA_START;

function katakanaToHiragana(str) {
  return str
    .split("")
    .map((ch) => {
      const code = ch.charCodeAt(0);
      if (code >= KATAKANA_START && code <= KATAKANA_END) {
        return String.fromCharCode(code - OFFSET);
      }
      return ch;
    })
    .join("");
}

function fuzzyMatch(pattern, text) {
  pattern = katakanaToHiragana(pattern.toLowerCase());
  text = katakanaToHiragana(text.toLowerCase());
  let patternIdx = 0;
  let textIdx = 0;
  let score = 0;
  while (patternIdx < pattern.length && textIdx < text.length) {
    if (pattern[patternIdx] === text[textIdx]) {
      score += 1;
      patternIdx++;
    }
    textIdx++;
  }
  return patternIdx === pattern.length ? score : 0;
}

function filterTable() {
  const inputElement = document.getElementById("search-input");
  if (!inputElement) return;
  const input = inputElement.value.trim();
  const table = document.querySelector("table tbody");
  if (!table) return;
  const rows = table.getElementsByTagName("tr");
  let total = 0;
  let n_match = 0;

  const headers = Array.from(document.querySelectorAll("thead th")).map(
    (th) => th.textContent,
  );
  const isAssetTable = headers.includes("銘柄");

  for (let i = 0; i < rows.length; i++) {
    const cells = rows[i].getElementsByTagName("td");
    let text = "";
    if (isAssetTable) {
      if (cells.length > 0) {
        text = cells[0].textContent || "";
      }
    } else {
      if (cells.length < 4) continue;
      const date = cells[0].textContent || "";
      const expenseType = cells[1].textContent || "";
      const memo = cells[3].textContent || "";
      text = date + " " + expenseType + " " + memo;
    }

    const score = fuzzyMatch(input, text);
    if (!input || score > 0) {
      rows[i].style.display = "";
      if (!isAssetTable) {
        const amountText = cells[2].textContent.replace(/[^\d]/g, "");
        total += parseInt(amountText, 10) || 0;
        n_match += 1;
      }
    } else {
      rows[i].style.display = "none";
    }
  }

  if (!isAssetTable) {
    const totalAmount = document.getElementById("total-amount");
    if (totalAmount) {
      if (input && total) {
        totalAmount.textContent = `合計: ¥${total.toLocaleString()}  (${n_match}件)`;
        totalAmount.style.display = "block";
      } else {
        totalAmount.textContent = "";
        totalAmount.style.display = "none";
      }
    }
  }

  const clearButton = document.getElementById("clear-search");
  if (clearButton) {
    clearButton.style.display = input ? "block" : "none";
  }
}

export function initializeTableFilter() {
  const searchInput = document.getElementById("search-input");
  if (searchInput) {
    searchInput.addEventListener("keyup", filterTable);
    // Initial filter on page load in case of back/forward navigation
    filterTable();
  }

  const clearButton = document.getElementById("clear-search");
  if (clearButton) {
    clearButton.addEventListener("click", () => {
      const input = document.getElementById("search-input");
      if (input) {
        input.value = "";
        filterTable();
      }
    });
  }
}
