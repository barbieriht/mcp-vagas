# mcp-vagas

Servidor MCP local para organizar candidaturas a vagas com o Claude. O Claude usa o servidor para:

- registrar candidaturas e evitar candidaturas duplicadas;
- acompanhar cada processo por etapas e pendências;
- manter um **currículo geral** estruturado, criado a partir do seu PDF e revisado por você;
- gerar **currículos personalizados** em PDF para cada vaga, sem inventar informação.

Uma Skill de candidaturas, que vai orquestrar o fluxo completo, está em desenvolvimento.

Ele roda localmente (stdio) e guarda tudo num arquivo SQLite. Não há servidor na nuvem.

## Situação

| Funcionalidade | Situação |
|---|---|
| Registrar, deduplicar por URL, buscar por empresa normalizada, atualizar e ver histórico | pronto |
| Currículo geral: extração do PDF, rascunho YAML, revisão e aprovação | pronto |
| Currículos personalizados com validação anti-invenção + PDF (Typst) | pronto |
| Normalização de URL por plataforma, listagens, CSV | em andamento (#3, #7, #8) |
| Estimativas salariais: cache de pesquisas (90 dias) | pronto |
| Avaliação de pretensão salarial (`evaluate_salary`), com prioridade da faixa publicada na vaga | pronto |
| Busca de vagas a partir do currículo, lista `a_aplicar` | planejado (#35) |
| Skill "candidaturas" (fluxo completo) | planejado (#11) |

Specs e tickets: [issues do repositório](https://github.com/barbieriht/mcp-vagas/issues).

## Requisitos

- Linux ou WSL2, com Python 3.12.
- [`uv`](https://docs.astral.sh/uv/).
- Claude Code e/ou Claude Desktop.

Não é preciso instalar Typst nem LaTeX: o compilador Typst vem embutido no pacote `typst`.

## Instalação para uso

Instale uma cópia estável, separada da pasta de desenvolvimento:

```bash
uv venv -p 3.12 ~/.local/share/vagas/venv
uv pip install --python ~/.local/share/vagas/venv/bin/python ~/projects/mcp-vagas
```

Para atualizar depois de mudanças no repositório, rode o comando abaixo e abra uma sessão nova do Claude:

```bash
uv pip install --reinstall-package vagas --python ~/.local/share/vagas/venv/bin/python ~/projects/mcp-vagas
```

### Configuração

| Variável | Para que serve | Padrão |
|---|---|---|
| `VAGAS_DB` | arquivo do banco SQLite | `~/.local/share/vagas/vagas.db` |
| `VAGAS_MASTER_RESUME` | arquivo YAML editável do currículo geral | `curriculo.yaml` ao lado do banco |
| `VAGAS_RESUME_OUT` | pasta onde os PDFs de currículo são gerados | nenhum (obrigatória para gerar PDF) |
| `VAGAS_SALARY_TTL_DAYS` | validade do cache de salários, em dias | `90` |

Mantenha o banco no filesystem do WSL (`~/...`), nunca em `/mnt/c`, que é lento e sujeito a locks. Já a pasta dos PDFs pode ficar no Windows, por exemplo `/mnt/c/Users/<usuário>/Curriculos`, para anexá-los no navegador.

### Claude Code

```bash
claude mcp add vagas --scope user \
  -e VAGAS_DB=$HOME/.local/share/vagas/vagas.db \
  -e VAGAS_RESUME_OUT=/mnt/c/Users/<usuário>/Curriculos \
  -- $HOME/.local/share/vagas/venv/bin/python -m vagas.server
```

Confira com `claude mcp list`.

### Claude Desktop (Windows)

> Ainda não validado ponta a ponta (#9).

No `claude_desktop_config.json`, a configuração abaixo roda o servidor dentro do WSL. As variáveis vão pelo `env` do Linux, porque o `env` do Desktop não chega ao WSL.

```json
{
  "mcpServers": {
    "vagas": {
      "command": "wsl.exe",
      "args": [
        "-e", "env",
        "VAGAS_DB=/home/<usuário-wsl>/.local/share/vagas/vagas.db",
        "VAGAS_RESUME_OUT=/mnt/c/Users/<usuário>/Curriculos",
        "/home/<usuário-wsl>/.local/share/vagas/venv/bin/python", "-m", "vagas.server"
      ]
    }
  }
}
```

Os dois clientes podem usar o mesmo banco ao mesmo tempo, porque o SQLite roda em modo WAL.

## Como usar

O Claude escolhe as tools sozinho a partir do pedido. Até a Skill ficar pronta, peça cada passo explicitamente.

### 1. Criar o currículo geral (uma vez)

1. *"Extraia meu currículo de C:\Users\<usuário>\Downloads\Curriculo.pdf e monte o currículo geral."*
   - O Claude chama `extract_resume_text` e depois `save_master_draft`.
   - O rascunho é gravado em `curriculo.yaml`, junto com um **relatório de revisão**: números, datas, nomes e termos do rascunho que não foram encontrados no PDF.
2. Revise e edite o YAML. Cada experiência tem parágrafos com IDs, como `exp-empresa-cargo-p1`.
3. *"Revisei, pode aprovar."* O Claude chama `approve_master`, que valida o arquivo e registra uma versão.

O currículo geral aprovado é a única fonte da verdade. Para mudá-lo, edite o YAML e aprove de novo.

### 2. Gerar um currículo personalizado para uma vaga

*"Gere um currículo para esta vaga: <link ou descrição>."*

O Claude chama `create_tailored_resume` com a seleção de itens e parágrafos do currículo geral. Ele pode reescrever parágrafos como bullets. Antes de gerar o PDF, o MCP **rejeita**:

- números que não estão no parágrafo de origem (inclusive "3+ years");
- tecnologias ou nomes próprios que não aparecem no currículo geral;
- IDs inexistentes ou parágrafos de outra experiência;
- qualquer tentativa de alterar empresa, cargo, datas, formação, certificações ou idiomas.

O PDF sai em `VAGAS_RESUME_OUT`, com nome no formato `Nome_Sobrenome_Resume_Empresa.pdf`. Um arquivo existente nunca é sobrescrito.

### 3. Registrar e acompanhar candidaturas

- *"Antes de aplicar, veja se já me candidatei a <url> ou a outra vaga da empresa."* (`find_application`)
- *"Registre a candidatura no Nubank, Data Scientist, pelo LinkedIn, com o currículo que você gerou."* (`add_application` com `resume_id`)
- *"Ficou faltando o CPF; registre como pendente."* (status `pendente_usuario` com `pending`)
- *"Passei para a entrevista técnica."* / *"Mostre o histórico da candidatura 3."* (`update_application`, `get_history`)

Status possíveis: `aplicada`, `pendente_usuario`, `rh`, `tecnica`, `gestor`, `proposta`, `recusada`, `desistiu`, `descartada`.

## Tools

| Tool | O que faz |
|---|---|
| `find_application` | procura por URL e/ou empresa ("Itaú S.A." = "itau"); chamar antes de aplicar |
| `add_application` | registra candidatura (`aplicada`, `pendente_usuario` ou `descartada`); duplicata devolve a existente |
| `update_application` | muda etapa, pendência, nota ou currículo vinculado |
| `get_history` | candidatura, linha do tempo e currículos vinculados |
| `extract_resume_text` | extrai o texto do PDF do currículo (caminho Windows ou WSL) |
| `save_master_draft` | grava o rascunho YAML do currículo geral, com relatório de revisão |
| `approve_master` | aprova o rascunho (só com aprovação explícita do usuário) |
| `get_master_resume` | devolve o currículo geral aprovado |
| `render_master_resume` | gera o PDF do currículo geral completo |
| `create_tailored_resume` | valida e gera um currículo personalizado |
| `list_resumes` / `get_resume` | consulta currículos personalizados gerados |
| `find_salary_estimate` | consulta o cache de salários (empresa e mercado; chamar antes de pesquisar) |
| `save_salary_estimate` | registra uma pesquisa de salários (inclusive "nada encontrado") |
| `evaluate_salary` | decide aplicar/não aplicar/pesquisar e o valor de pretensão, pela política do `perfil.md` |

## Desenvolvimento

```bash
cd ~/projects/mcp-vagas
uv venv -p 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/pytest -q
```

- **Inspector:** `.venv/bin/mcp dev src/vagas/server.py` abre o MCP Inspector no navegador.
- **Testes com o seu currículo real:** são opcionais e o PDF nunca é copiado para o repositório. Rode com `VAGAS_TEST_RESUME_PDF=/mnt/c/.../Curriculo.pdf .venv/bin/pytest -q`.
- **Convenções** (stdout proibido, TDD, migrações, dependências): veja o [CLAUDE.md](CLAUDE.md).

```text
src/vagas/
├── server.py           # tools MCP (finas)
├── repo.py             # candidaturas
├── db.py               # conexão, migrações com backup automático
├── models.py           # enums (status, fonte, modalidade)
├── normalize.py        # empresa e URL
├── resume_model.py     # schema do currículo geral
├── resume_repo.py      # rascunho, aprovação, currículos gerados
├── resume_extract.py   # extração do PDF e relatório de revisão
├── resume_tailor.py    # seleção e resolução do currículo personalizado
├── resume_validate.py  # verificação de números e termos
├── resume_render.py    # PDF com Typst
├── salary.py           # cache de estimativas salariais
└── templates/resume.typ
```

## Privacidade

Tudo fica na sua máquina: o banco, o YAML do currículo e os PDFs. O arquivo `skill/candidaturas/perfil.md`, com dados pessoais para formulários, está no `.gitignore`. Só o `perfil.example.md`, com dados fictícios, é versionado.
