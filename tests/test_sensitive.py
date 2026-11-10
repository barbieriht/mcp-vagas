import json
import os
import stat
import subprocess

import pytest

from vagas import sensitive, system
from vagas.repo import VagasError
from vagas.sensitive import (ALLOWED_FIELDS, DpapiBackend, NoVaultBackend, SecretServiceBackend, Vault,
                             default_backend, main, site, valid_cpf)


class FakeBackend:
    """Cifra de brincadeira, reversível, só para os testes: o valor nunca fica legível no arquivo."""

    def protect(self, data: bytes) -> bytes:
        return b"fake:" + bytes(b ^ 0x5A for b in data)

    def unprotect(self, data: bytes) -> bytes:
        assert data.startswith(b"fake:")
        return bytes(b ^ 0x5A for b in data[5:])


@pytest.fixture
def vault(tmp_path):
    return Vault(tmp_path / "cofre.json", FakeBackend())


def test_set_get_list_remove(vault, tmp_path):
    vault.set("cpf", "529.982.247-25")
    vault.set("rg", "12.345.678-9")

    assert vault.get("cpf") == "52998224725"  # só dígitos
    assert vault.list() == ["cpf", "rg"]
    raw = (tmp_path / "cofre.json").read_text()
    assert "52998224725" not in raw and "12.345.678-9" not in raw
    if os.name != "nt":  # no Windows a proteção é a ACL da pasta do usuário, não o modo do arquivo
        assert stat.S_IMODE(os.stat(tmp_path / "cofre.json").st_mode) == 0o600

    assert vault.remove("rg") is True and vault.remove("rg") is False
    assert vault.list() == ["cpf"]


def test_only_closed_list_of_fields(vault):
    for field in ("senha", "conta_bancaria", "cartao", "email"):
        with pytest.raises(VagasError, match="não pode ser guardado"):
            vault.set(field, "x")
    assert {"cpf", "rg", "cnh", "pis", "passaporte"} <= set(ALLOWED_FIELDS)


@pytest.mark.parametrize("cpf, ok", [("529.982.247-25", True), ("52998224724", False), ("111.111.111-11", False),
                                     ("123", False)])
def test_cpf_is_checked(cpf, ok):
    assert valid_cpf(cpf) is ok


def test_invalid_cpf_and_empty_values_are_refused(vault):
    with pytest.raises(VagasError, match="CPF inválido"):
        vault.set("cpf", "529.982.247-24")
    with pytest.raises(VagasError, match="vazio"):
        vault.set("rg", "  ")


def test_get_of_missing_field_is_a_clear_error(vault):
    with pytest.raises(VagasError, match="não está no cofre"):
        vault.get("cpf")


