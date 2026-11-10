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
  let control;
  if (field.kind === "yesno") {
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
    el("div", { class: "cabeca" }, el("label", { for: id, text: field.title }), badgeFor(control, pending, "Falta preencher")),
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
