# mcp-vagas

Servidor MCP local para organizar candidaturas a vagas com o Claude. O Claude usa o servidor para:

- registrar candidaturas e evitar candidaturas duplicadas;
- acompanhar cada processo por etapas e pendências;
- manter um **currículo geral** estruturado, criado a partir do seu PDF e revisado por você;
- gerar **currículos personalizados** em PDF para cada vaga, sem inventar informação.

A Skill "candidaturas" (pasta `skill/candidaturas`) orquestra tudo isso: triagem, candidatura e busca de vagas.

Ele roda localmente (stdio) e guarda tudo num arquivo SQLite. Não há servidor na nuvem.

## Situação

| Funcionalidade | Situação |
|---|---|
| Registrar, deduplicar por URL, buscar por empresa normalizada, atualizar e ver histórico | pronto |
| Currículo geral: extração do PDF, rascunho YAML, revisão e aprovação | pronto |
| Currículo geral também a partir do LinkedIn (revisão contra todas as fontes), seção Volunteering e link de certificação | pronto |
| Currículos personalizados com validação anti-invenção + PDF (Typst) | pronto |
| Listagens com filtros (status, pendências, fonte, data, sem resposta há N dias) | pronto |
| Normalização de URL por plataforma (LinkedIn, Gupy, Indeed, Glassdoor) | pronto |
| Exportação CSV | pronto |
| Estimativas salariais: cache de pesquisas (90 dias) | pronto |
| Avaliação de pretensão salarial (`evaluate_salary`), com prioridade da faixa publicada na vaga | pronto |
| Busca de vagas: registro de buscas (evita repetir em 24 h) | pronto |
| Busca de vagas: aderência da vaga ao currículo (`score_job_match`) | pronto |
| Busca de vagas: status `a_aplicar` com busca de origem e aderência | pronto |
| Busca de vagas: lista de trabalho (`a_aplicar`) ordenada por aderência | pronto |
| Skill "candidaturas" (triagem, candidatura, busca de vagas) | pronto; validação real nos clientes em andamento (#19) |

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
| `VAGAS_EXPORT_DIR` | pasta dos CSVs exportados (ex.: `/mnt/c/Users/<usuário>/Documents/vagas` para abrir no Windows) | `exports` ao lado do banco |
| `VAGAS_JOB_SEARCH_MIN_HOURS` | intervalo mínimo para repetir a mesma busca de vagas, em horas | `24` |

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

O Claude Desktop roda no Windows e chama o servidor dentro do WSL pelo `wsl.exe`. O banco, o código e a cópia estável continuam no Linux.

**Instalação automática (recomendada).** No WSL, na raiz do repositório:

```bash
python3 scripts/instalar_desktop.py                   # servidor, configuração, teste e zip da Skill
python3 scripts/instalar_desktop.py --sem-skill       # só servidor e configuração
python3 scripts/instalar_desktop.py --fechar-desktop  # e fecha o Desktop no fim, para recarregar
```

O script:
- atualiza a cópia estável;
- encontra o `claude_desktop_config.json` (instalador do site ou Microsoft Store), faz backup e registra o servidor `vagas` com as mesmas variáveis do Claude Code;
- testa o servidor pelo `wsl.exe`;
- gera `Downloads\candidaturas.zip`. Ele se recusa a gerar o zip se o `perfil.md` ou o `politica-salarial.md` tiverem campos `<PREENCHER>`.

Pode ser rodado de novo a cada atualização. Ficam manuais só reabrir o Desktop e enviar o zip em Configurações → Skills.

Os passos abaixo fazem o mesmo à mão.

**1. Instale a cópia estável no WSL** (seção [Instalação para uso](#instalação-para-uso)) e confira os dados de que vai precisar. Rode no terminal do WSL:

```bash
echo "distro: $WSL_DISTRO_NAME | usuário: $USER"   # ex.: distro: Ubuntu-22.04 | usuário: newf
```

**2. Abra o arquivo de configuração do Desktop:** no Claude Desktop, vá em **Configurações → Desenvolvedor → Editar configuração**. Isso abre o `claude_desktop_config.json` certo para a sua instalação. O caminho muda conforme a versão:

| Instalação | Caminho do arquivo |
|---|---|
| instalador do site | `%APPDATA%\Claude\claude_desktop_config.json` |
| Microsoft Store | `%LOCALAPPDATA%\Claude-Data\claude_<id>\claude_desktop_config.json` (ou dentro de `%LOCALAPPDATA%\Packages\Claude_<id>\`) |

**3. Acrescente o servidor `vagas`** em `mcpServers`, mantendo o que já existe no arquivo (por exemplo, `preferences`). Troque `<distro>`, `<usuário-wsl>` e `<usuário>` pelos seus valores:

```json
{
  "mcpServers": {
    "vagas": {
      "command": "wsl.exe",
      "args": [
        "-d", "<distro>",
        "-e", "env",
        "VAGAS_DB=/home/<usuário-wsl>/.local/share/vagas/vagas.db",
        "VAGAS_RESUME_OUT=/mnt/c/Users/<usuário>/Curriculos",
        "/home/<usuário-wsl>/.local/share/vagas/venv/bin/python", "-m", "vagas.server"
      ]
    }
  }
}
```

- `-d <distro>` escolhe a distribuição do WSL. Sem ele, o `wsl.exe` usa a distribuição padrão.
- As variáveis vão pelo `env` do Linux, porque o bloco `env` do Desktop não chega ao WSL.
- Use os mesmos valores de `VAGAS_DB` e `VAGAS_RESUME_OUT` do Claude Code se quiser que os dois clientes compartilhem as mesmas candidaturas e currículos. O SQLite em modo WAL aguenta os dois abertos ao mesmo tempo.

**4. Reinicie o Claude Desktop por completo:** feche também pelo ícone da bandeja do sistema, porque fechar só a janela não recarrega a configuração. Ao abrir de novo, o servidor `vagas` deve aparecer no menu de ferramentas (conectores) da conversa.

**5. Se não aparecer**, veja o log em **Configurações → Desenvolvedor**, no servidor `vagas` (ou o arquivo `mcp-server-vagas.log` na pasta `logs` ao lado do `claude_desktop_config.json`). Para testar o mesmo comando fora do Desktop, rode no PowerShell:

```powershell
wsl.exe -d <distro> -e /home/<usuário-wsl>/.local/share/vagas/venv/bin/python -c "import vagas.server; print('ok')"
```

**6. Instale a Skill no Desktop** pelo zip descrito na seção [Skill "candidaturas"](#skill-candidaturas).

## Skill "candidaturas"

A Skill diz ao Claude quando e em que ordem usar as tools. É ela que garante, por exemplo, que a deduplicação aconteça antes de abrir um formulário e que o Claude pare antes de enviar.

| Arquivo | Conteúdo | Versionado |
|---|---|---|
| `SKILL.md` | escolha do fluxo e **triagem** (duplicata, critérios, aderência, salário) | sim |
| `candidatar.md` | candidatura: currículo personalizado, formulário, bloqueios, revisão antes do envio | sim |
| `buscar.md` | busca de vagas a partir do currículo | sim |
| `curriculo.md` | montar ou atualizar o currículo geral a partir do PDF e do LinkedIn | sim |
| `perfil.md` | dados para formulários (contato, respostas padrão) | não (use `perfil.example.md`) |
| `politica-salarial.md` | faixas CLT por modalidade, modo e multiplicador PJ | não (use `politica-salarial.example.md`) |

Quando um formulário pede um dado que ainda não está no perfil, a Skill acrescenta o campo no `perfil.md` (com a sua resposta, depois que você responde) e no `perfil.example.md` (com valor fictício). Assim o campo fica documentado para as próximas candidaturas. Dados sensíveis (CPF, RG, senhas, dados bancários) entram só como campo, com o valor "informar manualmente". O `perfil.example.md` é versionado: faça commit dele de vez em quando.

Antes de usar, crie e preencha os dois arquivos pessoais:

```bash
cd ~/projects/mcp-vagas/skill/candidaturas
cp -n perfil.example.md perfil.md
cp -n politica-salarial.example.md politica-salarial.md
```

**Claude Code:** instale com um symlink. Assim existe uma cópia só, sempre igual ao repositório:

```bash
ln -s ~/projects/mcp-vagas/skill/candidaturas ~/.claude/skills/candidaturas
```

**Claude Desktop/Cowork:** compacte a pasta, incluindo os seus `perfil.md` e `politica-salarial.md`, e envie o zip em Configurações → Skills. Isso faz uma cópia, então repita o envio a cada mudança na Skill ou nos seus dados.

```bash
cd ~/projects/mcp-vagas/skill && zip -r /mnt/c/Users/<usuário>/Downloads/candidaturas.zip candidaturas
```

A Skill descreve ações no navegador ("abra a vaga", "anexe o PDF") sem depender de uma ferramenta específica. O cliente precisa ter alguma, como o Claude in Chrome no Desktop ou um MCP de navegador no Claude Code.

## Como usar

Com a Skill instalada, basta pedir em linguagem natural ("busque vagas para mim", "candidate-se a esta vaga: <link>"). Sem ela, peça cada passo explicitamente, como nos exemplos abaixo.

### 1. Criar o currículo geral (uma vez)

Com a Skill, peça: *"Monte meu currículo geral a partir do PDF C:\Users\<usuário>\Downloads\Curriculo.pdf e do meu LinkedIn https://www.linkedin.com/in/<perfil>/"*. O Claude lê o PDF, abre o seu perfil no navegador (logado), rola cada seção de detalhes até o fim, registra as fontes, pergunta sobre divergências e monta o rascunho. Ler o LinkedIn exige uma ferramenta de navegador no cliente.

Sem a Skill, os passos são:

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
- *"Mostre minha lista de vagas a aplicar."* (ordenada pela aderência ao currículo)
- *"Exporte minhas candidaturas para uma planilha."* (`export_csv`)
- *"O que está pendente comigo?"* / *"Quais candidaturas estão sem resposta há mais de 30 dias?"* (`list_applications`)

Status possíveis: `a_aplicar` (vaga encontrada e triada, aguardando candidatura), `aplicada`, `pendente_usuario`, `rh`, `tecnica`, `gestor`, `proposta`, `recusada`, `desistiu`, `descartada`.

## Tools

| Tool | O que faz |
|---|---|
| `find_application` | procura por URL (variantes de link da mesma vaga contam como uma) e/ou empresa ("Itaú S.A." = "itau"); chamar antes de aplicar |
| `add_application` | registra vaga (`a_aplicar`, `aplicada`, `pendente_usuario` ou `descartada`), com busca de origem e aderência; duplicata devolve a existente |
| `update_application` | muda etapa, pendência, nota ou currículo vinculado |
| `list_applications` | lista candidaturas com filtros combináveis: status, pendências, fonte, data de criação e sem resposta há N dias |
| `export_csv` | exporta todas as candidaturas para um CSV novo (separador `;`, abre no Excel e no Google Sheets) |
| `get_history` | candidatura, linha do tempo e currículos vinculados |
| `extract_resume_text` | extrai o texto do PDF do currículo (caminho Windows ou WSL) |
| `save_resume_source` | registra como fonte do currículo as seções do seu LinkedIn ou o texto de um PDF (ex.: anexado no chat) |
| `save_master_draft` | grava o rascunho YAML do currículo geral, com relatório de revisão contra todas as fontes |
| `approve_master` | aprova o rascunho (só com aprovação explícita do usuário) |
| `get_master_resume` | devolve o currículo geral aprovado |
| `render_master_resume` | gera o PDF do currículo geral completo |
| `create_tailored_resume` | valida e gera um currículo personalizado |
| `score_job_match` | aderência de uma vaga ao currículo geral: nota 0–100, termos presentes e ausentes (indicativa) |
| `list_resumes` / `get_resume` | consulta currículos personalizados gerados |
| `find_salary_estimate` | consulta o cache de salários (empresa e mercado; chamar antes de pesquisar) |
| `save_salary_estimate` | registra uma pesquisa de salários (inclusive "nada encontrado") |
| `find_job_search` / `save_job_search` | consulta e registra buscas de vagas por site, consulta e local |
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
├── salary.py           # cache e avaliação de estimativas salariais
├── job_search.py       # histórico de buscas de vagas
└── templates/resume.typ
```

## Privacidade

Tudo fica na sua máquina: o banco, o YAML do currículo e os PDFs. O arquivo `skill/candidaturas/perfil.md`, com dados pessoais para formulários, está no `.gitignore`. Só o `perfil.example.md`, com dados fictícios, é versionado.