def test_cli_set_list_remove_without_echo(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VAGAS_SENSITIVE_FILE", str(tmp_path / "cofre.json"))
    answers = iter(["529.982.247-25", "529.982.247-25"])
    monkeypatch.setattr("vagas.sensitive.getpass.getpass", lambda prompt="": next(answers))

    main(["set", "cpf"], backend=FakeBackend())
    main(["list"], backend=FakeBackend())
    main(["remove", "cpf"], backend=FakeBackend())
    out = capsys.readouterr().out

    assert "cpf" in out and "52998224725" not in out and "529.982" not in out
    assert json.loads((tmp_path / "cofre.json").read_text()) == {}


def test_cli_set_requires_matching_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("VAGAS_SENSITIVE_FILE", str(tmp_path / "cofre.json"))
    answers = iter(["529.982.247-25", "529.982.247-26"])
    monkeypatch.setattr("vagas.sensitive.getpass.getpass", lambda prompt="": next(answers))

    with pytest.raises(SystemExit, match="não conferem"):
        main(["set", "cpf"], backend=FakeBackend())


@pytest.mark.skipif(os.environ.get("VAGAS_TEST_DPAPI") != "1", reason="defina VAGAS_TEST_DPAPI=1 (Windows/WSL)")
def test_real_dpapi_roundtrip():
    backend = DpapiBackend()
    secret = "valor de teste ção 123".encode()

    protected = backend.protect(secret)

    assert protected != secret and secret not in protected
    assert backend.unprotect(protected) == secret


def test_readme_lists_every_allowed_field():
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert all(f"`{field}`" in readme for field in ALLOWED_FIELDS)


@pytest.mark.parametrize("host, expected", [
    ("acme.gupy.io", "gupy.io"), ("www.linkedin.com", "linkedin.com"), ("jobs.empresa.com.br", "empresa.com.br"),
    ("empresa.com.br", "empresa.com.br"), ("careers.acme.co.uk", "acme.co.uk"), ("boards.greenhouse.io", "greenhouse.io"),
])
def test_site_is_the_registrable_domain(host, expected):
    assert site(host) == expected


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

    assert "- RG: no cofre (extensão do Chrome)\n" in after_set
    assert "- RG: informar manualmente\n" in after_remove
    assert "12.345.678-9" not in after_set
    assert "- RG: informar manualmente" in (skill / "perfil.example.md").read_text(encoding="utf-8")


class FakeSecretTool:
    """secret-tool de mentira: guarda por atributos e registra cada chamada (argv e entrada padrão)."""

    def __init__(self):
        self.items, self.calls = {}, []

    def __call__(self, command, input=None, **kwargs):
        self.calls.append((command, input))
        attributes = tuple(command[-4:])
        if command[1] == "store":
            self.items[attributes] = input
            return subprocess.CompletedProcess(command, 0, b"", b"")
        if command[1] == "lookup":
            found = self.items.get(attributes)
            return subprocess.CompletedProcess(command, 0 if found else 1, found or b"", b"")
        self.items.pop(attributes, None)  # clear
        return subprocess.CompletedProcess(command, 0, b"", b"")


@pytest.fixture
def secret_tool(monkeypatch):
    fake = FakeSecretTool()
    monkeypatch.setattr(sensitive.subprocess, "run", fake)
    return fake


def test_secret_service_keeps_the_value_in_the_keyring_and_only_a_token_in_the_file(secret_tool, tmp_path):
    vault = Vault(tmp_path / "cofre.json", SecretServiceBackend())

    vault.set("cpf", "529.982.247-25")

    assert vault.get("cpf") == "52998224725"
    assert "52998224725" not in (tmp_path / "cofre.json").read_text()
    assert all(b"52998224725" not in " ".join(command).encode() for command, _ in secret_tool.calls)
    assert secret_tool.calls[0][1] == b"52998224725"  # o valor vai pela entrada padrão, nunca na linha de comando


def test_secret_service_forgets_replaced_and_removed_values(secret_tool, tmp_path):
    vault = Vault(tmp_path / "cofre.json", SecretServiceBackend())

    vault.set("rg", "1")
    vault.set("rg", "2")
    assert len(secret_tool.items) == 1 and vault.get("rg") == "2"
    vault.remove("rg")
    assert secret_tool.items == {}


def test_secret_service_missing_value_is_a_readable_error(secret_tool, tmp_path):
    vault = Vault(tmp_path / "cofre.json", SecretServiceBackend())
    vault.set("cpf", "529.982.247-25")
    secret_tool.items.clear()

    with pytest.raises(VagasError, match="chaveiro"):
        vault.get("cpf")


def test_without_a_keyring_saving_explains_what_still_works(tmp_path):
    vault = Vault(tmp_path / "cofre.json", NoVaultBackend())

    with pytest.raises(VagasError, match="secret-tool") as error:
        vault.set("cpf", "529.982.247-25")
    assert "currículo" in str(error.value)
    assert vault.list() == [] and not (tmp_path / "cofre.json").exists()


@pytest.mark.parametrize("native_windows, wsl, has_secret_tool, expected", [
    (True, False, False, DpapiBackend),
    (False, True, False, DpapiBackend),
    (False, False, True, SecretServiceBackend),
    (False, False, False, NoVaultBackend),
])
def test_default_backend_follows_the_platform(monkeypatch, native_windows, wsl, has_secret_tool, expected):
    monkeypatch.setattr(system, "NATIVE_WINDOWS", native_windows)
    monkeypatch.setattr(system, "IN_WSL", wsl)
    monkeypatch.setattr(sensitive.shutil, "which", lambda name: "/usr/bin/secret-tool" if has_secret_tool else None)

    assert isinstance(default_backend(), expected)


@pytest.mark.skipif(os.environ.get("VAGAS_TEST_SECRET_SERVICE") != "1",
                    reason="defina VAGAS_TEST_SECRET_SERVICE=1 (Linux com chaveiro desbloqueado e secret-tool)")
def test_real_secret_service_roundtrip(tmp_path):
    vault = Vault(tmp_path / "cofre.json", SecretServiceBackend())

    vault.set("rg", "12.345.678-9 ção")
    assert vault.get("rg") == "12.345.678-9 ção"
    vault.remove("rg")
    with pytest.raises(VagasError):
        SecretServiceBackend().unprotect(b"token-que-nao-existe")
