# mcp-vagas

Servidor MCP local (stdio) em Python + SQLite para registrar e deduplicar candidaturas a vagas, e a Skill "candidaturas" que o usa. Specs e tickets nas GitHub Issues (#1 servidor, #10 currículos, #11 Skill).

## Comandos

- Setup: `uv venv -p 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"`
- Testes: `.venv/bin/pytest -q`
- Inspector: `.venv/bin/mcp dev src/vagas/server.py`
- Painel de configuração: `.venv/bin/python -m vagas.panel` (página local; regra em `settings_form.py`, `settings_files.py`, `settings_resume.py` e `jobs_view.py`, HTTP em `panel.py`, página em `templates/panel/`)
- Servidor: `.venv/bin/python -m vagas.server` (banco em `$VAGAS_DB`, padrão `~/.local/share/vagas/vagas.db`; no Windows nativo, `%LOCALAPPDATA%\vagas\vagas.db`)

## Convenções

- Nunca escrever no stdout (`print` incluso) no código do servidor: no stdio o stdout é o canal do protocolo. Logging só em stderr.
- `repo.py` não importa nada de MCP; `server.py` só valida/converte e chama o repo. Regra de negócio fica no repo.
- Erros de uso: levantar `VagasError` com mensagem legível em português dizendo o que corrigir. O servidor converte em `ToolError`; outras exceções chegam ao cliente como mensagem genérica (comportamento do `mcp` 2.x).
- Valores de status, fonte e modalidade vêm de `models.py` (fonte única); tools usam os `Literal` para o enum aparecer no schema.
- Mudança de schema = nova entrada em `MIGRATIONS` (`db.py`), nunca editar uma migração já aplicada. O backup antes de migrar é automático.
- Roda no Linux, no WSL e no Windows nativo ([ADR 0003](docs/adr/0003-windows-nativo-sem-wsl.md)). Diferenças de plataforma só em `vagas.system` (`NATIVE_WINDOWS`, pasta de dados, processos); nada de `os.name`, `/mnt/c` ou `os.kill` espalhados. Nos testes, cubra os dois lados com `monkeypatch.setattr(system, "NATIVE_WINDOWS", ...)`.
- Docstrings das tools são lidas pelo modelo: explícitas sobre quando chamar e o que retorna.
- TDD: testes antes da implementação. Testar pelo comportamento externo em dois seams: `Repo` contra banco temporário e cliente MCP em memória (`mcp.Client(server)`). Nada de dados pessoais em fixtures.
- Dependências fixadas no `pyproject.toml`: `mcp`, `pydantic` (modelos com schema para as tools), `PyYAML` (currículo editável), `typst` (PDF do currículo; compilador embutido, só fontes embutidas) e `pypdf` (contagem de páginas e testes). Extra opcional `[linkedin]`: `playwright` (leitor do perfil do próprio usuário; sem técnicas de disfarce: diante de login/checkpoint, parar e pedir ação). Nada além disso sem discutir.
- PDFs de currículo vão para `$VAGAS_RESUME_OUT` (sem padrão; ex.: `/mnt/c/Users/<usuário>/Curriculos`). Template em `src/vagas/templates/resume.typ`, dados via `sys.inputs` (JSON), nunca interpolados no código Typst.
- Currículo geral: rascunho YAML em `$VAGAS_MASTER_RESUME` (padrão `curriculo.yaml` ao lado do banco); versões aprovadas ficam no banco, que é a fonte da verdade.
- Documentos do cofre (CPF, RG...) nos formulários: só pela extensão do Chrome (`extension/`) e pelo host `vagas.autofill_host`, cujo stdout é o canal de native messaging. A regra de domínio, empresa e confirmação fica em `vagas.autofill` (Python, testada); o JS só acha campos e preenche. Teste ponta a ponta em `tests/test_extension.py` (Chromium do Playwright).
- `skill/candidaturas/perfil.md` tem dados pessoais e fica fora do git; manter `perfil.example.md` com a mesma estrutura.

## Agent skills

### Issue tracker

Issues e specs ficam nas GitHub Issues deste repositório (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Labels padrão: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` e `docs/adr/` na raiz. See `docs/agents/domain.md`.
