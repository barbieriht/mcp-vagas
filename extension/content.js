// Acha campos de documentos (CPF, RG...) vazios e visíveis, caixas de aceite desmarcadas e o campo de
// arquivo do currículo, e pede os valores ao service worker, que consulta o host do mcp-vagas (só termos
// de uso e privacidade são marcados; o currículo é o PDF personalizado da candidatura). A decisão (site confiável, empresa, confirmação) fica no host;
// aqui só há um filtro barato para não chamar o host em toda página.
(() => {
  if (window.__vagasCofre) return;
  window.__vagasCofre = true;

  const MAYBE_DOCUMENT = /cpf|\brg\b|identidade|registro geral|cnh|habilita|motorista|\bpis\b|pasep|\bnis\b|\bnit\b|ctps|carteira de trabalho|eleitor|passaporte|passport|m[aã]e\b|mother|emissor|expedidor|licen[cs]e/i;
  const MAYBE_CONSENT = /termo|condi[cç][oõ]es|privacidade|privacy|lgpd|terms|dados|personal data|consent|concord|agree|aceit/i;
  // Rótulo que só diz "Concordo": o texto do aceite fica no bloco logo antes da caixa (ex.: Cornerstone).
  const GENERIC_CONSENT = /^(li e )?(concordo|aceito|de acordo|autorizo|sim|i agree|agree|i accept|accept|yes|ok)\b[\s.!]*$/i;
  const LINKEDIN = /(^|\.)linkedin\.com$/.test(location.hostname);
  const MAYBE_RESUME = /curr[ií]culo|curriculum|\bcv\b|resum[eé]/i;
  const TEXT_TYPES = new Set(["", "text", "tel", "number", "search"]);
  const seen = new WeakSet();
  const waiting = new WeakMap(); // campo de currículo ainda sem PDF -> { first, delay, next }
  const RETRY_FIRST = 3000;
  const RETRY_MAX = 30000;
  const RETRY_FOR = 20 * 60 * 1000;
  let retryTimer = null;
  let pageRetry = null; // { first, delay }: página recusada ou sem nada a preencher, consultada de novo
  let lastProbe = 0;
  const observedRoots = new WeakSet();
  const byId = new Map();
  let nextId = 0;
  let timer = null;

  const clean = (text) => (text || "").replace(/\s+/g, " ").trim();

  // Raízes onde procurar campos: o documento e os shadow roots abertos (o modal do LinkedIn pode viver num deles).
  function roots() {
    const found = [document];
    for (let i = 0; i < found.length; i++) {
      for (const el of found[i].querySelectorAll("*")) {
        if (el.shadowRoot && !found.includes(el.shadowRoot)) found.push(el.shadowRoot);
      }
    }
    for (const root of found.slice(1)) {
      if (!observedRoots.has(root)) {
        observedRoots.add(root);
        observer.observe(root, OBSERVE);
      }
    }
    return found;
  }

  function queryAll(selector, list = roots()) {
    return list.flatMap((root) => [...root.querySelectorAll(selector)]);
  }

  // Texto do primeiro bloco antes do campo (subindo até 4 níveis), sem passar por outro campo.
  function precedingText(input) {
    for (let node = input, depth = 0; node && depth < 4; node = node.parentElement, depth++) {
      for (let prev = node.previousElementSibling; prev; prev = prev.previousElementSibling) {
        if (prev.querySelector && prev.querySelector("input, select, textarea")) return "";
        const text = clean(prev.textContent);
        if (text) return text.slice(0, 600);
      }
    }
    return "";
  }

  function consentText(box) {
    const text = labelOf(box);
    if (text && !GENERIC_CONSENT.test(text)) return text;
    const before = precedingText(box);
    return before ? clean(`${before} ${text}`) : text;
  }

  function labelOf(input) {
    const parts = [];
    for (const label of input.labels || []) parts.push(clean(label.textContent));
    if (input.getAttribute("role") === "checkbox") parts.push(clean(input.textContent));
    for (const id of (input.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean)) {
      parts.push(clean((input.getRootNode().getElementById?.(id) || document.getElementById(id))?.textContent));
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
    // Caixa nativa escondida sob um componente sem <label> (ex.: InHire): vale o contêiner visível.
    return !box.checked && !box.disabled && (visible(box) || [...(box.labels || [])].some(visible) || shownNear(box));
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
    const sentOthers = []; // documentos e caixas enviados: voltam a ser consultados se a página for recusada
    const all = roots();
    for (const input of queryAll("input", all)) {
      if (seen.has(input) || !fillable(input)) continue;
      const text = labelOf(input);
      const attrs = attrsOf(input);
      if (!MAYBE_DOCUMENT.test(`${text} ${attrs}`)) continue;
      seen.add(input);
      sentOthers.push(input);
      const id = String(nextId++);
      byId.set(id, input);
      fields.push({ id, text, attrs, placeholder: input.getAttribute("placeholder") || "", maxlength: input.maxLength > 0 ? input.maxLength : null });
    }
    for (const box of queryAll("input[type=checkbox], [role=checkbox]", all)) {
      if (seen.has(box) || !checkable(box)) continue;
      const text = consentText(box);
      if (!MAYBE_CONSENT.test(text)) continue;
      seen.add(box);
      sentOthers.push(box);
      const id = String(nextId++);
      byId.set(id, box);
      fields.push({ id, kind: "checkbox", text });
    }
    const files = [];
    for (const input of queryAll("input[type=file]", all)) {
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
    if (!fields.length) {
      if (LINKEDIN) probe(all);
      return;
    }
    let response;
    try {
      response = await chrome.runtime.sendMessage({ type: "fill", fields });
    } catch (error) {
      response = null; // service worker indisponível: tenta de novo mais tarde
    }
    // Recusada (o site ainda não é de uma candidatura aberta) ou sem nada a preencher: o site pode virar confiável
    // (o currículo gerado grava o form_url) ou o perfil mudar; as caixas e os documentos voltam a ser consultados.
    if (!response || ["refused", "nothing", "error"].includes(response.status)) {
      for (const el of sentOthers) seen.delete(el);
      const before = pageRetry || { first: Date.now(), delay: RETRY_FIRST / 2 };
      if (sentOthers.length && Date.now() - before.first <= RETRY_FOR) {
        pageRetry = { first: before.first, delay: Math.min(before.delay * 2, RETRY_MAX * 2) };
        clearTimeout(retryTimer);
        retryTimer = setTimeout(scan, pageRetry.delay);
      }
    } else {
      pageRetry = null;
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
        if (!el.files?.length) {
          attachFile(el, value);
          if (LINKEDIN) selectUploaded(value.name);
        }
      } else if (value === true) {
        // Clique, não .checked: o framework da página só registra o aceite pelo evento.
        if (el.getAttribute("role") === "checkbox" ? el.getAttribute("aria-checked") !== "true" : !el.checked) el.click();
      } else if (!el.value) {
        setValue(el, value);
      }
    }
  }

  // LinkedIn Easy Apply: depois de subir o PDF, a lista de currículos pode manter o antigo selecionado. Marca o
  // rádio do arquivo novo, pelo nome; nunca clica em botões (Next, Review, Submit, "Tailor resume with AI").
  function selectUploaded(name) {
    const started = Date.now();
    const base = name.replace(/\.pdf$/i, "");
    const tick = () => {
      const all = roots();
      const label = queryAll("[role=dialog] *, .artdeco-modal *", all).find((el) => !el.children.length
        && (clean(el.textContent) === name || clean(el.textContent) === base));
      let radio = null;
      for (let node = label, depth = 0; node && !radio && depth < 6; node = node.parentElement, depth++) {
        const radios = node.querySelectorAll("input[type=radio], [role=radio]");
        if (radios.length === 1) radio = radios[0];
        else if (radios.length > 1) break;
      }
      if (radio) {
        const checked = radio.getAttribute("role") === "radio" ? radio.getAttribute("aria-checked") === "true" : radio.checked;
        if (!checked) radio.click();
        chrome.runtime.sendMessage({ type: "fill", fields: [], probe: { resume_selected: true } }).catch(() => {});
      } else if (Date.now() - started < 12000) {
        setTimeout(tick, 500);
      } else {
        chrome.runtime.sendMessage({ type: "fill", fields: [], probe: { resume_selected: false } }).catch(() => {});
      }
    };
    setTimeout(tick, 500);
  }

  // Modal do Easy Apply aberto sem campo de arquivo à vista: conta o que a extensão vê (sem textos nem valores),
  // para o extension_status mostrar por que o currículo não entrou. No máximo uma vez a cada 30 s.
  function probe(all) {
    if (Date.now() - lastProbe < 30000) return;
    const dialog = queryAll("[role=dialog], .artdeco-modal", all).find((el) => MAYBE_RESUME.test(el.textContent || ""));
    if (!dialog) return;
    lastProbe = Date.now();
    const files = queryAll("input[type=file]", all);
    chrome.runtime.sendMessage({ type: "fill", fields: [], probe: {
      dialog: true, file_inputs: files.length, file_inputs_shown: files.filter(shownNear).length,
      shadow_roots: all.length - 1, frames: document.querySelectorAll("iframe").length, top: window === window.top,
    } }).catch(() => {});
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(scan, 600);
  }

  const OBSERVE = { childList: true, subtree: true, attributes: true, attributeFilter: ["style", "class", "hidden"] };
  const observer = new MutationObserver(schedule);
  observer.observe(document.documentElement, OBSERVE);
  schedule();
})();
