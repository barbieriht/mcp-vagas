import pytest
from mcp import Client

from test_sensitive import FakeBackend
from vagas.db import connect
from vagas.repo import Repo, VagasError
from vagas.sensitive import SensitiveAccess, Vault, main, site
from vagas.server import build_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def vault(tmp_path):
    v = Vault(tmp_path / "cofre.json", FakeBackend())
    v.set("cpf", "529.982.247-25")
    return v


@pytest.fixture
def repo(db_path):
    conn = connect(db_path)
    yield Repo(conn)
    conn.close()


def app(repo, url="https://acme.gupy.io/jobs/1", status="a_aplicar", **extra):
    fields = {"pending": "CPF"} if status == "pendente_usuario" else {}
    return repo.add_application(company="Acme", role="DS", source="gupy", url=url, status=status,
                                **fields, **extra)["application"]


@pytest.mark.parametrize("host, expected", [
    ("acme.gupy.io", "gupy.io"), ("www.linkedin.com", "linkedin.com"), ("jobs.empresa.com.br", "empresa.com.br"),
    ("empresa.com.br", "empresa.com.br"), ("careers.acme.co.uk", "acme.co.uk"), ("boards.greenhouse.io", "greenhouse.io"),
])
def test_site_is_the_registrable_domain(host, expected):
    assert site(host) == expected


@pytest.mark.parametrize("job_url, form_url", [
    ("https://acme.gupy.io/jobs/1", "https://acme.gupy.io/candidates/jobs/1/apply"),
    ("https://acme.gupy.io/jobs/1", "https://login.gupy.io/candidates/signin"),
    ("https://www.linkedin.com/jobs/view/1/", "https://www.linkedin.com/jobs/view/1/apply"),
    ("https://careers.empresa.com.br/vaga/1", "https://jobs.empresa.com.br/apply/1"),
    ("https://www.linkedin.com/jobs/view/1/", "https://empresa.gupy.io/jobs/9/apply"),  # Gupy vale para qualquer vaga
])
def test_value_is_delivered_for_trusted_forms_and_use_is_logged(repo, vault, job_url, form_url):
    application = app(repo, url=job_url)

    result = SensitiveAccess(repo, vault).get_sensitive_field("cpf", application["id"], form_url)

    assert result["value"] == "52998224725" and result["field"] == "cpf"
    notes = [e["note"] for e in repo.events(application["id"]) if e.get("note")]
    assert len(notes) == 1 and "CPF" in notes[0] and result["domain"] in notes[0]
    assert "52998224725" not in notes[0]


@pytest.mark.parametrize("form_url, message", [
    ("https://acme-vagas.com/form", "domínio"),
    ("https://acme.gupy.io.golpe.com/form", "domínio"),
    ("http://acme.gupy.io/form", "https"),
    ("acme.gupy.io/form", "https"),
])
def test_untrusted_forms_are_refused(repo, vault, form_url, message):
    application = app(repo)

    with pytest.raises(VagasError, match=message):
        SensitiveAccess(repo, vault).get_sensitive_field("cpf", application["id"], form_url)
    assert not [e for e in repo.events(application["id"]) if e.get("note")]


@pytest.mark.parametrize("status", ["aplicada", "descartada"])
def test_only_triaged_open_applications(repo, vault, status):
    extra = {"discard_reason": "x"} if status == "descartada" else {}
    application = app(repo, status=status, **extra)

    with pytest.raises(VagasError, match="a_aplicar"):
        SensitiveAccess(repo, vault).get_sensitive_field("cpf", application["id"], "https://acme.gupy.io/x")


def test_pending_application_is_accepted(repo, vault):
    application = app(repo, status="pendente_usuario")

    assert SensitiveAccess(repo, vault).get_sensitive_field("cpf", application["id"], "https://acme.gupy.io/x")


def test_missing_application_field_or_value(repo, vault):
    access = SensitiveAccess(repo, vault)
    application = app(repo)
    with pytest.raises(VagasError, match="não existe"):
        access.get_sensitive_field("cpf", 999, "https://acme.gupy.io/x")
    with pytest.raises(VagasError, match="não pode ser guardado"):
        access.get_sensitive_field("senha", application["id"], "https://acme.gupy.io/x")
    with pytest.raises(VagasError, match="não está no cofre"):
        access.get_sensitive_field("rg", application["id"], "https://acme.gupy.io/x")


async def test_tool_via_mcp(db_path, vault):
    server = build_server(db_path, vault=vault)
    async with Client(server) as client:
        created = (await client.call_tool("add_application", {
            "company": "Acme", "role": "DS", "source": "gupy", "url": "https://acme.gupy.io/jobs/1",
            "status": "a_aplicar"})).structured_content["application"]
        tools = {t.name: t for t in (await client.list_tools()).tools}
        ok = (await client.call_tool("get_sensitive_field", {
            "field": "cpf", "application_id": created["id"], "form_url": "https://acme.gupy.io/apply"})).structured_content
        bad = await client.call_tool("get_sensitive_field", {
            "field": "cpf", "application_id": created["id"], "form_url": "https://outro.com/apply"})

    description = tools["get_sensitive_field"].description
    assert ok["value"] == "52998224725"
    assert bad.is_error and "domínio" in bad.content[0].text
    assert "confirm" in description and "pendente_usuario" in description


def test_cli_marks_the_profile(tmp_path, monkeypatch):
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "perfil.md").write_text("# Perfil\n\n## Outros campos de formulário\n- CPF: informar manualmente\n",
                                     encoding="utf-8")
    (skill / "perfil.example.md").write_text("# Perfil\n\n## Outros campos de formulário\n- CPF: informar manualmente\n",
                                             encoding="utf-8")
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(skill))
    monkeypatch.setenv("VAGAS_SENSITIVE_FILE", str(tmp_path / "cofre.json"))
    answers = iter(["12.345.678-9", "12.345.678-9"])
    monkeypatch.setattr("vagas.sensitive.getpass.getpass", lambda prompt="": next(answers))

    main(["set", "rg"], backend=FakeBackend())
    after_set = (skill / "perfil.md").read_text(encoding="utf-8")
    main(["remove", "rg"], backend=FakeBackend())
    after_remove = (skill / "perfil.md").read_text(encoding="utf-8")

    assert "- RG: no cofre (get_sensitive_field)\n" in after_set
    assert "- RG: informar manualmente\n" in after_remove
    assert "12.345.678-9" not in after_set
    assert "- RG: informar manualmente" in (skill / "perfil.example.md").read_text(encoding="utf-8")
