"""Atualização automática: a cada sessão, o servidor puxa o repositório e reinstala a cópia estável.

Testado contra repositórios git de verdade num diretório temporário (uma "origem" e o clone do
usuário) e um instalador falso, que só registra as chamadas.
"""

import json
import subprocess
import threading
from pathlib import Path

import pytest

from vagas import auto_update, md_fields, salary_policy, triage
from vagas.auto_update import update

SKILL = Path(__file__).resolve().parents[1] / "skill" / "candidaturas"

PERFIL = """# Dados para formulários

## Contato e identificação
- Nome: Fulano de Tal
- Telefone: +55 (00) 00000-0000

## Respostas padrão
- Parentes na empresa: não
"""

CRITERIOS = """# Critérios de triagem

- Cargos alvo: <PREENCHER: os cargos>
- Aderência mínima: 50

## Valores aceitos

- **Aderência mínima:** número.
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit_files(repo: Path, files: dict[str, str], message: str = "muda") -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


class Installer:
    def __init__(self, fail: bool = False):
        self.calls: list[Path] = []
        self.fail = fail

    def __call__(self, repo: Path) -> None:
        self.calls.append(repo)
        if self.fail:
            raise RuntimeError("uv: falhou ao instalar")


@pytest.fixture
def setup(tmp_path):
    """origin (o GitHub), dev (outra máquina que publica) e repo (o clone instalado do usuário)."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    dev = tmp_path / "dev"
    subprocess.run(["git", "clone", "-q", str(origin), str(dev)], check=True, capture_output=True)
    for repo_dir in (dev,):
        git(repo_dir, "config", "user.email", "teste@example.com")
        git(repo_dir, "config", "user.name", "Teste")
    git(dev, "checkout", "-q", "-b", "main")
    commit_files(dev, {
        ".gitignore": "skill/candidaturas/perfil.md\nskill/candidaturas/criterios-triagem.md\n",
        "skill/candidaturas/perfil.example.md": PERFIL,
        "skill/candidaturas/criterios-triagem.example.md": CRITERIOS,
        "skill/candidaturas/SKILL.md": "skill\n",
        "extension/manifest.json": "{}\n",
        "src/vagas/x.py": "x = 1\n",
    }, "inicial")
    git(dev, "push", "-q", "origin", "main")
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.email", "teste@example.com")
    git(repo, "config", "user.name", "Teste")
    (repo / "skill/candidaturas/perfil.md").write_text(
        PERFIL.replace("Fulano de Tal", "Pessoa Teste"), encoding="utf-8")
    (repo / "skill/candidaturas/criterios-triagem.md").write_text(
        CRITERIOS.replace("<PREENCHER: os cargos>", "Cientista de Dados"), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    return {"origin": origin, "dev": dev, "repo": repo, "data": data}


def record(data: Path) -> dict:
    return json.loads((data / auto_update.RECORD).read_text(encoding="utf-8"))


def mark_installed(setup) -> None:
    """Como o instalador deixa a cópia estável: registrada no commit atual do clone."""
    auto_update.write_record(setup["data"], git(setup["repo"], "rev-parse", "HEAD"))


def test_pulls_new_commits_reinstalls_and_records_the_installed_commit(setup):
    mark_installed(setup)
    before = git(setup["repo"], "rev-parse", "HEAD")
    new = commit_files(setup["dev"], {"src/vagas/x.py": "x = 2\n"})
    git(setup["dev"], "push", "-q", "origin", "main")
    installer = Installer()

    result = update(setup["repo"], setup["data"], installer)

    assert git(setup["repo"], "rev-parse", "HEAD") == new
    assert installer.calls == [setup["repo"]]
    assert record(setup["data"])["commit"] == new
    assert result["status"] == "atualizado"
    assert result["from"] == before[:7] and result["to"] == new[:7]
    assert any("conversa nova" in action for action in result["actions"])


def test_up_to_date_does_nothing(setup):
    mark_installed(setup)
    installer = Installer()

    result = update(setup["repo"], setup["data"], installer)

    assert installer.calls == []
    assert result == {"status": "em_dia", "version": git(setup["repo"], "rev-parse", "HEAD")[:7]}


def test_copy_installed_before_this_feature_is_reinstalled_once(setup):
    """Sem registro (instalada antes da atualização automática, ou o clone andou e o instalador não rodou)."""
    installer = Installer()

    first = update(setup["repo"], setup["data"], installer)
    second = update(setup["repo"], setup["data"], installer)

    assert first["status"] == "atualizado" and len(installer.calls) == 1
    assert second["status"] == "em_dia" and len(installer.calls) == 1


def test_clone_ahead_of_the_installed_copy_is_reinstalled(setup):
    """O usuário deu git pull à mão e não rodou o instalador: a cópia estável ficou para trás."""
    mark_installed(setup)
    commit_files(setup["dev"], {"src/vagas/x.py": "x = 3\n"})
    git(setup["dev"], "push", "-q", "origin", "main")
    git(setup["repo"], "pull", "-q", "--ff-only")
    installer = Installer()

    result = update(setup["repo"], setup["data"], installer)

    assert result["status"] == "atualizado" and installer.calls == [setup["repo"]]


@pytest.mark.parametrize("change", ["edited", "branch", "ahead"])
def test_never_touches_a_clone_with_local_work(setup, change):
    mark_installed(setup)
    commit_files(setup["dev"], {"src/vagas/x.py": "x = 4\n"})
    git(setup["dev"], "push", "-q", "origin", "main")
    repo = setup["repo"]
    if change == "edited":
        (repo / "src/vagas/x.py").write_text("x = 'local'\n", encoding="utf-8")
    elif change == "branch":
        git(repo, "checkout", "-q", "-b", "minha-branch")
    else:
        commit_files(repo, {"src/vagas/y.py": "y = 1\n"}, "local")
    head = git(repo, "rev-parse", "HEAD")
    installer = Installer()

    result = update(repo, setup["data"], installer)

    assert git(repo, "rev-parse", "HEAD") == head
    assert installer.calls == []
    assert result["status"] == "pulado"
    assert "git pull" in result["reason"]


def test_personal_files_do_not_count_as_local_changes(setup):
    """perfil.md e os outros arquivos pessoais ficam fora do git (.gitignore)."""
    mark_installed(setup)
    new = commit_files(setup["dev"], {"src/vagas/x.py": "x = 5\n"})
    git(setup["dev"], "push", "-q", "origin", "main")

    update(setup["repo"], setup["data"], Installer())

    assert git(setup["repo"], "rev-parse", "HEAD") == new


def test_offline_still_reinstalls_a_stale_copy(setup):
    git(setup["repo"], "remote", "set-url", "origin", str(setup["origin"].parent / "nao-existe.git"))
    installer = Installer()

    result = update(setup["repo"], setup["data"], installer)

    assert installer.calls == [setup["repo"]]
    assert result["status"] == "atualizado"
    assert "sem acesso" in result["warning"]


def test_failed_install_is_reported_and_retried_next_session(setup):
    mark_installed(setup)
    old = record(setup["data"])["commit"]
    commit_files(setup["dev"], {"src/vagas/x.py": "x = 6\n"})
    git(setup["dev"], "push", "-q", "origin", "main")

    result = update(setup["repo"], setup["data"], Installer(fail=True))

    assert result["status"] == "erro"
    assert "uv: falhou ao instalar" in result["reason"] and "instalador" in result["reason"]
    assert record(setup["data"])["commit"] == old
    assert update(setup["repo"], setup["data"], Installer())["status"] == "atualizado"


def test_editable_install_pulls_but_does_not_reinstall(setup):
    """Desenvolvimento (pip install -e): o código já é o do clone."""
    new = commit_files(setup["dev"], {"src/vagas/x.py": "x = 7\n"})
    git(setup["dev"], "push", "-q", "origin", "main")

    result = update(setup["repo"], setup["data"], None)

    assert git(setup["repo"], "rev-parse", "HEAD") == new
    assert result["status"] == "atualizado"


def test_not_a_git_clone_is_skipped(tmp_path):
    result = update(tmp_path / "sem-git", tmp_path, Installer())

    assert result["status"] == "pulado"


def test_concurrent_sessions_update_once(setup, monkeypatch):
    mark_installed(setup)
    commit_files(setup["dev"], {"src/vagas/x.py": "x = 8\n"})
    git(setup["dev"], "push", "-q", "origin", "main")
    started, release = threading.Event(), threading.Event()

    class Slow(Installer):
        def __call__(self, repo):
            started.set()
            release.wait(10)
            super().__call__(repo)

    slow = Slow()
    results = {}
    worker = threading.Thread(target=lambda: results.update(first=update(setup["repo"], setup["data"], slow)))
    worker.start()
    assert started.wait(10)
    results["second"] = update(setup["repo"], setup["data"], Installer())
    release.set()
    worker.join(10)

    assert results["first"]["status"] == "atualizado"
    assert results["second"]["status"] == "pulado" and "outra sessão" in results["second"]["reason"]


def test_new_example_fields_are_added_to_the_personal_files(setup):
    mark_installed(setup)
    commit_files(setup["dev"], {
        "skill/candidaturas/perfil.example.md": PERFIL.replace(
            "- Parentes na empresa: não\n",
            "- Parentes na empresa: não\n- Aceita viajar?: <...>\n  - Valores aceitos: sim ou não.\n"
            "- CNH: informar manualmente\n"),
        "skill/candidaturas/criterios-triagem.example.md": CRITERIOS.replace(
            "- Aderência mínima: 50\n", "- Aderência mínima: 50\n- Empresas ignoradas: Empresa Exemplo\n"),
    })
    git(setup["dev"], "push", "-q", "origin", "main")

    result = update(setup["repo"], setup["data"], Installer())

    perfil = (setup["repo"] / "skill/candidaturas/perfil.md").read_text(encoding="utf-8")
    assert perfil == PERFIL.replace("Fulano de Tal", "Pessoa Teste").replace(
        "- Parentes na empresa: não\n",
        "- Parentes na empresa: não\n- Aceita viajar?: <PREENCHER>\n  - Valores aceitos: sim ou não.\n"
        "- CNH: informar manualmente\n")
    criterios = (setup["repo"] / "skill/candidaturas/criterios-triagem.md").read_text(encoding="utf-8")
    assert "- Empresas ignoradas:\n" in criterios and "Empresa Exemplo" not in criterios
    assert "- Cargos alvo: Cientista de Dados" in criterios
    assert result["files_adjusted"] == {"perfil.md": ["Aceita viajar?", "CNH"],
                                        "criterios-triagem.md": ["Empresas ignoradas"]}


def test_new_section_in_the_example_is_created_in_the_personal_file(setup):
    mark_installed(setup)
    commit_files(setup["dev"], {"skill/candidaturas/perfil.example.md": PERFIL + "\n## Consentimentos\n"
                                "- Marketing e comunicações: <...>\n"})
    git(setup["dev"], "push", "-q", "origin", "main")

    update(setup["repo"], setup["data"], Installer())

    perfil = (setup["repo"] / "skill/candidaturas/perfil.md").read_text(encoding="utf-8")
    assert perfil.endswith("\n## Consentimentos\n- Marketing e comunicações: <PREENCHER>\n")


def test_field_the_user_removed_is_not_brought_back(setup):
    """Só os campos que a versão nova trouxe entram: um campo antigo apagado pelo usuário fica apagado."""
    mark_installed(setup)
    perfil = setup["repo"] / "skill/candidaturas/perfil.md"
    perfil.write_text(perfil.read_text(encoding="utf-8").replace("- Telefone: +55 (00) 00000-0000\n", ""),
                      encoding="utf-8")
    commit_files(setup["dev"], {"skill/candidaturas/perfil.example.md": PERFIL + "- Sobrenome social: <...>\n"})
    git(setup["dev"], "push", "-q", "origin", "main")

    result = update(setup["repo"], setup["data"], Installer())

    text = perfil.read_text(encoding="utf-8")
    assert "Telefone" not in text and "- Sobrenome social: <PREENCHER>" in text
    assert result["files_adjusted"] == {"perfil.md": ["Sobrenome social"]}


def test_field_already_in_the_personal_file_is_kept_as_is(setup):
    mark_installed(setup)
    perfil = setup["repo"] / "skill/candidaturas/perfil.md"
    perfil.write_text(perfil.read_text(encoding="utf-8") + "- Aceita viajar?: sim\n", encoding="utf-8")
    commit_files(setup["dev"], {"skill/candidaturas/perfil.example.md": PERFIL + "- Aceita viajar?: <...>\n"})
    git(setup["dev"], "push", "-q", "origin", "main")

    result = update(setup["repo"], setup["data"], Installer())

    assert perfil.read_text(encoding="utf-8").count("Aceita viajar?") == 1
    assert "files_adjusted" not in result


def test_actions_say_what_else_the_user_must_update(setup):
    mark_installed(setup)
    commit_files(setup["dev"], {"extension/manifest.json": '{"v": 2}\n', "skill/candidaturas/SKILL.md": "nova\n"})
    git(setup["dev"], "push", "-q", "origin", "main")

    actions = " ".join(update(setup["repo"], setup["data"], Installer())["actions"])

    assert "extensão" in actions and "recarregar" in actions
    assert "zip da Skill" in actions


def test_nothing_is_written_to_stdout(setup, capfd):
    """No stdio, o stdout do servidor é o canal do protocolo: git e uv não podem escrever nele."""
    commit_files(setup["dev"], {"src/vagas/x.py": "x = 9\n"})
    git(setup["dev"], "push", "-q", "origin", "main")
    capfd.readouterr()

    update(setup["repo"], setup["data"], Installer())

    assert capfd.readouterr().out == ""


@pytest.mark.parametrize("name, parse", [("criterios-triagem", triage.parse_criteria),
                                         ("politica-salarial", salary_policy.parse_policy)])
def test_empty_field_reads_like_a_missing_one(name, parse):
    """A atualização acrescenta campos novos vazios nos critérios e na política: vazio tem de valer o padrão."""
    text = (SKILL / f"{name}.example.md").read_text(encoding="utf-8")
    text = text.replace("<PREENCHER: os cargos do seu currículo que você busca>", "Cientista de Dados")
    items = [item for item in md_fields.parse(text) if item.parent is None]
    labels = [item.label for item in items]
    for item in items:
        if labels.count(item.label) > 1 or item.label == "Cargos alvo":
            continue
        removed = md_fields.remove_item(text, item.id)
        gone = text.count("\n") - removed.count("\n")  # em branco no lugar: os números de linha não mudam
        lines = removed.splitlines(keepends=True)
        absent = "".join(lines[:item.line] + ["\n"] * gone + lines[item.line:])
        emptied = md_fields.apply(text, {item.id: ""})
        assert parse(emptied) == parse(absent), item.label


def test_background_run_reports_the_update_once_even_across_sessions(setup):
    """O resultado fica gravado até ser contado ao usuário: a conversa que chamou get_config antes do fim da
    atualização vê "verificando", e a próxima vê o que mudou."""
    commit_files(setup["dev"], {"src/vagas/x.py": "x = 10\n"})
    git(setup["dev"], "push", "-q", "origin", "main")
    release = threading.Event()

    class Waiting(Installer):
        def __call__(self, repo):
            release.wait(10)
            super().__call__(repo)

    session = auto_update.Background(setup["repo"], setup["data"], Waiting())
    session.start()
    assert session.status() == {"status": "verificando"}
    release.set()
    session.join(10)

    next_session = auto_update.Background(setup["repo"], setup["data"], Installer())
    next_session.start()
    next_session.join(10)
    report = next_session.status()
    assert report["status"] == "atualizado" and report["to"] == git(setup["repo"], "rev-parse", "HEAD")[:7]
    assert next_session.status() is None


def test_background_run_reports_nothing_when_up_to_date(setup):
    mark_installed(setup)
    session = auto_update.Background(setup["repo"], setup["data"], Installer())
    session.start()
    session.join(10)

    assert session.status() is None


def test_repo_is_found_from_the_skill_folder(setup, monkeypatch):
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(setup["repo"] / "skill" / "candidaturas"))

    assert auto_update.find_repo() == setup["repo"]


def test_no_repo_found_means_no_update(tmp_path, monkeypatch):
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(tmp_path / "solta" / "candidaturas"))

    assert auto_update.find_repo() is None
