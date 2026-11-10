// Aba "Vagas": lista das vagas registradas, com filtros e o detalhe de cada uma. Só leitura (as ações
// sobre as vagas vêm depois). Usa el() e token do panel.js.
"use strict";

const jobs = { filters: { order: "", page: "1" }, loaded: false, detail: null, selected: new Set(), statuses: [] };

async function jobsAction(body) {
  const response = await fetch("/api/jobs/action", { method: "POST", headers: { "X-Panel-Token": token, "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `O painel respondeu ${response.status}.`);
  return data;
}

function jobsMessage(text, kind) {
  const node = document.getElementById("vagas-status");
  if (node) { node.textContent = text; node.className = kind || ""; }
}

async function jobsApi(path) {
  const response = await fetch(path, { headers: { "X-Panel-Token": token } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `O painel respondeu ${response.status}.`);
  return data;
}

function money(value) {
  return value == null ? "—" : `R$ ${Number(value).toLocaleString("pt-BR")}`;
}

function jobLink(item) {
  const text = `${item.role} — ${item.company}`;
  return item.url ? el("a", { href: item.url, target: "_blank", rel: "noopener noreferrer", text }) : el("span", { text });
}

function filterBar(data) {
  const f = jobs.filters;
  const control = (label, node) => el("label", { class: "filtro" }, el("span", { text: label }), node);
  const select = (key, options, empty) => {
    const node = el("select", {}, el("option", { value: "", text: empty }), ...options.map((o) => el("option", { value: o.value, text: o.label })));
    node.value = f[key] || "";
    node.addEventListener("change", () => setFilter(key, node.value));
    return node;
  };
  const text = el("input", { type: "search", value: f.text || "", placeholder: "Cargo, empresa ou local" });
  let timer;
  text.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => setFilter("text", text.value), 300); });
  const since = el("input", { type: "date", value: f.since || "" });
  since.addEventListener("change", () => setFilter("since", since.value));
  const score = el("input", { type: "number", min: "0", max: "100", inputmode: "numeric", value: f.min_score || "", placeholder: "0–100" });
  score.addEventListener("change", () => setFilter("min_score", score.value));
  const pending = el("input", { type: "checkbox" });
  pending.checked = Boolean(f.only_pending);
  pending.addEventListener("change", () => setFilter("only_pending", pending.checked ? "1" : ""));
  const order = select("order", [{ value: "recentes", label: "Mais recentes" }, { value: "aderencia", label: "Maior aderência" }], "Padrão");
  return el("div", { class: "filtros" },
    control("Busca", text), control("Status", select("status", data.statuses, "Todos")),
    control("Site", select("source", data.sources, "Todos")), control("Desde", since),
    control("Aderência mínima", score), control("Ordem", order),
    el("label", { class: "filtro opcao" }, pending, el("span", { text: "Só com pendência" })));
}

function counts(data) {
  const chips = data.statuses.filter((s) => data.counts[s.value]).map((s) => el("button", {
    type: "button", class: `chip${jobs.filters.status === s.value ? " ativo" : ""}`, "aria-pressed": String(jobs.filters.status === s.value),
    text: `${s.label}: ${data.counts[s.value]}`, onclick: () => setFilter("status", jobs.filters.status === s.value ? "" : s.value),
  }));
  return el("div", { class: "contagens", "aria-label": "Vagas por status" }, ...chips);
}

function list(data) {
  if (!data.items.length) return el("p", { class: "nota", text: "Nenhuma vaga com esses filtros." });
  const all = el("input", { type: "checkbox", "aria-label": "Selecionar todas as vagas desta página" });
  all.checked = data.items.length > 0 && data.items.every((item) => jobs.selected.has(item.id));
  all.addEventListener("change", () => {
    for (const item of data.items) all.checked ? jobs.selected.add(item.id) : jobs.selected.delete(item.id);
    document.querySelectorAll(".tabela-vagas tbody input[type=checkbox]").forEach((box) => { box.checked = all.checked; });
    refreshBulk();
  });
  const head = el("tr", {}, el("th", { scope: "col" }, all), ...["Vaga", "Status", "Site", "Local", "Aderência", "Pretensão", "Pendência", ""].map((t) => el("th", { scope: "col", text: t })));
  const rows = data.items.map((item) => el("tr", {},
    el("td", {}, (() => {
      const box = el("input", { type: "checkbox", "aria-label": `Selecionar ${item.role} — ${item.company}` });
      box.checked = jobs.selected.has(item.id);
      box.addEventListener("change", () => { box.checked ? jobs.selected.add(item.id) : jobs.selected.delete(item.id); refreshBulk(); });
      return box;
    })()),
    el("td", { "data-rotulo": "Vaga" }, jobLink(item)),
    el("td", { "data-rotulo": "Status" }, el("span", { class: `etapa etapa-${item.status}`, text: item.status_label })),
    el("td", { "data-rotulo": "Site", text: item.source_label }),
    el("td", { "data-rotulo": "Local", text: [item.location, item.work_mode].filter(Boolean).join(" · ") || "—" }),
    el("td", { "data-rotulo": "Aderência", text: item.match_score == null ? "—" : `${item.match_score}%` }),
    el("td", { "data-rotulo": "Pretensão", text: money(item.salary_ask) }),
    el("td", { "data-rotulo": "Pendência", text: item.pending || item.discard_reason || "—" }),
    el("td", {}, el("button", { type: "button", class: "remover", text: "Detalhes", "aria-label": `Detalhes de ${item.role} — ${item.company}`, onclick: () => openDetail(item.id) }))));
  return el("table", { class: "tabela-vagas" }, el("thead", {}, head), el("tbody", {}, ...rows));
}

function bulkBar() {
  const reason = el("input", { type: "text", id: "motivo-lote", placeholder: "Motivo do descarte", "aria-label": "Motivo do descarte das vagas selecionadas" });
  const button = el("button", { type: "button", class: "remover", id: "descartar-lote", text: "Descartar selecionadas", onclick: async () => {
    try {
      const result = await jobsAction({ action: "discard", ids: [...jobs.selected], reason: reason.value });
      jobs.selected.clear();
      await loadJobs();
      jobsMessage(`${result.items.length} vaga(s) descartada(s).`, "ok");
    } catch (error) {
      jobsMessage(error.message, "falha");
    }
  } });
  return el("div", { class: "lote" }, el("span", { id: "contagem-selecao" }), reason, button);
}

function refreshBulk() {
  const count = jobs.selected.size;
  const label = document.getElementById("contagem-selecao");
  if (label) label.textContent = count ? `${count} selecionada(s)` : "Nenhuma selecionada";
  const button = document.getElementById("descartar-lote");
  if (button) button.disabled = count === 0;
}

function pager(data) {
  const go = (page) => setFilter("page", String(page), true);
  return el("div", { class: "paginas" },
    el("button", { type: "button", class: "remover", text: "Anterior", disabled: data.page <= 1, onclick: () => go(data.page - 1) }),
    el("span", { text: `Página ${data.page} de ${data.pages} · ${data.total} vaga(s)` }),
    el("button", { type: "button", class: "remover", text: "Próxima", disabled: data.page >= data.pages, onclick: () => go(data.page + 1) }));
}

async function loadJobs() {
  const box = document.getElementById("vagas");
  const query = new URLSearchParams(Object.entries(jobs.filters).filter(([, v]) => v)).toString();
  try {
    const data = await jobsApi(`/api/jobs?${query}`);
    jobs.statuses = data.statuses;
    box.replaceChildren(filterBar(data), counts(data), el("p", { id: "vagas-status", role: "status", "aria-live": "polite" }),
      bulkBar(), list(data), pager(data), el("div", { id: "detalhe-vaga" }));
    refreshBulk();
    jobs.loaded = true;
  } catch (error) {
    box.replaceChildren(el("p", { class: "erro", text: error.message }));
  }
}

function setFilter(key, value, keepPage) {
  jobs.filters[key] = value;
  if (!keepPage) jobs.filters.page = "1";
  loadJobs();
}

function line(label, value) {
  return value ? el("div", { class: "linha-detalhe" }, el("dt", { text: label }), el("dd", { text: value })) : null;
}

function actionsForm(app) {
  const message = el("p", { class: "nota", role: "status" });
  const done = async (body, text) => {
    try {
      await jobsAction(body);
      await loadJobs();
      await openDetail(app.id);
      jobsMessage(text, "ok");
    } catch (error) {
      message.textContent = error.message;
    }
  };
  if (app.status === "descartada") {
    const reason = el("input", { type: "text", placeholder: "Por que reabrir? (opcional)", "aria-label": "Motivo para reabrir" });
    return el("div", { class: "acoes-vaga" }, el("h3", { text: "Reabrir" }),
      el("p", { class: "ajuda", text: "Volta para a lista de trabalho (a aplicar), com o motivo no histórico." }), reason,
      el("button", { type: "button", class: "aprovar", text: "Reabrir a vaga", onclick: () => done({ action: "reopen", id: app.id, reason: reason.value }, "Vaga reaberta.") }), message);
  }
  const stage = el("select", { id: "etapa-vaga" }, ...jobs.statuses.map((s) => el("option", { value: s.value, text: s.label })));
  stage.value = app.status;
  const pending = el("textarea", { id: "pendencia-vaga", rows: "2" });
  pending.value = app.pending || "";
  const note = el("input", { type: "text", id: "nota-vaga", placeholder: "Ex.: entrevista marcada para sexta" });
  const reason = el("input", { type: "text", id: "motivo-vaga", placeholder: "Ex.: salário abaixo do mínimo" });
  const reasonBox = el("label", { class: "filtro", hidden: true }, el("span", { text: "Motivo do descarte" }), reason);
  stage.addEventListener("change", () => { reasonBox.hidden = stage.value !== "descartada"; });
  const field = (label, node) => el("label", { class: "filtro" }, el("span", { text: label }), node);
  return el("div", { class: "acoes-vaga" }, el("h3", { text: "Atualizar" }),
    el("div", { class: "acoes-grade" }, field("Etapa", stage), reasonBox, field("Pendência (vazio limpa)", pending), field("Anotação no histórico", note)),
    el("button", { type: "button", class: "aprovar", text: "Salvar alterações", onclick: () => done({
      action: "update", id: app.id, status: stage.value === app.status ? "" : stage.value, pending: pending.value,
      note: note.value, discard_reason: reason.value }, "Vaga atualizada.") }), message);
}

async function openDetail(id) {
  const target = document.getElementById("detalhe-vaga");
  try {
    const { application: app, events, resumes } = await jobsApi(`/api/jobs/${id}`);
    const salary = app.salary_evaluation || {};
    const terms = app.match_terms || {};
    const close = el("button", { type: "button", class: "remover", text: "Fechar", onclick: () => target.replaceChildren() });
    const timeline = el("ol", { class: "linha-do-tempo" }, ...events.map((e) => el("li", { text:
      `${new Date(e.at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })} · ${e.from_label ? `${e.from_label} → ` : ""}${e.to_label}${e.note ? ` — ${e.note}` : ""}` })));
    const files = resumes.length ? el("ul", { class: "mudancas" }, ...resumes.map((r) => el("li", { text: `${r.label} — ${r.windows_path || r.pdf_path}` }))) : null;
    const description = app.description ? el("details", { class: "cv-secao" }, el("summary", { text: "Descrição da vaga" }), el("p", { class: "descricao", text: app.description })) : null;
    target.replaceChildren(el("section", { class: "secao detalhe", "aria-label": `Detalhes de ${app.role}` },
      el("div", { class: "faixa-topo" }, el("h2", {}, jobLink(app)), close),
      el("dl", {},
        line("Status", app.status_label), line("Site", app.source_label),
        line("Local", [app.location, app.work_mode, app.seniority].filter(Boolean).join(" · ")),
        line("Aderência", app.match_score == null ? "" : `${app.match_score}%`),
        line("Termos presentes", (terms.matched || []).join(", ")), line("Termos ausentes", (terms.missing || []).join(", ")),
        line("Pretensão", app.salary_ask == null ? "" : money(app.salary_ask)), line("Avaliação salarial", salary.reason),
        line("Pendência", app.pending), line("Motivo do descarte", app.discard_reason),
        line("Registrada em", (app.created_at || "").slice(0, 10))),
      actionsForm(app), el("h3", { text: "Histórico" }), timeline,
      files ? el("h3", { text: "Currículos gerados" }) : null, files, description));
    target.querySelector("h2 a, h2 span").focus?.();
    target.scrollIntoView({ block: "start" });
  } catch (error) {
    target.replaceChildren(el("p", { class: "erro", text: error.message }));
  }
}

function showView() {
  const vagas = location.hash === "#vagas";
  document.getElementById("vista-configuracao").hidden = vagas;
  document.getElementById("vista-vagas").hidden = !vagas;
  document.getElementById("intro-config").hidden = vagas;
  document.getElementById("intro-vagas").hidden = !vagas;
  document.getElementById("titulo-pagina").textContent = vagas ? "Vagas" : "Configuração";
  document.getElementById("aba-vagas").toggleAttribute("aria-current", vagas);
  document.getElementById("aba-configuracao").toggleAttribute("aria-current", !vagas);
  if (vagas) document.getElementById("aba-vagas").setAttribute("aria-current", "page");
  else document.getElementById("aba-configuracao").setAttribute("aria-current", "page");
  if (vagas && !jobs.loaded) loadJobs();
}

window.addEventListener("hashchange", showView);
showView();
