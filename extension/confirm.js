// Janela de confirmação. Todo texto vindo da página entra por textContent, nunca como HTML.
const id = new URLSearchParams(location.search).get("id");

function list(items) {
  return items.length > 1 ? `${items.slice(0, -1).join(", ")} e ${items[items.length - 1]}` : items[0];
}

let resumeId = null;
let mustChoose = false;
const accepting = [];

function button(label, answer, primary) {
  const el = document.createElement("button");
  el.textContent = label;
  if (primary) el.className = "primary";
  if (answer !== "no") accepting.push(el);
  el.disabled = answer !== "no" && mustChoose;
  el.addEventListener("click", async () => {
    await chrome.runtime.sendMessage({ type: "confirm-answer", id, answer, resumeId });
    window.close();
  });
  document.getElementById("buttons").append(el);
}

function resumeChoices(resumes) {
  const box = document.getElementById("resumes");
  for (const resume of resumes) {
    const row = document.createElement("label");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "resume";
    radio.addEventListener("change", () => {
      resumeId = resume.application_id;
      for (const el of accepting) el.disabled = false;
    });
    const text = document.createElement("span");
    text.textContent = `${resume.label}: ${resume.name}`;
    row.append(radio, text);
    box.append(row);
  }
}

async function main() {
  const details = await chrome.runtime.sendMessage({ type: "confirm-details", id });
  if (!details) {
    document.getElementById("question").textContent = "Este pedido já foi respondido ou expirou.";
    return;
  }
  const { origin, documents, terms = [], resumes = [], title } = details;
  const actions = [];
  if (documents.length) actions.push(`preencher ${list(documents)}`);
  if (terms.length) actions.push(terms.length > 1 ? `aceitar estes ${terms.length} termos` : "aceitar este termo");
  if (resumes.length === 1) {
    actions.push(`anexar o currículo ${resumes[0].name}`);
    resumeId = resumes[0].application_id;
  } else if (resumes.length > 1) {
    actions.push("anexar o currículo escolhido abaixo");
    mustChoose = true;
    resumeChoices(resumes);
  }
  const question = `${list(actions)} em ${origin.label}?`;
  document.getElementById("question").textContent = question[0].toUpperCase() + question.slice(1);
  const accepted = document.getElementById("terms");
  for (const text of terms) {
    const item = document.createElement("li");
    item.textContent = text.length > 240 ? `${text.slice(0, 240)}…` : text;
    accepted.append(item);
  }
  document.getElementById("where").textContent = `Endereço: ${origin.host}`;
  if (title) document.getElementById("title").textContent = `Página: ${title}`;
  if (origin.remember) {
    button(`Permitir sempre para ${origin.label}`, "always", true);
    button("Só desta vez", "once");
  } else {
    document.getElementById("note").textContent =
      "Neste site várias empresas publicam vagas no mesmo endereço, então a confirmação vale só para esta vaga.";
    button("Preencher nesta vaga", "once", true);
  }
  button("Não preencher", "no");
  setInterval(() => chrome.runtime.sendMessage({ type: "keepalive" }).catch(() => {}), 20000);
}

main();
