"""Ciclo de vida do currículo geral: rascunho em YAML editável, aprovação e versões. Não depende de MCP."""

import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from vagas.db import default_db_path
from vagas.models import LINKEDIN_SECTIONS, RESUME_SOURCE_KINDS
from vagas.normalize import normalize_text
from vagas.repo import Repo, VagasError, _require_choice, _require_text, _utcnow
from vagas.resume_extract import extract_pages, review_draft, wsl_path
from vagas.resume_diff import diff_master
from vagas.resume_suggest import suggest_selection
from vagas.resume_model import MasterResume, describe_errors
from vagas.resume_render import render_resume
from vagas.resume_tailor import TailoredSelection, resolve
from vagas.resume_validate import match_terms, strings, term_set


def default_draft_path(db_path: Path | str | None = None) -> Path:
    if env := os.environ.get("VAGAS_MASTER_RESUME"):
        return Path(env)
    db = Path(db_path) if db_path is not None else default_db_path()
    return db.parent / "curriculo.yaml"


# Tecnologias reconhecidas mesmo no início de frase e sem marcas de sigla (minúsculas).
TECH_TERMS = frozenset("""
python sql spark pyspark kafka airflow pandas numpy scipy polars docker kubernetes terraform ansible tableau looker
prefect dagster luigi wandb chromadb pgvector milvus catboost
statsmodels sklearn scikit-learn matplotlib seaborn plotly optuna ray dask
databricks snowflake bigquery redshift athena glue lambda sagemaker vertex mlflow kubeflow dbt hadoop hive scala java
kotlin rust go golang julia matlab elixir javascript typescript react node django flask fastapi streamlit pytorch
tensorflow keras jax xgboost lightgbm catboost langchain langgraph llamaindex huggingface transformers openai
anthropic bedrock qdrant pinecone weaviate chroma faiss elasticsearch opensearch postgres postgresql mysql mongodb
redis cassandra neo4j git github gitlab jenkins linux bash azure gcp aws excel powerbi grafana prometheus kibana
""".split())
# Famílias de ferramentas equivalentes: um termo ausente da vaga aponta os da mesma família presentes no
# currículo ("relacionados"), sem contar como presente na nota.
TECH_FAMILIES: dict[str, tuple[str, ...]] = {
    "gradient boosting": ("XGBoost", "LightGBM", "CatBoost"),
    "mlops": ("MLflow", "Weights & Biases", "W&B", "wandb", "Kubeflow", "SageMaker", "Vertex AI"),
    "nuvem": ("AWS", "Azure", "GCP"),
    "bancos vetoriais": ("Qdrant", "Pinecone", "Weaviate", "ChromaDB", "Chroma", "PGVector", "Milvus", "FAISS"),
    "orquestração": ("Airflow", "Prefect", "Dagster", "Luigi"),
    "deep learning": ("PyTorch", "TensorFlow", "Keras", "JAX"),
    "bi": ("Power BI", "PowerBI", "Tableau", "Looker", "Metabase", "Superset"),
    "data warehouse": ("BigQuery", "Redshift", "Snowflake", "Databricks", "Synapse"),
    "llm frameworks": ("LangChain", "LangGraph", "LlamaIndex", "Haystack"),
    "streaming": ("Kafka", "Kinesis", "Pub/Sub", "RabbitMQ"),
}


# Trechos de requisitos desejáveis: começam num marcador forte e vão até o próximo cabeçalho.
_OPTIONAL_START = re.compile(
    r"\b(diferenciais|nice[- ]to[- ]have|bonus points|preferred qualifications|nice to haves)\b"
    r"|\b(diferencial|desejaveis|desejavel|sera um plus|e um plus|plus|bonus|preferred)\s*:")
_SECTION_START = re.compile(
    r"\b(requisitos|requirements|qualificacoes|qualifications|responsabilidades|responsibilities|atividades"
    r"|beneficios|benefits|o que oferecemos|what we offer|what you bring|what you will do|sobre (a|o|nos)\b"
    r"|about (us|the)|informacoes adicionais|etapas do processo|local de trabalho)\b")
