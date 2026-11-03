import json
import os
import stat

import pytest

from vagas.repo import VagasError
from vagas.sensitive import ALLOWED_FIELDS, DpapiBackend, Vault, main, valid_cpf


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
