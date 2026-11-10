import pytest

from vagas.db import connect
from vagas.repo import Repo
from vagas.server import build_server


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "vagas.db"


@pytest.fixture
def repo(db_path):
    conn = connect(db_path)
    yield Repo(conn)
    conn.close()


@pytest.fixture
def server(db_path):
    return build_server(db_path)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def clean_path_settings(monkeypatch):
    """O ambiente do desenvolvedor não pode vazar para os testes de configuração de caminhos."""
    for name in ("VAGAS_CONFIG", "VAGAS_RESUME_OUT", "VAGAS_EXPORT_DIR", "VAGAS_MASTER_RESUME",
                 "VAGAS_LOGIN_METHOD", "VAGAS_LOGIN_EMAIL", "VAGAS_MAX_OPEN_TABS", "VAGAS_SALARY_RULE",
                 "VAGAS_AUTOFILL_DOMAINS", "VAGAS_AUTO_SUBMIT", "VAGAS_AUTOFILL_PLATFORMS",
                 # arquivos pessoais: um teste nunca pode ler nem gravar os do desenvolvedor
                 "VAGAS_SKILL_DIR", "VAGAS_TRIAGE_CRITERIA", "VAGAS_SALARY_POLICY", "VAGAS_SENSITIVE_FILE"):
        monkeypatch.delenv(name, raising=False)
