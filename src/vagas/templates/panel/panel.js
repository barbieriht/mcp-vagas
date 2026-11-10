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

function renderField(sectionKey, field, needsSetup) {
  const id = `${sectionKey}.${field.key}`;
  original[id] = field.value;
  const control = input(field, id);
  // Pasta ou arquivo com padrão e ainda não confirmado: o padrão já vem preenchido, e salvar o confirma.
  if (needsSetup && !field.value && field.default && (field.kind === "dir" || field.kind === "file")) {
    control.value = field.default;
  }
  const box = el("div", { class: "campo", "data-campo": id },
    el("label", { for: id, text: field.title }, needsSetup ? el("span", { class: "selo", text: "Falta configurar" }) : null),
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

function render(data) {
  const container = document.getElementById("secoes");
  const index = document.getElementById("indice");
  container.replaceChildren();
  index.replaceChildren();
  original = {};
  for (const [key, section] of Object.entries(data.sections)) {
    const pending = section.needs_setup && section.needs_setup.length > 0;
    index.append(el("li", {}, el("a", { href: `#secao-${key}`, class: pending ? "pendente" : null, text: section.title })));
    const box = el("section", { class: "secao", id: `secao-${key}`, "aria-labelledby": `titulo-${key}` },
      el("h2", { id: `titulo-${key}`, text: section.title }),
      el("p", { class: "arquivo", text: `Arquivo: ${section.file}` }));
    for (const field of section.fields) box.append(renderField(key, field, (section.needs_setup || []).includes(field.key)));
    container.append(box);
  }
}

function changes() {
  const form = {};
  for (const [id, before] of Object.entries(original)) {
    const value = document.getElementById(id).value.trim();
    if (value === before) continue;
    const [section, key] = id.split(".");
    (form[section] ||= {})[key] = value;
  }
  return form;
}

function showErrors(errors) {
  document.querySelectorAll(".erro").forEach((node) => node.remove());
  document.querySelectorAll(".com-erro").forEach((node) => node.classList.remove("com-erro"));
  let first = null;
  for (const [id, message] of Object.entries(errors)) {
    const box = document.querySelector(`[data-campo="${CSS.escape(id)}"]`);
    if (!box) continue;
    box.classList.add("com-erro");
    const note = el("p", { class: "erro", id: `${id}-erro`, text: message });
    box.append(note);
    document.getElementById(id).setAttribute("aria-describedby", note.id);
    first ||= document.getElementById(id);
  }
  if (first) first.focus();
  return Object.keys(errors).filter((id) => !document.querySelector(`[data-campo="${CSS.escape(id)}"]`));
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
      status(`Nada foi salvo: corrija ${count === 1 ? "o campo marcado" : `os ${count} campos marcados`}.${loose.length ? " " + loose.map((k) => result.errors[k]).join(" ") : ""}`, "falha");
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
  document.getElementById("formulario").addEventListener("submit", submit);
  try {
    render(await api("GET"));
  } catch (error) {
    document.getElementById("secoes").replaceChildren(el("p", { class: "erro", text: error.message }));
  }
}

start();
