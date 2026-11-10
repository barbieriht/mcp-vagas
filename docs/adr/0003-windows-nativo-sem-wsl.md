# Windows nativo, sem WSL

O servidor, o host da extensão e os instaladores também rodam no Windows sem WSL (#169). O Claude Desktop é nativo no Windows, e exigir o WSL era a etapa mais difícil da instalação para quem não é dev. As diferenças de plataforma ficam em `vagas.system` (`NATIVE_WINDOWS`, pasta de dados, processos em segundo plano), e os outros módulos perguntam lá. Assim os testes cobrem os dois lados em qualquer sistema.

- **Pasta de dados:** `%LOCALAPPDATA%\vagas` no Windows nativo e `~/.local/share/vagas` no Linux e no WSL. Caminhos `C:\...` ficam como estão no Windows nativo; no WSL continuam virando `/mnt/c/...`.
- **Skill sem symlinks:** no Windows, symlink exige administrador ou modo de desenvolvedor. Os instaladores registram `VAGAS_SKILL_DIR`, `VAGAS_SALARY_POLICY` e `VAGAS_TRIAGE_CRITERIA` apontando para a pasta da Skill, no lugar dos symlinks ao lado do banco. Os links em `~/.claude/skills` viram junções, que não exigem privilégio.
- **Processos:** no Windows, `os.kill(pid, 0)` encerra o processo em vez de só testar se ele existe. A checagem da busca em lote usa `OpenProcess`/`GetExitCodeProcess`, e o processo sobe com `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` no lugar de `start_new_session`.
- **Cofre:** a mesma DPAPI da [ADR 0001](0001-cofre-de-dados-sensiveis-com-dpapi.md), pelo `powershell.exe` sem a pasta `/mnt/c`. Um cofre criado no WSL abre no Windows nativo com o mesmo usuário do Windows.

## Alternativas consideradas

- **conda ou instalador próprio:** o `uv` roda nativo no Windows, baixa o Python 3.12 e já é o que o projeto usa. `uv run --no-project` roda os instaladores sem Python instalado à parte.
- **Exigir o modo de desenvolvedor para usar symlinks:** é mais um passo manual, e as variáveis de ambiente já existiam.
- **Chamar a DPAPI por `ctypes`:** dispensaria o PowerShell, mas mudaria o formato do cofre entre WSL e Windows nativo. Com o mesmo PowerShell, o arquivo é compatível nos dois.

## Consequências

- A suíte roda nos dois sistemas. No Windows, o teste ponta a ponta da extensão registra o host em chaves do Chromium e do Chrome for Testing (nunca na do Google Chrome do usuário) e as apaga no fim.
- Quem migra do WSL para o Windows nativo começa com um banco novo em `%LOCALAPPDATA%\vagas`, a não ser que aponte `VAGAS_DB` para o antigo.
