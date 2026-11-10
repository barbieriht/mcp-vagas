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
  const pending = !field.value;
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
  if (field.kind === "languages") return renderLanguages(section, field, name, help, notes);
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
  register(section.key, field.id, field.value, () => control.value.trim(), control);
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
  register(section.key, field.id, field.value, () => (select.value === OTHER ? custom.value.trim() : select.value), select);
  return el("div", { class: classes, "data-campo": name },
    el("div", { class: "cabeca" }, el("label", { for: id, text: field.title }), badgeFor(select, !field.value, "Falta preencher")),
    help, select, custom, ...notes);
}

// Enter não envia o formulário: passa para o próximo campo. Só o botão "Salvar tudo" grava.
function nextFieldOnEnter(event) {
  const target = event.target;
  if (event.key !== "Enter" || event.isComposing || !(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;
  event.preventDefault();
  const fields = [...document.querySelectorAll("#formulario input, #formulario select, #formulario button")]
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
  const box = el("div", { class: "campo", "data-campo": name },
    el("div", { class: "cabeca" }, el("label", { for: id, text: field.title }), badge), input, remove);
  controls.push({ section: "vault", key: field.id, before: "", node: input,
    read: () => (removing ? { remove: true } : input.value.trim()) });
  return box;
}

const plain = (text) => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();

// Tabela de faixas da política salarial: uma linha por faixa, com "usar a faixa de" outra linha.
function renderBands(section, field, name, help) {
  const list = el("div", { class: "faixas" });
  const box = el("fieldset", { class: "campo", "data-campo": name }, el("legend", { text: field.title }), help, list);
  const rows = [];

  function aliasTarget(row, alias) {
    if (!alias) return "";
    const target = plain(alias);
    const hit = rows.find((other) => other !== row && (plain(other.name.value).startsWith(target) || target.startsWith(plain(other.name.value))));
    return hit ? hit.name.value : alias;
  }

  function refresh() {
    rows.forEach((row, index) => {
      row.node.querySelector(".faixa-titulo").textContent = `Faixa ${index + 1}`;
      for (const [key, node] of Object.entries(row.cells)) node.dataset.campo = `${name}.${index}.${key}`;
      const current = row.alias.value;
      row.alias.replaceChildren(el("option", { value: "", text: "Não: valores próprios" }));
      for (const other of rows) {
        if (other !== row && other.name.value.trim()) row.alias.append(el("option", { value: other.name.value.trim(), text: other.name.value.trim() }));
      }
      row.alias.value = [...row.alias.options].some((o) => o.value === current) ? current : "";
      const usesOther = Boolean(row.alias.value);
      row.min.disabled = row.max.disabled = usesOther;
    });
  }

  function addRow(data) {
    const n = ++counter;
    const make = (key, label, control) => {
      control.id = `faixa-${n}-${key}`;
      const cell = el("div", { class: `celula celula-${key}` }, el("label", { for: control.id, text: label }), control);
      return cell;
    };
    const row = {
      name: el("input", { type: "text", value: data.name || "", placeholder: "Ex.: Remoto nacional", autocomplete: "off" }),
      currency: el("select", {}),
      clt: el("input", { type: "checkbox" }),
      min: el("input", { type: "text", inputmode: "decimal", value: data.min || "", placeholder: data.hint_min ? `Ex.: ${data.hint_min}` : "Ex.: 8000", autocomplete: "off" }),
      max: el("input", { type: "text", inputmode: "decimal", value: data.max || "", placeholder: data.hint_max ? `Ex.: ${data.hint_max}` : "Opcional", autocomplete: "off" }),
      alias: el("select", {}),
    };
    for (const currency of field.currencies) row.currency.append(el("option", { value: currency, text: currency }));
    row.currency.value = data.currency || field.currencies[0];
    row.clt.checked = Boolean(data.clt);
    row.cells = {
      name: make("name", "Nome", row.name),
      currency: make("currency", "Moeda", row.currency),
      min: make("min", "Mínimo mensal", row.min),
      max: make("max", "Máximo mensal", row.max),
      alias: make("alias", "Usar os valores da faixa", row.alias),
    };
    row.clt.id = `faixa-${n}-clt`;
    const clt = el("label", { class: "opcao celula-clt", for: row.clt.id }, row.clt, el("span", { text: "CLT (multiplicada em vagas PJ)" }));
    const remove = el("button", { type: "button", class: "remover", text: "Remover faixa", onclick: () => {
      rows.splice(rows.indexOf(row), 1);
      row.node.remove();
      refresh();
    } });
    row.node = el("div", { class: "faixa" },
      el("div", { class: "faixa-topo" }, el("p", { class: "faixa-titulo" }), remove),
      el("div", { class: "faixa-grade" }, row.cells.name, row.cells.currency, row.cells.min, row.cells.max, row.cells.alias, clt),
      data.applies ? el("p", { class: "nota", text: data.applies }) : null);
    row.name.addEventListener("input", refresh);
    row.alias.addEventListener("change", refresh);
    rows.push(row);
    list.append(row.node);
    refresh();
    row.alias.value = aliasTarget(row, data.alias || "");
    refresh();
    return row;
  }

  for (const data of field.value) addRow(data);
  const add = el("button", { type: "button", class: "adicionar", text: "Adicionar faixa", onclick: () => addRow({}).name.focus() });
  box.append(add);
  const read = () => rows.map((row) => ({
    name: row.name.value.trim(), currency: row.currency.value, clt: row.clt.checked,
    min: row.alias.value ? "" : row.min.value.trim(), max: row.alias.value ? "" : row.max.value.trim(), alias: row.alias.value,
  }));
  register(section.key, field.id, read(), read, box);
  return box;
}

function sectionPending(key, section) {
  if (section.error) return true;
  if (key === "config") return (section.needs_setup || []).length > 0;
  return (section.pending || []).length > 0;
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
    } else if (key === "config") {
      for (const field of section.fields) box.append(renderConfigField(field, (section.needs_setup || []).includes(field.key)));
    } else {
      if (section.help) box.append(el("p", { class: "ajuda", text: section.help }));
      if (section.unavailable) box.append(el("p", { class: "nota aviso", text: section.unavailable }));
      if (section.new) box.append(el("p", { class: "nota aviso", text: "Este arquivo ainda não existe: ele é criado quando você salvar. Os textos em cinza são só exemplos." }));
      for (const group of section.groups) {
        if (group.name) box.append(el("h3", { class: "grupo-titulo", text: group.name }));
        for (const field of group.fields) box.append(renderFileField(section, field, section.new));
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
    (form[control.section] ||= {})[control.key] = value;
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
    const note = el("p", { class: "erro do-campo", id: `erro-${++counter}`, text: message });
    box.append(note);
    const control = box.querySelector("input, select");
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
    const extra = (result.warnings || []).join(" ");
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
