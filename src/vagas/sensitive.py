"""Cofre local de dados sensíveis liberados pelo usuário (CPF, RG e similares).

Mecanismo: arquivo JSON na pasta de dados (VAGAS_SENSITIVE_FILE, padrão cofre.json ao lado do banco),
com cada valor cifrado pela DPAPI do Windows (escopo do usuário), chamada pelo powershell.exe, no Windows
e no WSL. No Linux, o valor fica no chaveiro do sistema (Secret Service, pelo secret-tool) e o arquivo só
guarda um identificador; sem chaveiro (e no macOS, por ora) não há cofre (ADR 0004).
- Sem texto puro: o arquivo no WSL só guarda o texto cifrado; decifrar exige a sessão do usuário no
  Windows.
- Funciona pelo Claude Code e pelo Claude Desktop (os dois rodam o servidor dentro do WSL).
- Sem senha a cada uso.
Alternativas descartadas: Secret Service (o Desktop chama o servidor pelo wsl.exe, sem sessão gráfica
para destrancar o chaveiro) e Gerenciador de Credenciais (exige P/Invoke via PowerShell, mais frágil).

Cadastro só pelo terminal, com o valor digitado sem eco (o valor nunca passa pela conversa):
    python -m vagas.sensitive set cpf | remove cpf | list
"""

import argparse
import base64
import getpass
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol

from vagas.db import default_db_path
from vagas import system
from vagas.repo import VagasError

ALLOWED_FIELDS: dict[str, str] = {
    "cpf": "CPF",
    "rg": "RG",
    "rg_orgao_emissor": "Órgão emissor do RG",
    "cnh": "CNH",
    "pis": "PIS/PASEP",
    "ctps": "CTPS",
    "titulo_eleitor": "Título de eleitor",
    "passaporte": "Passaporte",
    "nome_mae": "Nome da mãe",
}
_DIGITS_ONLY = {"cpf", "pis"}

_PS_PROTECT = ("Add-Type -AssemblyName System.Security; $d=[Convert]::FromBase64String([Console]::In.ReadToEnd().Trim());"
               "[Convert]::ToBase64String([Security.Cryptography.ProtectedData]::{op}($d,$null,'CurrentUser'))")


class Backend(Protocol):
    def protect(self, data: bytes) -> bytes: ...
    def unprotect(self, data: bytes) -> bytes: ...


def _forget(backend: Backend, protected: bytes) -> None:
    """Apaga o valor guardado fora do arquivo (chaveiro), quando o backend guarda algo lá."""
    if forget := getattr(backend, "forget", None):
        forget(protected)


class DpapiBackend:
    """DPAPI do Windows pelo powershell.exe; os dados vão pela entrada padrão, nunca pela linha de comando."""

    def _run(self, op: str, data: bytes) -> bytes:
        try:
            done = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _PS_PROTECT.format(op=op)],
                input=base64.b64encode(data).decode(), capture_output=True, text=True, timeout=60,
                cwd=None if system.NATIVE_WINDOWS else "/mnt/c",
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VagasError(f"Não foi possível usar a proteção do Windows (powershell.exe): {exc}") from exc
        if done.returncode != 0:
            raise VagasError("A proteção do Windows recusou a operação (o cofre só abre com o mesmo usuário do "
                             "Windows que cadastrou os dados).")
        return base64.b64decode(done.stdout.strip())

    def protect(self, data: bytes) -> bytes:
        return self._run("Protect", data)

    def unprotect(self, data: bytes) -> bytes:
        return self._run("Unprotect", data)


