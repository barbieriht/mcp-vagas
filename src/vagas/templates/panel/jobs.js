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
  const fromSearch = f.search_id ? el("p", { class: "nota aviso filtro-busca" },
    el("span", { text: `Mostrando só as vagas da busca ${f.search_label || "#" + f.search_id}. ` }),
    el("button", { type: "button", class: "remover", text: "Limpar este filtro", onclick: () => { delete f.search_label; setFilter("search_id", ""); } })) : null;
  return el("div", { class: "filtros-area" }, fromSearch, el("div", { class: "filtros" },
    control("Busca", text), control("Status", select("status", data.statuses, "Todos")),
    control("Site", select("source", data.sources, "Todos")), control("Desde", since),
    control("Aderência mínima", score), control("Ordem", order),
    el("label", { class: "filtro opcao" }, pending, el("span", { text: "Só com pendência" }))));
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
  const query = new URLSearchParams(Object.entries(jobs.filters).filter(([k, v]) => v && k !== "search_label")).toString();
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

// Buscas feitas: buscas registradas e buscas em lote. Só leitura; "Ver vagas" filtra a aba Vagas pela busca.
function when(value) {
  return value ? new Date(value).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—";
}

function runCard(run) {
  const progress = run.progress || {};
  const summary = run.summary || {};
  const parts = [];
  if (progress.searches_total != null) parts.push(`buscas: ${progress.searches_done || 0} de ${progress.searches_total}`);
  if (progress.jobs_total != null) parts.push(`triagens: ${progress.jobs_done || 0} de ${progress.jobs_total}`);
  if (summary.jobs) parts.push(`vagas novas: ${summary.jobs.triaged}, já registradas: ${summary.jobs.already_registered}`);
  const errors = (summary.errors || []).length + (run.error ? 1 : 0);
  return el("li", { class: `busca-lote lote-${run.status}` },
    el("span", { class: "etapa", text: run.status_label }),
    el("span", { text: ` ${when(run.started_at)}${run.finished_at ? ` → ${when(run.finished_at)}` : ""}` }),
    parts.length ? el("span", { class: "nota", text: ` · ${parts.join(" · ")}` }) : null,
    run.status === "running" && progress.current ? el("span", { class: "nota", text: ` · agora: ${progress.current}` }) : null,
    errors ? el("span", { class: "nota", text: ` · ${errors} erro(s)${run.error ? `: ${run.error}` : ""}` }) : null);
}

async function loadSearches() {
  const box = document.getElementById("buscas");
  const source = searchesState.source || "";
  try {
    const data = await jobsApi(`/api/searches${source ? `?source=${encodeURIComponent(source)}` : ""}`);
    const site = el("select", {}, el("option", { value: "", text: "Todos" }), ...data.sources.map((s) => el("option", { value: s.value, text: s.label })));
    site.value = source;
    site.addEventListener("change", () => { searchesState.source = site.value; loadSearches(); });
    const refresh = el("button", { type: "button", class: "remover", text: "Atualizar", onclick: loadSearches });
    const runs = data.runs.length
      ? el("ul", { class: "lotes" }, ...data.runs.map(runCard))
      : el("p", { class: "nota", text: "Nenhuma busca em lote ainda. Peça ao Claude: \"busque vagas para mim\"." });
    const head = el("tr", {}, ...["Quando", "Site", "Consulta", "Local", "Filtros", "Resultados", "Vagas registradas"].map((t) => el("th", { scope: "col", text: t })));
    const rows = data.searches.map((s) => el("tr", {},
      el("td", { "data-rotulo": "Quando", text: when(s.searched_at) }),
      el("td", { "data-rotulo": "Site", text: s.source_label }),
      el("td", { "data-rotulo": "Consulta", text: s.query }),
      el("td", { "data-rotulo": "Local", text: s.location || "—" }),
      el("td", { "data-rotulo": "Filtros", text: s.filters ? Object.entries(s.filters).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : v}`).join("; ") : "—" }),
      el("td", { "data-rotulo": "Resultados", text: String(s.results_count ?? "—") }),
      el("td", { "data-rotulo": "Vagas registradas" }, s.jobs_count
        ? el("button", { type: "button", class: "remover", text: `Ver ${s.jobs_count} vaga(s)`, "aria-label": `Ver as vagas da busca ${s.query}`, onclick: () => {
          jobs.filters = { order: "", page: "1", search_id: String(s.id), search_label: `"${s.query}" (${s.source_label})` };
          location.hash = "#vagas";
          loadJobs();
        } })
        : el("span", { text: "0" }))));
    const table = data.searches.length
      ? el("table", { class: "tabela-vagas" }, el("thead", {}, head), el("tbody", {}, ...rows))
      : el("p", { class: "nota", text: "Nenhuma busca registrada com esse filtro." });
    box.replaceChildren(
      el("div", { class: "faixa-topo" }, el("h2", { text: "Buscas em lote" }), refresh), runs,
      el("div", { class: "faixa-topo" }, el("h2", { text: "Buscas registradas" }), el("label", { class: "filtro" }, el("span", { text: "Site" }), site)), table);
    searchesState.loaded = true;
  } catch (error) {
    box.replaceChildren(el("p", { class: "erro", text: error.message }));
  }
}

const searchesState = { source: "", loaded: false };

function showView() {
  const view = location.hash === "#vagas" ? "vagas" : location.hash === "#buscas" ? "buscas" : "configuracao";
  const titles = { configuracao: "Configuração", vagas: "Vagas", buscas: "Buscas" };
  document.getElementById("vista-configuracao").hidden = view !== "configuracao";
  document.getElementById("vista-vagas").hidden = view !== "vagas";
  document.getElementById("vista-buscas").hidden = view !== "buscas";
  document.getElementById("intro-config").hidden = view !== "configuracao";
  document.getElementById("intro-vagas").hidden = view !== "vagas";
  document.getElementById("intro-buscas").hidden = view !== "buscas";
  document.getElementById("titulo-pagina").textContent = titles[view];
  for (const name of Object.keys(titles)) {
    const tab = document.getElementById(`aba-${name}`);
    if (name === view) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  }
  if (view === "vagas" && !jobs.loaded) loadJobs();
  if (view === "buscas") loadSearches();
}

window.addEventListener("hashchange", showView);
showView();
