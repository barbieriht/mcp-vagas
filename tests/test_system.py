"""Diferenças entre Windows nativo e Linux/WSL ficam em vagas.system."""

import subprocess
import sys
from pathlib import Path

import pytest

from vagas import system
from vagas.db import default_db_path
from vagas.resume_extract import windows_path, wsl_path


def test_checking_a_process_does_not_stop_it():
    # No Windows, os.kill(pid, 0) encerra o processo: a checagem precisa ser só de leitura.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert system.process_alive(child.pid)
        assert child.poll() is None
    finally:
        child.kill()
        child.wait()
    assert not system.process_alive(child.pid)


def test_no_pid_is_not_alive():
    assert not system.process_alive(None)
    assert not system.process_alive(0)


def test_detached_process_options_match_the_platform(monkeypatch):
    monkeypatch.setattr(system, "NATIVE_WINDOWS", False)
    assert system.detached_process_options() == {"start_new_session": True}

    monkeypatch.setattr(system, "NATIVE_WINDOWS", True)
    flags = system.detached_process_options()["creationflags"]
    assert flags & system.DETACHED_PROCESS and flags & system.CREATE_NEW_PROCESS_GROUP


def test_windows_paths_stay_as_they_are_on_native_windows(monkeypatch):
    monkeypatch.setattr(system, "NATIVE_WINDOWS", True)

    assert wsl_path(r"C:\Users\Maria\Downloads\cv.pdf") == Path(r"C:\Users\Maria\Downloads\cv.pdf")
    assert windows_path(r"C:\Users\Maria\Curriculos\cv.pdf") == r"C:\Users\Maria\Curriculos\cv.pdf"


def test_db_defaults_to_localappdata_on_native_windows(monkeypatch, tmp_path):
    monkeypatch.delenv("VAGAS_DB", raising=False)
    monkeypatch.setattr(system, "NATIVE_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert default_db_path() == tmp_path / "vagas" / "vagas.db"


@pytest.mark.skipif(system.NATIVE_WINDOWS, reason="caminho padrão do Linux/WSL")
def test_db_defaults_to_local_share_on_linux(monkeypatch, tmp_path):
    monkeypatch.delenv("VAGAS_DB", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert default_db_path() == tmp_path / ".local/share/vagas/vagas.db"


def test_dpapi_runs_powershell_without_a_wsl_folder(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="aGk=\n", stderr="")

    from vagas import sensitive

    monkeypatch.setattr(sensitive.subprocess, "run", fake_run)
    monkeypatch.setattr(system, "NATIVE_WINDOWS", True)
    assert sensitive.DpapiBackend().protect(b"x") == b"hi"
    monkeypatch.setattr(system, "NATIVE_WINDOWS", False)
    sensitive.DpapiBackend().protect(b"x")

    assert calls[0]["cwd"] is None and calls[1]["cwd"] == "/mnt/c"