OPTIONAL_WEIGHT = 0.5


def _fold(text: str) -> str:
    """Minúsculas sem acento, com o mesmo comprimento (as posições continuam valendo no texto original)."""
    out = []
    for char in text:
        ascii_char = unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode()
        out.append((ascii_char[:1] or char).lower())
    return "".join(out)


def _optional_spans(text: str) -> list[tuple[int, int]]:
    folded = _fold(text)
    spans = []
    for start in _OPTIONAL_START.finditer(folded):
        end = _SECTION_START.search(folded, start.end())
        spans.append((start.start(), end.start() if end else len(text)))
    return spans


def _only_optional(term: str, text: str, spans: list[tuple[int, int]]) -> bool:
    places = [m.start() for m in re.finditer(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.I)]
    return bool(places) and all(any(a <= p < b for a, b in spans) for p in places)


def _in_resume(name: str, corpus: set[str]) -> bool:
    """Nome de uma palavra: o token inteiro ("W&B"); de várias: todas as palavras ("Power BI")."""
    words = name.lower().split()
    return words[0] in corpus if len(words) == 1 else all(w in corpus for w in words)


def _related(missing: list[str], corpus: set[str]) -> dict[str, list[str]]:
    related: dict[str, list[str]] = {}
    for term in missing:
        low = term.lower()
        for family in TECH_FAMILIES.values():
            if low not in {name.lower() for name in family}:
                continue
            found = [name for name in family if name.lower() != low and _in_resume(name, corpus)]
            if found:
                related.setdefault(term, []).extend(n for n in found if n not in related.get(term, []))
    return related


# Siglas e palavras em maiúsculas que não são tecnologia.
_COMMON_CAPS = frozenset("""
clt pj pf rh sp rj mg pr sc rs br usa eua ltda sa me gptw todos para com nos voce voces ceo cto cfo we you our the
and pcd lgbt lgbtqia lgbtqi lgbtqia+ lgbtqi+ esg ti home office vr va plr ppr dia jr sr pl ii iii usd brl eur latam
emea apac kpi kpis okr okrs lgpd cmn dna p&l sesc senai
totalpass gympass wellhub alelo sodexo flash caju swile zenklub
""".split())


def _technical(term: str, skills: set[str], excluded: set[str]) -> str | None:
    """O termo na forma a mostrar, se for técnico; senão None."""
    term = term.strip("®™©")
    if re.search(r"[a-z]\.[A-Z][a-z]", term):  # ponto sem espaço entre frases: "Statsmodels.Conhecimento"
        term = term.split(".")[0]
    low = term.lower()
    words = set(re.findall(r"[a-z0-9]+", normalize_text(term)))
    if not term or term.startswith("#") or (words and words <= excluded):
        return None
    if low in skills or low in TECH_TERMS:
        return term
    if low in _COMMON_CAPS:
        return None
    if re.fullmatch(r"[A-Za-z]{1,2}(\+\+|#)", term):  # C++, C#, F#
        return term
    if re.fullmatch(r"\d+[a-z]{0,2}", low):  # 3x, 24h, 5k
        return None
    if any(c.isdigit() for c in term) or re.search(r"[A-Za-z]\.[A-Za-z]", term) or term.startswith("."):
        return term
    letters = re.sub(r"[^A-Za-z]", "", term)
    if letters.isupper() and 2 <= len(letters) <= 5:
        return term
    return term if re.search(r"[a-z][A-Z]", term) or re.match(r"[A-Z]{2,}[a-z]", term) else None


class _Dumper(yaml.SafeDumper):
    pass


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.Node:
    # Parágrafos longos em bloco dobrado (>-) ficam legíveis e editáveis à mão.
    style = ">" if len(value) > 80 and "\n" not in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _represent_str)


def _to_yaml(data: dict[str, Any]) -> str:
    return yaml.dump(data, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=100)