class SecretServiceBackend:
    """Linux: chaveiro do sistema (GNOME Keyring, KWallet...) pelo secret-tool.

    O valor vai pela entrada padrão, nunca pela linha de comando; o cofre.json guarda só um
    identificador aleatório. Exige o chaveiro desbloqueado na sessão (o padrão ao entrar no desktop)."""

    SERVICE = "mcp-vagas"

    def _attributes(self, token: str) -> list[str]:
        return ["service", self.SERVICE, "token", token]

    def _run(self, args: list[str], data: bytes | None = None) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(["secret-tool", *args], input=data, capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VagasError(f"Não foi possível usar o chaveiro do sistema (secret-tool): {exc}") from exc

    def protect(self, data: bytes) -> bytes:
        token = secrets.token_hex(16)
        done = self._run(["store", "--label=mcp-vagas (cofre)", *self._attributes(token)], data)
        if done.returncode != 0:
            raise VagasError("O chaveiro do sistema recusou guardar o valor (ele precisa estar desbloqueado: "
                             f"entre na sessão gráfica). Detalhe: {done.stderr.decode(errors='replace').strip()}")
        return token.encode()

    def unprotect(self, data: bytes) -> bytes:
        done = self._run(["lookup", *self._attributes(data.decode())])
        if done.returncode != 0 or not done.stdout:
            raise VagasError("O valor não está no chaveiro do sistema (apagado, ou o chaveiro está bloqueado). "
                             "Cadastre de novo pelo terminal: python -m vagas.sensitive set <campo>")
        return done.stdout

    def forget(self, data: bytes) -> None:
        self._run(["clear", *self._attributes(data.decode())])


class NoVaultBackend:
    """Sem chaveiro disponível: o cofre fica vazio e os documentos são digitados pelo usuário."""

    MESSAGE = ("Este sistema não tem onde guardar o cofre com segurança. No Linux, instale o secret-tool "
               "(pacote libsecret-tools) e use um chaveiro ativo (GNOME Keyring ou KWallet); no macOS o cofre "
               "ainda não é suportado. Sem cofre, a extensão do Chrome continua anexando o currículo e marcando "
               "os termos de uso; CPF, RG e os outros documentos você digita no formulário.")

    def protect(self, data: bytes) -> bytes:
        raise VagasError(self.MESSAGE)

    def unprotect(self, data: bytes) -> bytes:
        raise VagasError(self.MESSAGE)


def default_backend() -> Backend:
    """DPAPI no Windows e no WSL; Secret Service no Linux com secret-tool; senão, sem cofre."""
    if system.NATIVE_WINDOWS or system.IN_WSL:
        return DpapiBackend()
    if shutil.which("secret-tool"):
        return SecretServiceBackend()
    return NoVaultBackend()


def default_vault_path(db_path: Path | str | None = None) -> Path:
    if env := os.environ.get("VAGAS_SENSITIVE_FILE"):
        return Path(env)
    db = Path(db_path) if db_path is not None else default_db_path()
    return db.parent / "cofre.json"


def valid_cpf(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(d) * w for d, w in zip(digits[:size], range(size + 1, 1, -1)))
        if (total * 10 % 11) % 10 != int(digits[size]):
            return False
    return True


def check_field(field: str) -> str:
    field = (field or "").strip().lower()
    if field not in ALLOWED_FIELDS:
        raise VagasError(f"O campo {field!r} não pode ser guardado no cofre. Permitidos: {', '.join(ALLOWED_FIELDS)}. "
                         "Senhas, dados bancários e cartões ficam sempre manuais.")
    return field


class Vault:
    def __init__(self, path: Path | str, backend: Backend):
        self.path = Path(path)
        self.backend = backend

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8") or "{}")

    def _save(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.chmod(self.path, 0o600)

    def set(self, field: str, value: str) -> None:
        field = check_field(field)
        value = (value or "").strip()
        if not value:
            raise VagasError("Valor vazio: nada foi guardado.")
        if field == "cpf" and not valid_cpf(value):
            raise VagasError("CPF inválido (dígitos verificadores não conferem): nada foi guardado.")
        if field in _DIGITS_ONLY:
            value = re.sub(r"\D", "", value)
        data = self._load()
        old = data.get(field)
        data[field] = base64.b64encode(self.backend.protect(value.encode("utf-8"))).decode()
        self._save(data)
        if old:
            _forget(self.backend, base64.b64decode(old))

    def get(self, field: str) -> str:
        field = check_field(field)
        data = self._load()
        if field not in data:
            raise VagasError(f"{ALLOWED_FIELDS[field]} não está no cofre. O usuário cadastra pelo terminal: "
                             f"python -m vagas.sensitive set {field}")
        return self.backend.unprotect(base64.b64decode(data[field])).decode("utf-8")

    def remove(self, field: str) -> bool:
        field = check_field(field)
        data = self._load()
        if field not in data:
            return False
        old = data.pop(field)
        self._save(data)
        _forget(self.backend, base64.b64decode(old))
        return True

    def list(self) -> list[str]:
        return sorted(self._load())


OPEN_STATUSES = ("a_aplicar", "pendente_usuario")
_SECOND_LEVEL = {"com", "org", "net", "gov", "edu", "co", "art", "ind", "inf"}


def site(host: str) -> str:
    """Domínio registrável: acme.gupy.io -> gupy.io; jobs.empresa.com.br -> empresa.com.br."""
    parts = host.lower().strip(".").split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _mark_profile(field: str, stored: bool) -> str | None:
    """Indica no perfil.md se o campo está no cofre; devolve um aviso se a pasta da Skill não for encontrada."""
    from vagas.profile_fields import ProfileFiles, default_skill_dir

    try:
        ProfileFiles(default_skill_dir()).mark_vault(ALLOWED_FIELDS[field], stored)
    except VagasError as exc:
        return f"perfil.md não atualizado: {exc}"
    return None


def main(argv: list[str] | None = None, backend: Backend | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m vagas.sensitive", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("set", "guarda um campo (valor digitado sem eco)"), ("remove", "apaga um campo")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("field", help=", ".join(ALLOWED_FIELDS))
    sub.add_parser("list", help="mostra os campos guardados (sem os valores)")
    args = parser.parse_args(argv)
    vault = Vault(default_vault_path(), backend or default_backend())
    try:
        if args.command == "set":
            field = check_field(args.field)
            first = getpass.getpass(f"{ALLOWED_FIELDS[field]}: ")
            if getpass.getpass("Digite de novo para confirmar: ") != first:
                sys.exit("Os valores não conferem: nada foi guardado.")
            vault.set(field, first)
            print(f"{ALLOWED_FIELDS[field]} guardado no cofre ({vault.path}).")
            if warning := _mark_profile(field, stored=True):
                print(warning)
        elif args.command == "remove":
            field = check_field(args.field)
            removed = vault.remove(field)
            print(f"{field}: {'removido' if removed else 'não estava no cofre'}.")
            if removed and (warning := _mark_profile(field, stored=False)):
                print(warning)
        else:
            fields = vault.list()
            print("\n".join(f"{f} ({ALLOWED_FIELDS.get(f, f)})" for f in fields) or "Cofre vazio.")
    except VagasError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
