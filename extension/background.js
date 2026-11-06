// Ponte entre a página e o host do mcp-vagas (native messaging). A confirmação por empresa abre numa
// janela da própria extensão: nem a página nem um agente que controla a aba conseguem respondê-la.
const HOST = "com.barbieriht.vagas";
const CONFIRM_PAGE = chrome.runtime.getURL("confirm.html");
const pending = new Map(); // id da confirmação -> { details, resolve, windowId }
const asking = new Map(); // aba|chave -> Promise da resposta (uma janela por empresa, mesmo com vários campos)

function fromConfirmPage(sender) {
  return sender.id === chrome.runtime.id && (sender.url || "").startsWith(CONFIRM_PAGE);
}

async function badge(tabId, text, title) {
  try {
    await chrome.action.setBadgeText({ tabId, text });
    await chrome.action.setTitle({ tabId, title: `Vagas: ${title}` });
  } catch (error) {
    // aba fechada no meio do caminho
  }
}

async function remembered(key) {
  return (await chrome.storage.session.get(key))[key];
}

function ask(cacheKey, details) {
  if (asking.has(cacheKey)) return asking.get(cacheKey);
  const id = crypto.randomUUID();
  const answer = new Promise((resolve) => {
    pending.set(id, { details, resolve });
    chrome.windows.create({ url: `${CONFIRM_PAGE}?id=${id}`, type: "popup", width: 520, height: 460, focused: true })
      .then((win) => { if (pending.has(id)) pending.get(id).windowId = win.id; })
      .catch(() => resolve("no"));
  }).finally(() => { pending.delete(id); asking.delete(cacheKey); });
  asking.set(cacheKey, answer);
  return answer;
}

async function fill(message, sender) {
  const tabId = sender.tab.id;
  const request = { url: sender.url, fields: message.fields, confirm: null };
  let response = await chrome.runtime.sendNativeMessage(HOST, request);
  if (response.status === "confirm") {
    const cacheKey = `${tabId}|${response.origin.key}`;
    let answer = await remembered(cacheKey);
    if (!answer) {
      answer = await ask(cacheKey, { ...response, title: sender.tab.title || "", pageUrl: sender.url });
      if (answer !== "always") await chrome.storage.session.set({ [cacheKey]: answer });
    }
    if (answer === "no") {
      await badge(tabId, "", "preenchimento recusado nesta aba");
      return { status: "declined" };
    }
    response = await chrome.runtime.sendNativeMessage(HOST, { ...request, confirm: answer });
  }
  if (response.status === "filled") await badge(tabId, "OK", `preenchido (${response.label})`);
  if (response.status === "error") await badge(tabId, "!", response.message);
  return response;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "fill" && sender.tab && sender.id === chrome.runtime.id && !fromConfirmPage(sender)) {
    fill(message, sender).then(sendResponse, async (error) => {
      await badge(sender.tab.id, "!", `host do mcp-vagas indisponível: ${error.message || error}`);
      sendResponse({ status: "error", message: String(error.message || error) });
    });
    return true;
  }
  if (message.type === "confirm-details" && fromConfirmPage(sender)) {
    sendResponse(pending.get(message.id)?.details || null);
  } else if (message.type === "confirm-answer" && fromConfirmPage(sender)) {
    const entry = pending.get(message.id);
    const answer = ["always", "once", "no"].includes(message.answer) ? message.answer : "no";
    if (entry) entry.resolve(entry.details.origin.remember || answer !== "always" ? answer : "once");
    sendResponse(true);
  } else if (message.type === "keepalive" && fromConfirmPage(sender)) {
    sendResponse(true); // a janela de confirmação mantém o service worker vivo enquanto espera
  }
  return false;
});

chrome.windows.onRemoved.addListener((windowId) => {
  for (const entry of pending.values()) {
    if (entry.windowId === windowId) entry.resolve("no");
  }
});