def _content_hash(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _source_text(content: list[str] | dict[str, str]) -> str:
    return "\n".join(content.values() if isinstance(content, dict) else content)


def _validate(data: Any) -> MasterResume:
    if isinstance(data, MasterResume):
        return data
    try:
        return MasterResume.model_validate(data)
    except ValidationError as exc:
        raise VagasError(describe_errors(exc)) from exc


class ResumeStore:
    def __init__(self, conn: sqlite3.Connection, draft_path: Path | str, now: Callable[[], str] = _utcnow):
        self.conn = conn
        self.draft_path = Path(draft_path)
        self.now = now

    def save_master_draft(self, resume: Any, overwrite: bool = False) -> dict[str, Any]:
        data = _validate(resume).as_data()
        if self.draft_path.exists() and not overwrite and self._has_unapproved_edits():
            raise VagasError(
                f"O rascunho {self.draft_path} tem alterações que não foram aprovadas nem escritas por "
                "esta tool (provavelmente edições do usuário). Peça ao usuário para aprovar ou descartar "
                "as edições; só use overwrite=true se ele concordar em sobrescrevê-las."
            )
        text = _to_yaml(data)
        self.draft_path.parent.mkdir(parents=True, exist_ok=True)
        self.draft_path.write_text(text, encoding="utf-8")
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO master_draft (id, file_hash, written_at) VALUES (1, ?, ?)",
                (_text_hash(text), self.now()),
            )
        sources = self._latest_sources()
        if not sources:
            return {"path": str(self.draft_path), "sources": [], "review": None}
        reference = "\n".join(_source_text(json.loads(s["content"])) for s in sources)
        return {
            "path": str(self.draft_path),
            "sources": [{"kind": s["kind"], "path": s["path"]} for s in sources],
            "review": review_draft(data, reference),
        }

    def save_resume_source(
        self, kind: str, url: str, sections: dict[str, str] | None = None, text: str | None = None,
    ) -> dict[str, Any]:
        """Registra uma fonte do currículo geral: seções do LinkedIn ou o texto de um PDF já extraído."""
        _require_choice("kind", kind, RESUME_SOURCE_KINDS)
        url = _require_text("url", url)
        if kind == "pdf":
            if sections is not None:
                raise VagasError("Fonte 'pdf' recebe o texto em 'text', não em 'sections'.")
            text = _require_text("text", text)
            with self.conn:
                cursor = self.conn.execute(
                    "INSERT INTO resume_sources (kind, path, content, extracted_at) VALUES ('pdf', ?, ?, ?)",
                    (url, json.dumps([text], ensure_ascii=False), self.now()),
                )
            return {"source_id": cursor.lastrowid, "chars": len(text)}
        if text is not None:
            raise VagasError("Fonte 'linkedin' recebe o texto por seção em 'sections', não em 'text'.")
        if not sections:
            raise VagasError(f"Informe 'sections' com ao menos uma seção: {', '.join(LINKEDIN_SECTIONS)}.")
        cleaned = {}
        for name, text in sections.items():
            _require_choice("sections", name, LINKEDIN_SECTIONS)
            cleaned[name] = _require_text(f"sections.{name}", text)
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO resume_sources (kind, path, content, extracted_at) VALUES (?, ?, ?, ?)",
                (kind, url, json.dumps(cleaned, ensure_ascii=False), self.now()),
            )
        return {"source_id": cursor.lastrowid, "sections": {name: len(text) for name, text in cleaned.items()}}

    def _latest_sources(self) -> list[sqlite3.Row]:
        """Fonte mais recente de cada tipo, PDF primeiro."""
        sources = []
        for kind in ("pdf", *(k for k in RESUME_SOURCE_KINDS if k != "pdf")):
            row = self.conn.execute(
                "SELECT kind, path, content FROM resume_sources WHERE kind = ? "
                "ORDER BY extracted_at DESC, id DESC LIMIT 1",
                (kind,),
            ).fetchone()
            if row:
                sources.append(row)
        return sources

    def extract_resume_text(self, pdf_path: str | Path) -> dict[str, Any]:
        """Extrai o texto do PDF e o guarda como referência para revisar os próximos rascunhos."""
        path = wsl_path(pdf_path)
        pages = extract_pages(path)
        with self.conn:
            self.conn.execute(
                "INSERT INTO resume_sources (kind, path, content, extracted_at) VALUES ('pdf', ?, ?, ?)",
                (str(path), json.dumps(pages, ensure_ascii=False), self.now()),
            )
        return {"path": str(path), "page_count": len(pages), "pages": pages}

    def approve_master(self) -> dict[str, Any]:
        data = _validate(self._read_draft()).as_data()
        content_hash = _content_hash(data)
        existing = self.conn.execute(
            "SELECT id FROM master_resumes WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if existing:
            return {"created": False, "version_id": existing["id"], "content_hash": content_hash}
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO master_resumes (content_hash, content, approved_at) VALUES (?, ?, ?)",
                (content_hash, json.dumps(data, ensure_ascii=False), self.now()),
            )
        return {"created": True, "version_id": cursor.lastrowid, "content_hash": content_hash}

    def get_master_resume(self) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM master_resumes ORDER BY approved_at DESC, id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise VagasError(
                "Nenhum currículo geral aprovado. Gere o rascunho com save_master_draft, peça ao "
                "usuário para revisá-lo e, com a aprovação explícita dele, chame approve_master."
            )
        return {
            "version_id": row["id"],
            "content_hash": row["content_hash"],
            "approved_at": row["approved_at"],
            "resume": json.loads(row["content"]),
        }

    def create_tailored_resume(
        self, selection: Any, out_dir: Path | str | None, application_id: int | None = None,
    ) -> dict[str, Any]:
        """Valida a seleção contra o currículo geral, gera o PDF e registra. Nada é gravado se falhar."""
        if application_id is not None and not self.conn.execute(
            "SELECT 1 FROM applications WHERE id = ?", (application_id,)
        ).fetchone():
            raise VagasError(f"Candidatura {application_id} não existe.")
        if not isinstance(selection, TailoredSelection):
            try:
                selection = TailoredSelection.model_validate(selection)
            except ValidationError as exc:
                raise VagasError(describe_errors(exc, "Seleção inválida")) from exc
        master = self.get_master_resume()
        resolved = resolve(master["resume"], selection)
        rendered = render_resume(resolved, out_dir, label=selection.label)
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO resumes (
                    master_resume_id, application_id, label, selection, resolved, pdf_path, pages, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (master["version_id"], application_id, selection.label,
                 json.dumps(selection.model_dump(exclude_none=True), ensure_ascii=False),
                 json.dumps(resolved, ensure_ascii=False), rendered["path"], rendered["pages"], self.now()),
            )
        return {"id": cursor.lastrowid, **rendered}

    def suggest_tailored_selection(self, application_id: int) -> dict[str, Any]:
        """Seleção inicial do currículo personalizado pelos termos da candidatura (ver resume_suggest)."""
        app = Repo(self.conn).get(application_id)
        terms = (app.get("match_terms") or {}).get("matched") or []
        if not terms and app.get("description"):
            terms = self.score_job_match(app["description"], company=app["company"], title=app["role"],
                                         location=app.get("location"))["matched"]
        master = self.get_master_resume()["resume"]
        result = suggest_selection(master, terms, label=app["company"])
        resolve(master, TailoredSelection.model_validate(result["selection"]))  # a sugestão sempre passa
        return result

    def diff_master(self, items: dict[str, Any]) -> dict[str, Any]:
        """Compara itens das fontes com o currículo geral aprovado (ver resume_diff). Não salva nada."""
        if not isinstance(items, dict):
            raise VagasError("'items' deve ser um objeto com as seções do currículo (ex.: o items de "
                             "import_linkedin_profile).")
        result = diff_master(self.get_master_resume()["resume"], items)
        try:
            MasterResume.model_validate(result["draft"])
        except ValidationError as exc:
            raise VagasError(describe_errors(exc, "O rascunho resultante ficou inválido; corrija os itens")) from exc
        return result

    def score_job_match(self, description: str, company: str | None = None, title: str | None = None,
                        location: str | None = None) -> dict[str, Any]:
        """Aderência da vaga ao currículo geral: termos técnicos da descrição presentes e ausentes.

        Só contam tecnologias (skills do currículo, TECH_TERMS, siglas, CamelCase, nomes com dígitos
        ou símbolos); palavras da empresa, do título e do local da vaga são ignoradas.
        """
        description = _require_text("description", description)
        master = self.get_master_resume()["resume"]
        skill_terms = [term for group in master.get("skills", []) for term in group["terms"]]
        # Skills de uma palavra contam como termo; as de várias ("Machine Learning") só como frase inteira,
        # para palavras soltas como "Data" e "Learning" não virarem termos técnicos.
        skills = term_set(t for t in skill_terms if " " not in t.strip())
        phrases = [t for t in dict.fromkeys(skill_terms) if " " in t.strip()
                   and re.search(rf"(?<!\w){re.escape(t)}(?!\w)", description, re.I)]
        corpus = term_set(strings(master))
        matched, missing = match_terms(description, corpus, skills | TECH_TERMS)
        excluded = {w for text in (company, title, location) if text
                    for w in re.findall(r"[a-z0-9]+", normalize_text(text)) if len(w) > 1}
        terms = list(dict.fromkeys(t for t in (_technical(t, skills, excluded) for t in matched + missing) if t))

        def present(term: str) -> bool:  # termos de início de frase não passam pela checagem de match_terms
            return term.lower() in corpus or all(p.lower() in corpus for p in term.split("-") if p)

        matched = [t for t in terms if present(t)] + [p for p in phrases if p not in terms]
        missing = [t for t in terms if not present(t)]
        terms = [*terms, *(p for p in phrases if p not in terms)]
        total = len(matched) + len(missing)
        if total == 0:
            return {"score": None, "matched": [], "missing": [], "related": {}, "optional": [],
                    "note": "A descrição não tem termos técnicos reconhecíveis (tecnologias, siglas, nomes "
                            "próprios); avalie a aderência pela leitura da vaga."}
        spans = _optional_spans(description)
        optional = [t for t in terms if spans and _only_optional(t, description, spans)]
        weight = {t: OPTIONAL_WEIGHT if t in optional else 1.0 for t in terms}
        score = round(100 * sum(weight[t] for t in matched) / sum(weight.values()))
        return {"score": score, "matched": matched, "missing": missing, "related": _related(missing, corpus),
                "optional": optional, "note": None}

    def list_resumes(self, application_id: int | None = None) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, label, pdf_path, pages, master_resume_id, application_id, created_at
            FROM resumes WHERE ? IS NULL OR application_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (application_id, application_id),
        )
        return [dict(row) for row in rows]

    def get_resume(self, resume_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
        if row is None:
            raise VagasError(f"Currículo personalizado {resume_id} não existe.")
        resume = dict(row)
        resume["selection"] = json.loads(resume["selection"])
        resume["resolved"] = json.loads(resume["resolved"])
        return resume

    def _read_draft(self) -> Any:
        if not self.draft_path.exists():
            raise VagasError(f"Não há rascunho em {self.draft_path}. Gere um com save_master_draft.")
        try:
            return yaml.safe_load(self.draft_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise VagasError(f"YAML inválido em {self.draft_path}: {exc}") from exc

    def _has_unapproved_edits(self) -> bool:
        text = self.draft_path.read_text(encoding="utf-8")
        written = self.conn.execute("SELECT file_hash FROM master_draft WHERE id = 1").fetchone()
        if written and written["file_hash"] == _text_hash(text):
            return False
        try:
            data = MasterResume.model_validate(yaml.safe_load(text)).as_data()
        except (yaml.YAMLError, ValidationError):
            return True
        approved = self.conn.execute(
            "SELECT 1 FROM master_resumes WHERE content_hash = ?", (_content_hash(data),)
        ).fetchone()
        return approved is None
