// Acha campos de documentos (CPF, RG...) vazios e visíveis, caixas de aceite desmarcadas e o campo de
// arquivo do currículo, e pede os valores ao service worker, que consulta o host do mcp-vagas (só termos
// de uso e privacidade são marcados; o currículo é o PDF personalizado da candidatura). A decisão (site confiável, empresa, confirmação) fica no host;
// aqui só há um filtro barato para não chamar o host em toda página.
(() => {
  if (window.__vagasCofre) return;
  window.__vagasCofre = true;

  const MAYBE_DOCUMENT = /cpf|\brg\b|identidade|registro geral|cnh|habilita|motorista|\bpis\b|pasep|\bnis\b|\bnit\b|ctps|carteira de trabalho|eleitor|passaporte|passport|m[aã]e\b|mother|emissor|expedidor|licen[cs]e/i;
  const MAYBE_CONSENT = /termo|condi[cç][oõ]es|privacidade|privacy|lgpd|terms|dados/i;
  const MAYBE_RESUME = /curr[ií]culo|curriculum|\bcv\b|resum[eé]/i;
  const TEXT_TYPES = new Set(["", "text", "tel", "number", "search"]);
  const seen = new WeakSet();
  const waiting = new WeakMap(); // campo de currículo ainda sem PDF -> { first, delay, next }
  const RETRY_FIRST = 3000;
  const RETRY_MAX = 30000;
  const RETRY_FOR = 20 * 60 * 1000;
  let retryTimer = null;
  const byId = new Map();
  let nextId = 0;
  let timer = null;

  const clean = (text) => (text || "").replace(/\s+/g, " ").trim();

  function labelOf(input) {
    const parts = [];
    for (const label of input.labels || []) parts.push(clean(label.textContent));
    if (input.getAttribute("role") === "checkbox") parts.push(clean(input.textContent));
    for (const id of (input.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean)) {
      parts.push(clean(document.getElementById(id)?.textContent));
    }
    parts.push(clean(input.getAttribute("aria-label")));
    let text = clean(parts.join(" "));
    // Sem rótulo associado: o texto do maior contêiner que só tem este campo.
    for (let node = input.parentElement, depth = 0; !text && node && depth < 4; node = node.parentElement, depth++) {
      if (node.querySelectorAll("input, select, textarea").length > 1) break;
      text = clean(node.textContent).slice(0, 120);
    }
    return text;
  }

  function attrsOf(input) {
    return ["name", "id", "placeholder", "autocomplete"].map((a) => input.getAttribute(a) || "").join(" ").trim();
  }

  function visible(input) {
    if (input.checkVisibility && !input.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
    const box = input.getBoundingClientRect();
    if (box.width < 4 || box.height < 4) return false;
    return box.right + window.scrollX > 0 && box.bottom + window.scrollY > 0;
  }

  function fillable(input) {
    return TEXT_TYPES.has((input.getAttribute("type") || "").toLowerCase()) && !input.disabled && !input.readOnly
      && !input.value && visible(input);
  }

  // Caixa nativa escondida sob um rótulo estilizado: vale a visibilidade do rótulo.
  function checkable(box) {
    if (box.getAttribute("role") === "checkbox") {
      return box.getAttribute("aria-checked") !== "true" && box.getAttribute("aria-disabled") !== "true" && visible(box);
    }
    return !box.checked && !box.disabled && (visible(box) || [...(box.labels || [])].some(visible));
  }

  // Campos de arquivo quase sempre ficam escondidos atrás de um botão: vale o rótulo ou o contêiner visível.
  function shownNear(input) {
    if (visible(input) || [...(input.labels || [])].some(visible)) return true;
    for (let node = input.parentElement, depth = 0; node && depth < 3; node = node.parentElement, depth++) {
      if (visible(node)) return true;
    }
    return false;
  }

  function attachFile(input, { name, type, data }) {
    const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
    const transfer = new DataTransfer();
    transfer.items.add(new File([bytes], name, { type }));
    input.files = transfer.files;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // Setter do protótipo + eventos: frameworks como React só enxergam o valor assim.
  function setValue(input, value) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  async function scan() {
    const fields = [];
    for (const input of document.querySelectorAll("input")) {
      if (seen.has(input) || !fillable(input)) continue;
      const text = labelOf(input);
      const attrs = attrsOf(input);
      if (!MAYBE_DOCUMENT.test(`${text} ${attrs}`)) continue;
      seen.add(input);
      const id = String(nextId++);
      byId.set(id, input);
      fields.push({ id, text, attrs, placeholder: input.getAttribute("placeholder") || "", maxlength: input.maxLength > 0 ? input.maxLength : null });
    }
    for (const box of document.querySelectorAll("input[type=checkbox], [role=checkbox]")) {
      if (seen.has(box) || !checkable(box)) continue;
      const text = labelOf(box);
      if (!MAYBE_CONSENT.test(text)) continue;
      seen.add(box);
      const id = String(nextId++);
      byId.set(id, box);
      fields.push({ id, kind: "checkbox", text });
    }
    const files = [];
    for (const input of document.querySelectorAll("input[type=file]")) {
      if (seen.has(input) || input.disabled || input.files?.length) continue;
      const text = labelOf(input);
      const attrs = attrsOf(input);
      if (!MAYBE_RESUME.test(`${text} ${attrs}`) || !shownNear(input)) continue;
      const retry = waiting.get(input);
      if (retry && Date.now() < retry.next) continue;
      const id = String(nextId++);
      byId.set(id, input);
      files.push([id, input]);
      fields.push({ id, kind: "file", text, attrs, accept: input.getAttribute("accept") || "" });
    }
    if (!fields.length) return;
    let response;
    try {
      response = await chrome.runtime.sendMessage({ type: "fill", fields });
    } catch (error) {
      return; // extensão recarregada ou service worker indisponível: nada a fazer nesta página
    }
    // O currículo personalizado só é gerado depois que o campo de upload aparece: sem PDF ainda, o campo
    // volta a ser consultado, com intervalo crescente, até receber o arquivo ou o preenchimento ser recusado.
    for (const [id, input] of files) {
      const got = response?.values?.[id];
      if (got || response?.status === "declined") {
        seen.add(input);
        waiting.delete(input);
        continue;
      }
      const before = waiting.get(input) || { first: Date.now(), delay: RETRY_FIRST / 2 };
      if (Date.now() - before.first > RETRY_FOR) {
        seen.add(input);
        waiting.delete(input);
        continue;
      }
      const delay = Math.min(before.delay * 2, RETRY_MAX);
      waiting.set(input, { first: before.first, delay, next: Date.now() + delay });
      clearTimeout(retryTimer);
      retryTimer = setTimeout(scan, delay);
    }
    for (const [id, value] of Object.entries(response?.values || {})) {
      const el = byId.get(id);
      if (!el) continue;
      if (value && typeof value === "object") {
        if (!el.files?.length) attachFile(el, value);
      } else if (value === true) {
        // Clique, não .checked: o framework da página só registra o aceite pelo evento.
        if (el.getAttribute("role") === "checkbox" ? el.getAttribute("aria-checked") !== "true" : !el.checked) el.click();
      } else if (!el.value) {
        setValue(el, value);
      }
    }
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(scan, 600);
  }

  new MutationObserver(schedule).observe(document.documentElement, {
    childList: true, subtree: true, attributes: true, attributeFilter: ["style", "class", "hidden"],
  });
  schedule();
})();
