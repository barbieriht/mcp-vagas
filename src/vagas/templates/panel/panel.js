// Painel de configuração do mcp-vagas. Monta o formulário a partir de GET /api/settings e envia só os
// campos alterados para POST /api/settings. A regra (validação, gravação) fica no servidor Python.
"use strict";

const token = new URLSearchParams(location.search).get("t") || "";
let original = {};  // "secao.chave" -> valor carregado

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (name === "text") node.textContent = value;
    else if (name === "class") node.className = value;
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else node.setAttribute(name, value === true ? "" : value);
  }
  for (const child of children) if (child) node.append(child);
  return node;
}

async function api(method, body) {
  const response = await fetch("/api/settings", {
    method,
    headers: { "X-Panel-Token": token, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `O painel respondeu ${response.status}. Abra pelo link do comando de novo.`);
  return data;
}

function sourceNote(field) {
  if (field.source === "env") {
    return el("p", { class: "nota aviso", text: `A variável ${field.env} está definida e vale no lugar deste campo (${field.effective}). O que você salvar aqui só passa a valer sem ela.` });
  }
  if (field.default) {
    const shown = field.choices.find((c) => c.value === field.default);
    return el("p", { class: "nota", text: `Em branco, vale o padrão: ${shown ? shown.label : field.default}.` });
  }
  return null;
}

function input(field, id) {
  if (field.kind === "choice") {
    const select = el("select", { id, name: id });
    select.append(el("option", { value: "", text: field.default ? "Padrão" : "Escolha…" }));
    for (const choice of field.choices) select.append(el("option", { value: choice.value, text: choice.label }));
    select.value = field.value;
    return select;
  }
  const attrs = { id, name: id, value: field.value, autocomplete: "off", spellcheck: "false" };
  if (field.kind === "int") Object.assign(attrs, { type: "number", inputmode: "numeric", min: field.bounds[0], max: field.bounds[1], placeholder: field.default });
  else if (field.key === "login_email") Object.assign(attrs, { type: "email", placeholder: "nome@gmail.com" });
  else if (field.kind === "pdf") Object.assign(attrs, { type: "text", placeholder: "Ex.: C:\\Users\\você\\Downloads\\Curriculo.pdf" });
  else if (field.key === "linkedin_url") Object.assign(attrs, { type: "url", placeholder: "https://www.linkedin.com/in/seu-nome" });
  else Object.assign(attrs, { type: "text", placeholder: field.default || (field.kind === "dir" ? "Caminho da pasta" : "") });
  return el("input", attrs);
}

let controls = [];  // {section, key, read(), before}: o que foi carregado e como ler o valor atual
let counter = 0;

function register(section, key, before, read, node) {
  controls.push({ section, key, before: JSON.stringify(before), read, node });
}

// Selo fora do rótulo (o nome do campo fica limpo), ligado ao controle como descrição.
function badgeFor(control, show, text) {
  if (!show) return null;
  const badge = el("span", { class: "selo", id: `selo-${++counter}`, text });
  control.setAttribute("aria-describedby", badge.id);
  return badge;
}

// Resposta trazida do formato antigo do perfil: ainda não está no arquivo, então conta como alteração ao salvar.
function loadedValue(field) {
  return field.migrated ? null : field.value;
}

function hintFor(field, isNew) {
  if (!field.hint) return "";
  return isNew ? `Ex.: ${field.hint}` : field.hint;
}

function renderConfigField(field, needsSetup) {
  const id = `campo-${++counter}`;
  const control = input(field, id);
  // Pasta ou arquivo com padrão e ainda não confirmado: o padrão já vem preenchido, e salvar o confirma.
  if (needsSetup && !field.value && field.default && (field.kind === "dir" || field.kind === "file")) {
    control.value = field.default;
  }
  register("config", field.key, field.value, () => control.value.trim(), control);
  const box = el("div", { class: "campo", "data-campo": `config.${field.key}` },
    el("div", { class: "cabeca" }, el("label", { for: id, text: field.title }), badgeFor(control, needsSetup, "Falta configurar")),
    field.label.toLowerCase() !== field.title.toLowerCase() ? el("p", { class: "ajuda", text: field.label }) : null,
    control,
    sourceNote(field));
  if (field.suggestions && field.suggestions.length) {
    const list = el("div", { class: "sugestoes", "aria-label": "Sugestões" });
    for (const suggestion of field.suggestions) {
      list.append(el("button", { type: "button", text: suggestion, onclick: () => { control.value = suggestion; control.focus(); } }));
    }
    box.append(list);
  }
  return box;
}

function renderFileField(section, field, isNew) {
  const name = `${section.key}.${field.id}`;
  const notes = (field.notes || []).map((note) => el("p", { class: "nota", text: note }));
  const help = field.help ? el("p", { class: "ajuda", text: field.help }) : null;
  const loadError = field.error ? el("p", { class: "nota aviso", text: field.error }) : null;
  const classes = `campo${field.parent ? " subcampo" : ""}`;
  if (field.kind === "group") {
    return el("div", { class: `${classes} grupo` }, el("h3", { text: field.title }), ...notes);
  }
  if (field.kind === "locked") {
    return el("div", { class: classes, "data-campo": name },
      el("p", { class: "rotulo", text: field.title }), el("p", { class: "nota", text: field.status }));
  }
  const id = `campo-${++counter}`;
  const pending = !field.value && field.kind !== "years";  // anos em branco = calculado
  if (field.kind === "multi") {
    const boxes = field.choices.map((choice) => {
      const box = el("input", { type: "checkbox", value: choice.value, id: `${id}-${choice.value}` });
      box.checked = field.value.includes(choice.value);
      return el("label", { class: "opcao", for: box.id }, box, el("span", { text: choice.label }));
    });
    const group = el("fieldset", { class: classes, "data-campo": name },
      el("legend", { text: field.title }), help, el("div", { class: "opcoes" }, ...boxes), loadError, ...notes);
    register(section.key, field.id, field.value,
      () => [...group.querySelectorAll("input:checked")].map((box) => box.value), group);
    return group;
  }
  if (field.kind === "choice_other") return renderChoiceOther(section, field, name, id, classes, help, notes);
  if (field.kind === "bands") return renderBands(section, field, name, help);
  if (field.kind === "places") return renderPlaces(section, field, name, help, loadError);
  if (field.kind === "languages") return renderLanguages(section, field, name, help, notes);
  if (field.kind === "periods") {
    const years = field.years_computed === null ? null
      : `Total: ${field.years_computed} ${field.years_computed === 1 ? "ano" : "anos"} (${String(field.years_exact).replace(".", ",")} somados, sem contar períodos sobrepostos).`;
    const list = el("ul", { class: "mudancas" }, ...field.value.map((p) => el("li", { text: `${p.title} — ${p.company} (${p.start || "?"} – ${p.end || "atual"})` })));
    return el("div", { class: classes }, el("p", { class: "rotulo", text: field.title }), field.value.length ? list : null,
      years ? el("p", { class: "nota", text: years }) : null, ...notes);
  }
  if (field.kind === "secret") return renderSecret(section, field, name, id);
  let control;
  if (field.kind === "choice") {
    control = el("select", { id });
    for (const choice of field.choices) control.append(el("option", { value: choice.value, text: choice.label }));
    control.value = field.value;
  } else if (field.kind === "yesno") {
    control = el("select", { id });
    for (const [value, label] of [["", "Escolha…"], ["sim", "Sim"], ["não", "Não"]]) control.append(el("option", { value, text: label }));
    control.value = field.value;
  } else {
    const attrs = { id, value: field.value, autocomplete: "off", placeholder: hintFor(field, isNew) };
    if (field.kind === "int") Object.assign(attrs, { type: "number", inputmode: "numeric", min: field.bounds[0], max: field.bounds[1] });
    else attrs.type = "text";
    control = el("input", attrs);
  }
  register(section.key, field.id, loadedValue(field), () => control.value.trim(), control);
  return el("div", { class: classes, "data-campo": name },
    el("div", { class: "cabeca" }, el("label", { for: id, text: field.title }),
      badgeFor(control, pending, field.missing ? "Campo novo" : "Falta preencher")),
    help, control, loadError, ...notes);
}

const OTHER = "__outra__";

// Lista de opções com "Outra…": escolher "Outra…" mostra um campo de texto livre.
function renderChoiceOther(section, field, name, id, classes, help, notes) {
  const select = el("select", { id });
  select.append(el("option", { value: "", text: "Escolha…" }));
  for (const choice of field.choices) select.append(el("option", { value: choice, text: choice }));
  select.append(el("option", { value: OTHER, text: "Outra…" }));
  const custom = el("input", { type: "text", id: `${id}-outra`, autocomplete: "off", "aria-label": `${field.title}: outra resposta`, placeholder: "Escreva a resposta" });
  const known = field.choices.includes(field.value);
  select.value = !field.value ? "" : known ? field.value : OTHER;
  custom.value = known ? "" : field.value;
  const showCustom = () => { custom.hidden = select.value !== OTHER; };
  select.addEventListener("change", () => { showCustom(); if (!custom.hidden) custom.focus(); });
  showCustom();
  register(section.key, field.id, loadedValue(field), () => (select.value === OTHER ? custom.value.trim() : select.value), select);
  return el("div", { class: classes, "data-campo": name },
    el("div", { class: "cabeca" }, el("label", { for: id, text: field.title }), badgeFor(select, !field.value, "Falta preencher")),
    help, select, custom, ...notes);
}

// Enter não envia o formulário: passa para o próximo campo. Só o botão "Salvar tudo" grava.
function nextFieldOnEnter(event) {
  const target = event.target;
  if (event.key !== "Enter" || event.isComposing || !(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;
  event.preventDefault();
  // título de subseção fechada entra na fila: Enter nele abre a subseção, em vez de pulá-la inteira
  const fields = [...document.querySelectorAll("#formulario input, #formulario select, #formulario button, #formulario details:not([open]) > summary")]
    .filter((node) => !node.disabled && !node.hidden && node.offsetParent !== null);
  const next = fields[fields.indexOf(target) + 1];
  if (next) next.focus();
}

// Idiomas: uma linha por idioma, com o nível da lista ou "Outro…" (texto livre).
function renderLanguages(section, field, name, help, notes) {
  const list = el("div", { class: "idiomas" });
  const box = el("fieldset", { class: "campo", "data-campo": name }, el("legend", { text: field.title }), help, list);
  const rows = [];

  function refresh() {
    rows.forEach((row, index) => {
      row.cells.language.dataset.campo = `${name}.${index}.language`;
      row.cells.level.dataset.campo = `${name}.${index}.level`;
    });
  }

  function addRow(data) {
    const n = ++counter;
    const language = el("input", { type: "text", id: `idioma-${n}`, value: data.language || "", autocomplete: "off", placeholder: "Ex.: inglês" });
    const level = el("select", { id: `nivel-${n}` });
    level.append(el("option", { value: "", text: "Escolha…" }));
    for (const option of field.levels) level.append(el("option", { value: option, text: option }));
    level.append(el("option", { value: OTHER, text: "Outro…" }));
    const custom = el("input", { type: "text", "aria-label": "Nível: outro", placeholder: "Ex.: intermediário (B1, certificado)", autocomplete: "off" });
    const known = field.levels.find((option) => plain(option) === plain(data.level || ""));
    level.value = !data.level ? "" : known || OTHER;
    custom.value = known ? "" : data.level || "";
    const showCustom = () => { custom.hidden = level.value !== OTHER; };
    level.addEventListener("change", () => { showCustom(); if (!custom.hidden) custom.focus(); });
    showCustom();
    const row = {
      raw: data.raw || "",
      original: known ? { level: known, text: data.level } : null,
      read: () => {
        const chosen = level.value === OTHER ? custom.value.trim() : level.value;
        // nível da lista sem mudança: o texto lido do arquivo, para a linha original ser mantida
        const levelText = row.original && chosen === row.original.level ? row.original.text : chosen;
        return { language: language.value.trim(), level: levelText, raw: row.raw };
      },
      cells: {
        language: el("div", { class: "celula" }, el("label", { for: language.id, text: "Idioma" }), language),
        level: el("div", { class: "celula" }, el("label", { for: level.id, text: "Nível" }), level, custom),
      },
    };
    const remove = el("button", { type: "button", class: "remover", text: "Remover", "aria-label": "Remover idioma", onclick: () => {
      rows.splice(rows.indexOf(row), 1);
      row.node.remove();
      refresh();
    } });
    row.node = el("div", { class: "idioma" }, row.cells.language, row.cells.level, remove);
    rows.push(row);
    list.append(row.node);
    refresh();
    return { focus: () => language.focus() };
  }

  for (const data of field.value) addRow(data);
  if (!field.value.length && field.hint_rows && field.hint_rows.length) {
    box.append(el("p", { class: "nota", text: `Ex.: ${field.hint_rows.map((r) => `${r.language} (${r.level})`).join(", ")}` }));
  }
  box.append(el("button", { type: "button", class: "adicionar", text: "Adicionar idioma", onclick: () => addRow({}).focus() }), ...notes);
  const read = () => rows.map((row) => row.read());
  register(section.key, field.id, read(), read, box);
  return box;
}

// Documento do cofre: campo de senha que nunca mostra o valor guardado; em branco, não muda nada.
function renderSecret(section, field, name, id) {
  const input = el("input", { type: "password", id, autocomplete: "new-password", spellcheck: "false",
    placeholder: field.stored ? "Guardado. Digite só para trocar" : "Não guardado", disabled: Boolean(section.unavailable) });
  let removing = false;
  const remove = field.stored ? el("button", { type: "button", class: "remover", text: "Remover do cofre", onclick: () => {
    removing = !removing;
    remove.textContent = removing ? "Desfazer remoção" : "Remover do cofre";
    input.disabled = removing;
    box.classList.toggle("a-remover", removing);
  } }) : null;
  const badge = field.stored ? el("span", { class: "selo ok", text: "Guardado no cofre" }) : null;
  // Mostrar o que foi digitado agora, para conferir antes de salvar. O valor já guardado nunca vem do servidor.
  const show = el("button", { type: "button", class: "mostrar", text: "Mostrar", "aria-pressed": "false",
    "aria-label": `Mostrar o que foi digitado em ${field.title}`, onclick: () => {
      const visible = input.type === "password";
      input.type = visible ? "text" : "password";
      show.textContent = visible ? "Ocultar" : "Mostrar";
      show.setAttribute("aria-pressed", String(visible));
      show.setAttribute("aria-label", `${visible ? "Ocultar" : "Mostrar"} o que foi digitado em ${field.title}`);
    } });
  const line = el("div", { class: "segredo" }, input, show);
  const box = el("div", { class: "campo", "data-campo": name },
    el("div", { class: "cabeca" }, el("label", { for: id, text: field.title }), badge), line, remove);
  controls.push({ section: "vault", key: field.id, before: "", node: input,
    read: () => (removing ? { remove: true } : input.value.trim()) });
  return box;
}

// Currículo geral: editor guiado pela descrição das seções (schema) que vem do servidor. O estado é o
// próprio currículo (campos que o painel não mostra voltam como vieram); listas viram blocos recolhíveis.
function renderResume(section, box) {
  const state = structuredClone(section.value);
  box.append(el("p", { class: "nota aviso", text: section.origin === "draft"
    ? "Você está editando o rascunho do currículo geral. Os currículos personalizados só usam a versão aprovada: depois de salvar, aprove o rascunho no fim desta seção."
    : `Não há rascunho: salvar aqui cria um rascunho a partir da versão aprovada${section.approved_at ? ` em ${section.approved_at.slice(0, 10)}` : ""}.` }));

  const summaryOf = (spec, item) => (spec.item.summary || []).map((key) => item[key]).filter(Boolean).join(" · ") || "Novo item";

  function field(spec, holder, path) {
    const name = `resume.${path.join(".")}`;
    const id = `campo-${++counter}`;
    const label = el("label", { for: id, text: spec.label + (spec.required ? " *" : "") });
    let control;
    if (spec.type === "longtext") {
      control = el("textarea", { id, rows: "3" });
      control.value = holder[spec.key] || "";
    } else if (spec.type === "textlist") {
      control = el("textarea", { id, rows: "3", placeholder: "Um por linha" });
      control.value = (holder[spec.key] || []).join("\n");
    } else if (spec.type === "choice") {
      control = el("select", { id });
      control.append(el("option", { value: "", text: "—" }));
      for (const choice of spec.choices) control.append(el("option", { value: choice.value, text: choice.label }));
      control.value = holder[spec.key] || "";
    } else {
      control = el("input", { id, type: spec.type === "int" ? "number" : "text", placeholder: spec.placeholder || "", autocomplete: "off" });
      control.value = holder[spec.key] ?? "";
    }
    control.addEventListener("input", () => {
      const raw = control.value;
      if (spec.type === "textlist") holder[spec.key] = raw.split("\n").map((s) => s.trim()).filter(Boolean);
      else if (spec.type === "int") holder[spec.key] = raw === "" ? "" : Number(raw);
      else holder[spec.key] = raw;
      control.dispatchEvent(new CustomEvent("resume-change", { bubbles: true }));
    });
    return el("div", { class: "campo cv-campo", "data-campo": name }, label, control);
  }

  function list(spec, holder, path) {
    holder[spec.key] ||= [];
    const items = holder[spec.key];
    const name = `resume.${path.join(".")}`;
    const wrap = el("div", { class: "cv-lista" });
    // No topo, o bloco recolhível já tem o título da seção; dentro de um item (ex.: parágrafos), mostra o rótulo.
    const title = path.length > 1 ? el("p", { class: "rotulo", text: spec.label + (spec.required ? " *" : "") }) : null;
    const container = el("div", { class: `campo cv-lista-campo`, "data-campo": name }, title, wrap);
    function draw() {
      wrap.replaceChildren();
      items.forEach((item, index) => {
        const head = el("summary", { text: summaryOf(spec, item) });
        const move = (delta) => {
          const target = index + delta;
          if (target < 0 || target >= items.length) return;
          [items[index], items[target]] = [items[target], items[index]];
          draw();
        };
        const tools = el("div", { class: "cv-acoes" },
          el("button", { type: "button", class: "remover", text: "Subir", disabled: index === 0, onclick: () => move(-1) }),
          el("button", { type: "button", class: "remover", text: "Descer", disabled: index === items.length - 1, onclick: () => move(1) }),
          el("button", { type: "button", class: "remover", text: "Remover", onclick: () => { items.splice(index, 1); draw(); } }));
        const body = el("div", { class: "cv-item-corpo" }, ...spec.item.fields.map((child) => node(child, item, [...path, index, child.key])), tools);
        const details = el("details", { class: "cv-item" }, head, body);
        details.addEventListener("resume-change", () => { head.textContent = summaryOf(spec, item); });
        wrap.append(details);
      });
    }
    draw();
    container.append(el("button", { type: "button", class: "adicionar", text: spec.add || "Adicionar", onclick: () => {
      items.push({});
      draw();
      const last = wrap.lastElementChild;
      last.open = true;
      const first = last.querySelector("input, textarea, select");
      if (first) first.focus();
    } }));
    return container;
  }

  function node(spec, holder, path) {
    if (spec.type === "list") return list(spec, holder, path);
    if (spec.type === "object") {
      holder[spec.key] ||= {};
      return el("div", { class: "cv-objeto" }, ...spec.fields.map((child) => node(child, holder[spec.key], [...path, child.key])));
    }
    return field(spec, holder, path);
  }

  for (const spec of section.schema.fields) {
    const part = el("details", { class: "cv-secao", open: spec.key === "basics" },
      el("summary", { text: spec.label }), node(spec, state, [spec.key]));
    box.append(part);
  }
  // O "antes" vem depois de montar o editor: listas ausentes viram [] e não contam como alteração.
  const before = JSON.stringify({ data: state, hash: section.hash });
  controls.push({ section: "resume", key: "__whole__", before, node: box, read: () => ({ data: state, hash: section.hash }) });
  renderApproval(section, box);
}

// Aprovação do currículo geral: o que muda em relação à versão aprovada, o que não aparece nas fontes e
// o botão Aprovar, com uma confirmação que repete os avisos. Aprovar não faz parte do "Salvar tudo".
function renderApproval(section, box) {
  const approval = section.approval;
  if (!approval) return;
  // Rótulos por seção: "title" é Cargo nas experiências e Título nas publicações.
  const labels = {};
  const fieldLabels = {};
  for (const spec of section.schema.fields) {
    labels[spec.key] = spec.label;
    fieldLabels[spec.key] = Object.fromEntries((spec.item ? spec.item.fields : spec.fields || [spec]).map((f) => [f.key, f.label]));
  }
  const kinds = { added: "novo", removed: "removido", changed: "alterado" };
  const area = el("div", { class: "aprovacao" }, el("h3", { text: "Aprovar o rascunho" }));
  if (approval.changes.length) {
    const list = el("ul", { class: "mudancas" });
    for (const change of approval.changes) {
      const fields = (change.fields || []).map((f) => (fieldLabels[change.section] || {})[f] || f).join(", ");
      list.append(el("li", { text: `${labels[change.section] || change.section}: ${change.label ? change.label + " — " : ""}${kinds[change.kind]}${fields ? ` (${fields})` : ""}` }));
    }
    area.append(el("p", { class: "ajuda", text: "O que muda em relação à versão aprovada:" }), list);
  }
  if (approval.review.length) {
    const list = el("ul", { class: "mudancas" });
    for (const item of approval.review.slice(0, 30)) list.append(el("li", { text: `${item.where}: ${item.value} (${item.reason})` }));
    const warning = el("p", { class: "nota aviso", text: `Não encontrado no PDF nem no LinkedIn (${approval.review.length}). Confira se é verdade antes de aprovar: nada inventado pode chegar ao recrutador.` });
    area.append(warning, approval.review.length > 5
      ? el("details", { class: "cv-secao" }, el("summary", { text: `Ver os ${approval.review.length} itens` }), list)
      : list);
  }
  const message = el("p", { class: "nota", role: "status" });
  const button = el("button", { type: "button", class: "aprovar", text: "Aprovar o rascunho", disabled: !approval.can_approve });
  if (!approval.can_approve) message.textContent = approval.reason;
  const confirm = el("div", { class: "confirmacao", hidden: true },
    el("p", { text: `Aprovar torna este rascunho a versão usada nos currículos personalizados e recalcula a aderência das vagas abertas.${approval.review.length ? ` Há ${approval.review.length} item(ns) que não aparecem nas fontes.` : ""}` }));
  const yes = el("button", { type: "button", class: "aprovar", text: "Confirmar aprovação" });
  const no = el("button", { type: "button", class: "remover", text: "Cancelar", onclick: () => { confirm.hidden = true; button.hidden = false; } });
  confirm.append(el("div", { class: "cv-acoes" }, no, yes));
  button.addEventListener("click", () => {
    if (changes().resume) {  // só as alterações do currículo importam para aprovar
      message.textContent = "Há alterações não salvas no currículo: clique em \"Salvar tudo\" antes de aprovar.";
      return;
    }
    button.hidden = true;
    confirm.hidden = false;
    yes.focus();
  });
  yes.addEventListener("click", async () => {
    yes.disabled = true;
    try {
      const response = await fetch("/api/resume/approve", { method: "POST", headers: { "X-Panel-Token": token, "Content-Type": "application/json" }, body: JSON.stringify({ hash: section.hash }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `O painel respondeu ${response.status}.`);
      render(result.settings);
      status(`Currículo geral aprovado (versão ${result.version_id}). Aderência recalculada em ${result.rescored} vaga(s).`, "ok");
    } catch (error) {
      confirm.hidden = true;
      button.hidden = false;
      message.textContent = error.message;
      yes.disabled = false;
    }
  });
  area.append(button, confirm, message);
  box.append(area);
}

const plain = (text) => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
const PLACES_EVENT = "locais-aceitos";  // os locais dos critérios mudaram: as faixas atualizam as cidades

// Locais aceitos dos critérios: um grupo por estado, com as cidades separadas por vírgula.
function renderPlaces(section, field, name, help, loadError) {
  const list = el("div", { class: "locais" });
  const box = el("fieldset", { class: "campo", "data-campo": name }, el("legend", { text: field.title }), help, list);
  const rows = [];
  const read = () => rows.map((row) => ({
    state: row.state.value,
    cities: row.cities.value.split(",").map((city) => city.trim()).filter(Boolean),
  }));
  const announce = () => document.dispatchEvent(new CustomEvent(PLACES_EVENT, { detail: read() }));

  function addRow(data) {
    const n = ++counter;
    const state = el("select", { id: `estado-${n}` });
    state.append(el("option", { value: "", text: "Qualquer estado" }));
    for (const choice of field.states) state.append(el("option", { value: choice.value, text: choice.label }));
    state.value = data.state || "";
    const cities = el("input", { type: "text", id: `cidades-${n}`, value: (data.cities || []).join(", "), autocomplete: "off",
      placeholder: "Ex.: São Carlos, São Paulo, Barueri (vazio: você julga cada cidade do estado)" });
    const row = { state, cities };
    const remove = el("button", { type: "button", class: "remover", text: "Remover", "aria-label": "Remover estado", onclick: () => {
      rows.splice(rows.indexOf(row), 1);
      row.node.remove();
      announce();
    } });
    row.node = el("div", { class: "local" },
      el("div", { class: "celula" }, el("label", { for: state.id, text: "Estado" }), state),
      el("div", { class: "celula" }, el("label", { for: cities.id, text: "Cidades" }), cities),
      remove);
    state.addEventListener("change", announce);
    cities.addEventListener("input", announce);
    rows.push(row);
    list.append(row.node);
    return row;
  }

  for (const data of field.value) addRow(data);
  box.append(el("button", { type: "button", class: "adicionar", text: "Adicionar estado", onclick: () => {
    addRow({}).state.focus();
    announce();
  } }));
  if (loadError) box.append(loadError);
  register(section.key, field.id, loadedValue(field), read, box);
  return box;
}

// Faixas da política salarial: cada faixa é um conjunto de vagas com um valor. Tipo de vaga (remoto,
// híbrido, presencial); remoto nacional (R$) ou internacional (US$/€); para híbrido e presencial, as cidades
// dos locais aceitos e "demais cidades" de cada estado. O mesmo local na mesma modalidade só numa faixa.
function renderBands(section, field, name, help) {
  const list = el("div", { class: "faixas" });
  const box = el("fieldset", { class: "campo", "data-campo": name }, el("legend", { text: field.title }), help, list);
  const rows = [];
  let places = field.places || [];
  const allModes = field.modes.map((mode) => mode.value);
  const modeTitle = Object.fromEntries(field.modes.map((mode) => [mode.value, mode.label]));
  const plural = { remoto: "remotas", hibrido: "híbridas", presencial: "presenciais" };
  const cityKey = (state, city) => `${state}|${plain(city)}`;

  function selection(row) {
    const modes = allModes.filter((mode) => row.modes[mode].checked);
    const remote = modes.includes("remoto");
    const local = modes.some((mode) => mode !== "remoto");
    const scope = remote ? (row.scope.find((radio) => radio.checked) || {}).value || "" : "";
    const currency = scope === "internacional" ? row.currency.value : "BRL";
    const states = [...new Set([...row.loadedStates, ...places.map((g) => g.state),
      ...[...row.chosen.values()].map((v) => v.state), ...row.rest])];
    const chosen = local ? states.map((state) => ({
      state,
      cities: [...row.chosen.values()].filter((v) => v.state === state).map((v) => v.city),
      rest: row.rest.has(state),
    })).filter((g) => g.cities.length || g.rest) : [];
    return { modes, scope, currency, places: chosen };
  }

  const where = (chosen) => chosen.places.flatMap((g) => [...g.cities, ...(g.rest ? [`demais cidades de ${g.state}`] : [])]);

  function label(row) {
    const chosen = selection(row);
    const parts = [];
    if (chosen.modes.includes("remoto")) parts.push(chosen.scope ? `Remoto ${chosen.scope}${chosen.scope === "internacional" ? ` (${chosen.currency})` : ""}` : "Remoto");
    const local = chosen.modes.filter((mode) => mode !== "remoto").map((mode) => modeTitle[mode]);
    if (local.length) {
      const text = [local[0], ...local.slice(1).map((t) => t.toLowerCase())].join("/");
      const at = where(chosen);
      parts.push(at.length ? `${text} em ${at.join(", ")}` : text);
    }
    if (parts.length === 2) parts[1] = parts[1][0].toLowerCase() + parts[1].slice(1);
    return parts.join(" e ") || "nova faixa";
  }

  function applies(row) {
    const chosen = selection(row);
    const parts = [];
    if (chosen.modes.includes("remoto")) {
      const scope = { nacional: " nacionais", internacional: " internacionais" }[chosen.scope] || "";
      parts.push(`vagas remotas${scope}${chosen.scope ? `, pagas em ${chosen.currency}` : ""}`);
    }
    const local = chosen.modes.filter((mode) => mode !== "remoto").map((mode) => plural[mode]);
    if (local.length) {
      const at = where(chosen);
      parts.push(`vagas ${local.join(" e ")}${at.length ? ` em ${at.join(", ")}` : " (marque os locais)"}`);
    }
    return parts.length ? `Vale para ${parts.join(" e para ")}.` : "Marque ao menos um tipo de vaga.";
  }

  // O que cada faixa cobre: o mesmo local na mesma modalidade em duas faixas é avisado aqui e recusado ao salvar.
  function coverage(row) {
    const chosen = selection(row);
    const keys = [];
    if (chosen.scope) keys.push([`remoto|${chosen.scope}|${chosen.currency}`, `Remoto ${chosen.scope}`]);
    for (const mode of chosen.modes.filter((m) => m !== "remoto")) {
      for (const group of chosen.places) {
        for (const city of group.cities) keys.push([`${mode}|${cityKey(group.state, city)}`, `${city}${group.state ? `/${group.state}` : ""} (${modeTitle[mode].toLowerCase()})`]);
        if (group.rest) keys.push([`${mode}|${group.state}|*`, `Demais cidades de ${group.state} (${modeTitle[mode].toLowerCase()})`]);
      }
    }
    return keys;
  }

  function refresh() {
    const seen = new Map();
    rows.forEach((row, index) => {
      row.title.textContent = `Faixa ${index + 1}: ${label(row)}`;
      for (const [key, node] of Object.entries(row.cells)) node.dataset.campo = `${name}.${index}.${key}`;
      const chosen = selection(row);
      const remote = chosen.modes.includes("remoto");
      row.cells.scope.hidden = !remote;
      row.cells.currency.hidden = !(remote && chosen.scope === "internacional");
      row.cells.places.hidden = !chosen.modes.some((mode) => mode !== "remoto");
      row.applies.textContent = applies(row);
      const clashes = [];
      for (const [key, text] of coverage(row)) {
        if (seen.has(key)) clashes.push(`${text} já está na faixa ${seen.get(key) + 1}`);
        else seen.set(key, index);
      }
      row.conflict.textContent = clashes.length ? `${clashes.join("; ")}: cada local, numa modalidade, tem um valor só.` : "";
      row.conflict.hidden = !clashes.length;
    });
  }

  function checkbox(text, checked, onchange) {
    const input = el("input", { type: "checkbox", id: `faixa-opcao-${++counter}` });
    input.checked = checked;
    input.addEventListener("change", () => { onchange(input.checked); refresh(); });
    return el("label", { class: "opcao", for: input.id }, input, el("span", { text }));
  }

  // Cidades por estado, dos locais aceitos; as marcadas que saíram dos locais aceitos ficam à vista até serem desmarcadas.
  function drawPlaces(row) {
    const shown = new Set();
    const groups = [];
    const toggleCity = (state, city) => (on) => (on ? row.chosen.set(cityKey(state, city), { state, city }) : row.chosen.delete(cityKey(state, city)));
    const toggleRest = (state) => (on) => (on ? row.rest.add(state) : row.rest.delete(state));
    for (const group of places) {
      const options = group.cities.filter((city) => !shown.has(cityKey(group.state, city)) && shown.add(cityKey(group.state, city)))
        .map((city) => checkbox(city, row.chosen.has(cityKey(group.state, city)), toggleCity(group.state, city)));
      if (group.state && !shown.has(`${group.state}|*`)) {
        shown.add(`${group.state}|*`);
        options.push(checkbox(`Demais cidades de ${group.state}`, row.rest.has(group.state), toggleRest(group.state)));
      }
      if (options.length) groups.push(el("div", { class: "cidades-estado" },
        el("p", { class: "cidades-titulo", text: group.state || "Qualquer estado" }), el("div", { class: "opcoes" }, ...options)));
    }
    const outside = [
      ...[...row.chosen.entries()].filter(([key]) => !shown.has(key)).map(([, v]) =>
        checkbox(v.state ? `${v.city} (${v.state})` : v.city, true, toggleCity(v.state, v.city))),
      ...[...row.rest].filter((state) => !shown.has(`${state}|*`)).map((state) =>
        checkbox(`Demais cidades de ${state}`, true, toggleRest(state))),
    ];
    if (outside.length) groups.push(el("div", { class: "cidades-estado" },
      el("p", { class: "cidades-titulo", text: "Fora dos locais aceitos" }), el("div", { class: "opcoes" }, ...outside)));
    row.cells.places.replaceChildren(
      el("p", { class: "rotulo-celula", text: "Cidades" }),
      ...(groups.length ? groups : [el("p", { class: "nota", text: "Cadastre os locais aceitos nos critérios de triagem para escolher as cidades." })]));
  }

  document.addEventListener(PLACES_EVENT, (event) => {
    places = event.detail;
    rows.forEach(drawPlaces);
    refresh();
  });

  function addRow(data) {
    const n = ++counter;
    const make = (key, text, control) => {
      control.id = `faixa-${n}-${key}`;
      return el("div", { class: `celula celula-${key}` }, el("label", { for: control.id, text }), control);
    };
    const row = {
      currency: el("select", {}),
      clt: el("input", { type: "checkbox" }),
      min: el("input", { type: "text", inputmode: "decimal", value: data.min || "", placeholder: data.hint_min ? `Ex.: ${data.hint_min}` : "Ex.: 8000", autocomplete: "off" }),
      max: el("input", { type: "text", inputmode: "decimal", value: data.max || "", placeholder: data.hint_max ? `Ex.: ${data.hint_max}` : "Opcional", autocomplete: "off" }),
      chosen: new Map(),
      rest: new Set(),
      loadedStates: (data.places || []).map((g) => g.state),
      modes: {},
      title: el("p", { class: "faixa-titulo" }),
      applies: el("p", { class: "nota" }),
      conflict: el("p", { class: "nota aviso", hidden: true }),
    };
    for (const group of data.places || []) {
      for (const city of group.cities) row.chosen.set(cityKey(group.state, city), { state: group.state, city });
      if (group.rest) row.rest.add(group.state);
    }
    for (const currency of field.currencies) row.currency.append(el("option", { value: currency, text: currency }));
    row.currency.value = field.currencies.includes(data.currency) ? data.currency : field.currencies[0];
    row.clt.checked = Boolean(data.clt);
    const modeBoxes = field.modes.map((mode) => {
      const input = el("input", { type: "checkbox", id: `faixa-${n}-modo-${mode.value}` });
      input.checked = (data.modes || []).includes(mode.value);
      input.addEventListener("change", refresh);
      row.modes[mode.value] = input;
      return el("label", { class: "opcao", for: input.id }, input, el("span", { text: mode.label }));
    });
    const scopes = [["nacional", "Nacionais (em R$)"], ["internacional", "Internacionais (em US$ ou €)"]];
    row.scope = scopes.map(([value]) => {
      const radio = el("input", { type: "radio", name: `faixa-${n}-escopo`, id: `faixa-${n}-escopo-${value}`, value });
      radio.checked = value === data.scope;
      radio.addEventListener("change", refresh);
      return radio;
    });
    const scopeLabels = row.scope.map((radio, i) => el("label", { class: "opcao", for: radio.id }, radio, el("span", { text: scopes[i][1] })));
    row.cells = {
      modes: el("div", { class: "celula celula-modes", role: "group", "aria-label": "Tipo de vaga" },
        el("p", { class: "rotulo-celula", text: "Tipo de vaga" }), el("div", { class: "opcoes" }, ...modeBoxes)),
      scope: el("div", { class: "celula celula-scope", role: "radiogroup", "aria-label": "Vagas remotas" },
        el("p", { class: "rotulo-celula", text: "Vagas remotas" }), el("div", { class: "opcoes" }, ...scopeLabels)),
      currency: make("currency", "Moeda das vagas internacionais", row.currency),
      places: el("div", { class: "celula celula-places", role: "group", "aria-label": "Cidades" }),
      min: make("min", "Mínimo mensal", row.min),
      max: make("max", "Máximo mensal", row.max),
    };
    row.clt.id = `faixa-${n}-clt`;
    const clt = el("label", { class: "opcao celula-clt", for: row.clt.id }, row.clt, el("span", { text: "CLT (multiplicada em vagas PJ)" }));
    const remove = el("button", { type: "button", class: "remover", text: "Remover faixa", onclick: () => {
      rows.splice(rows.indexOf(row), 1);
      row.node.remove();
      refresh();
    } });
    row.currency.addEventListener("change", refresh);
    row.node = el("div", { class: "faixa" },
      el("div", { class: "faixa-topo" }, row.title, remove),
      el("div", { class: "faixa-grade" }, row.cells.modes, row.cells.scope, row.cells.currency, row.cells.places,
        row.cells.min, row.cells.max, clt),
      row.applies, row.conflict);
    rows.push(row);
    list.append(row.node);
    drawPlaces(row);
    refresh();
    return row;
  }

  for (const data of field.value) addRow(data);
  const add = el("button", { type: "button", class: "adicionar", text: "Adicionar faixa", onclick: () => addRow({}).modes.remoto.focus() });
  box.append(add, ...(field.notes || []).map((note) => el("p", { class: "nota aviso", text: note })));
  const read = () => rows.map((row) => ({ ...selection(row), clt: row.clt.checked, min: row.min.value.trim(), max: row.max.value.trim() }));
  register(section.key, field.id, field.migrated ? null : read(), read, box);
  return box;
}

function sectionPending(key, section) {
  if (section.error) return true;
  if (key === "config") return (section.needs_setup || []).length > 0;
  return (section.pending || []).length > 0;
}

// Subseção com nome (## do arquivo) dobrável: começa aberta se tem campo a preencher; depois de salvar,
// fica como o usuário deixou.
const folds = new Map();  // "secao/subseção" -> aberta?

function renderFold(section, group, fields) {
  const key = `${section.key}/${group.name}`;
  const pending = group.fields.filter((field) => (section.pending || []).includes(field.id) || (field.missing && !field.value)).length;
  const summary = el("summary", {}, el("h3", { class: "grupo-titulo", text: group.name }),
    pending ? el("span", { class: "selo", text: `${pending} a preencher` }) : null);
  const fold = el("details", { class: "grupo-dobravel", open: folds.has(key) ? folds.get(key) : pending > 0 }, summary, ...fields);
  fold.addEventListener("toggle", () => folds.set(key, fold.open));
  return fold;
}

function render(data) {
  const container = document.getElementById("secoes");
  const index = document.getElementById("indice");
  container.replaceChildren();
  index.replaceChildren();
  controls = [];
  for (const [key, section] of Object.entries(data.sections)) {
    section.key = key;
    index.append(el("li", {}, el("a", { href: `#secao-${key}`, class: sectionPending(key, section) ? "pendente" : null, text: section.title })));
    const box = el("section", { class: "secao", id: `secao-${key}`, "aria-labelledby": `titulo-${key}` },
      el("h2", { id: `titulo-${key}`, text: section.title }),
      section.file ? el("p", { class: "arquivo", text: `Arquivo: ${section.file}` }) : null);
    if (section.error) {
      box.append(el("p", { class: "erro", text: section.error }));
    } else if (key === "resume") {
      renderResume(section, box);
    } else if (key === "config") {
      for (const field of section.fields) box.append(renderConfigField(field, (section.needs_setup || []).includes(field.key)));
    } else {
      if (section.help) box.append(el("p", { class: "ajuda", text: section.help }));
      if (section.unavailable) box.append(el("p", { class: "nota aviso", text: section.unavailable }));
      if (section.new) box.append(el("p", { class: "nota aviso", text: "Este arquivo ainda não existe: ele é criado quando você salvar. Os textos em cinza são só exemplos." }));
      for (const group of section.groups) {
        const fields = group.fields.map((field) => renderFileField(section, field, section.new));
        box.append(...(group.name ? [renderFold(section, group, fields)] : fields));
      }
    }
    container.append(box);
  }
}

function changes() {
  const form = {};
  for (const control of controls) {
    const value = control.read();
    if (control.section === "vault") {  // {set: {doc: valor}, remove: [doc]}
      if (value && value.remove) ((form.vault ||= {}).remove ||= []).push(control.key);
      else if (value) ((form.vault ||= {}).set ||= {})[control.key] = value;
      continue;
    }
    if (JSON.stringify(value) === control.before) continue;
    if (control.key === "__whole__") form[control.section] = value;  // seção enviada inteira (currículo)
    else (form[control.section] ||= {})[control.key] = value;
  }
  return form;
}

function showErrors(errors) {
  document.querySelectorAll(".erro.do-campo").forEach((node) => node.remove());
  document.querySelectorAll(".com-erro").forEach((node) => node.classList.remove("com-erro"));
  let first = null;
  const loose = [];
  for (const [name, message] of Object.entries(errors)) {
    const box = [...document.querySelectorAll("[data-campo]")].find((node) => node.dataset.campo === name);
    if (!box) { loose.push(message); continue; }
    box.classList.add("com-erro");
    for (let open = box.closest("details"); open; open = open.parentElement.closest("details")) open.open = true;
    const note = el("p", { class: "erro do-campo", id: `erro-${++counter}`, text: message });
    box.append(note);
    const control = box.querySelector("input, select, textarea");
    if (control) {
      control.setAttribute("aria-describedby", note.id);
      first ||= control;
    }
  }
  if (first) first.focus();
  return loose;
}

function status(text, kind) {
  const node = document.getElementById("status");
  node.textContent = text;
  node.className = kind || "";
}

async function submit(event) {
  event.preventDefault();
  const form = changes();
  if (!Object.keys(form).length) return status("Nada mudou desde a última gravação.");
  const button = document.getElementById("salvar");
  button.disabled = true;
  status("Salvando…");
  try {
    const result = await api("POST", form);
    const loose = showErrors(result.errors || {});
    if (!result.saved) {
      const count = Object.keys(result.errors).length;
      status(`Nada foi salvo: corrija ${count === 1 ? "o campo marcado" : `os ${count} campos marcados`}.${loose.length ? " " + loose.join(" ") : ""}`, "falha");
      return;
    }
    render(result.settings);
    const gone = result.rechecked?.discarded || [];
    const recheck = gone.length === 1 ? `1 vaga aberta foi descartada pelos critérios novos: ${gone[0].role} — ${gone[0].company}.`
      : gone.length ? `${gone.length} vagas abertas foram descartadas pelos critérios novos (veja em Vagas).` : "";
    const extra = [...(result.warnings || []), recheck].filter(Boolean).join(" ");
    status(`Tudo salvo.${extra ? " " + extra : ""}`, "ok");
  } catch (error) {
    status(error.message, "falha");
  } finally {
    button.disabled = false;
  }
}

async function start() {
  const form = document.getElementById("formulario");
  form.addEventListener("submit", submit);
  form.addEventListener("keydown", nextFieldOnEnter);
  try {
    render(await api("GET"));
  } catch (error) {
    document.getElementById("secoes").replaceChildren(el("p", { class: "erro", text: error.message }));
  }
}

start();
