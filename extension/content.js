// Acha campos de documentos (CPF, RG...) vazios e visíveis e pede os valores ao service worker,
// que consulta o host do mcp-vagas. A decisão (site confiável, empresa, confirmação) fica no host;
// aqui só há um filtro barato para não chamar o host em toda página.
(() => {
  if (window.__vagasCofre) return;
  window.__vagasCofre = true;

  const MAYBE_DOCUMENT = /cpf|\brg\b|identidade|registro geral|cnh|habilita|motorista|\bpis\b|pasep|\bnis\b|\bnit\b|ctps|carteira de trabalho|eleitor|passaporte|passport|m[aã]e\b|mother|emissor|expedidor|licen[cs]e/i;
  const TEXT_TYPES = new Set(["", "text", "tel", "number", "search"]);
  const seen = new WeakSet();
  const byId = new Map();
  let nextId = 0;
  let timer = null;

  const clean = (text) => (text || "").replace(/\s+/g, " ").trim();

  function labelOf(input) {
    const parts = [];
    for (const label of input.labels || []) parts.push(clean(label.textContent));
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
    if (!fields.length) return;
    let response;
    try {
      response = await chrome.runtime.sendMessage({ type: "fill", fields });
    } catch (error) {
      return; // extensão recarregada ou service worker indisponível: nada a fazer nesta página
    }
    for (const [id, value] of Object.entries(response?.values || {})) {
      const input = byId.get(id);
      if (input && !input.value) setValue(input, value);
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
