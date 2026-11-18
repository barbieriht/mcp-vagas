"""O que muda entre Windows nativo e Linux/WSL: pasta de dados, processos em segundo plano e caminhos.

No WSL o Windows aparece em /mnt/<letra> e os caminhos C:\\... são convertidos; no Windows nativo
eles já são os caminhos locais. Os outros módulos perguntam aqui, nunca a os.name direto, para os
testes cobrirem os dois lados em qualquer sistema.
"""

import os
import platform
import shutil
from pathlib import Path
from typing import Any

NATIVE_WINDOWS = os.name == "nt"
IN_WSL = not NATIVE_WINDOWS and "microsoft" in platform.uname().release.lower()

# Flags do CreateProcess (subprocess só as expõe no Windows).
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259


def default_data_dir() -> Path:
    """%LOCALAPPDATA%\\vagas no Windows nativo; ~/.local/share/vagas no Linux e no WSL."""
    if NATIVE_WINDOWS:
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / "vagas" if base else Path.home() / "AppData" / "Local" / "vagas"
    return Path.home() / ".local/share/vagas"


def process_alive(pid: int | None) -> bool:
    """O processo existe? Só consulta: no Windows, os.kill(pid, 0) encerraria o processo."""
    if not pid:
        return False
    if os.name == "nt":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_process_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ctypes.get_last_error() == 5  # acesso negado: existe, mas é de outro usuário
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def detached_process_options() -> dict[str, Any]:
    """Argumentos do Popen para o processo seguir sozinho, sem console e sem receber o Ctrl+C do cliente."""
    if NATIVE_WINDOWS:
        return {"creationflags": DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def hidden_window_options() -> dict[str, Any]:
    """Argumentos do subprocess.run para um comando rápido (git, uv) não abrir janela de console no Windows."""
    return {"creationflags": CREATE_NO_WINDOW} if NATIVE_WINDOWS else {}


def find_executable(name: str) -> str | None:
    """git ou uv, também fora do PATH: o Claude Desktop (e o wsl.exe -e) sobe o servidor com um PATH mínimo."""
    if found := shutil.which(name):
        return found
    home = Path.home()
    if NATIVE_WINDOWS:
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        programs = Path(os.environ.get("ProgramFiles") or "C:/Program Files")
        candidates = [home / ".local" / "bin" / f"{name}.exe", home / ".cargo" / "bin" / f"{name}.exe",
                      local / "Microsoft" / "WinGet" / "Links" / f"{name}.exe", programs / "Git" / "cmd" / f"{name}.exe"]
    else:
        candidates = [home / ".local" / "bin" / name, home / ".cargo" / "bin" / name, Path("/usr/local/bin") / name,
                      Path("/opt/homebrew/bin") / name, Path("/usr/bin") / name]
    return next((str(path) for path in candidates if path.is_file()), None)
