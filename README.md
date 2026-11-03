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
| Leitor do LinkedIn em Python (Playwright): perfil inteiro por código, sem a LLM transcrever páginas | pronto |
| Currículos personalizados com validação anti-invenção + PDF (Typst) | pronto |
| Listagens com filtros (status, pendências, fonte, data, sem resposta há N dias) | pronto |
| Normalização de URL por plataforma (LinkedIn, Gupy, Indeed, Glassdoor) | pronto |
| Exportação CSV | pronto |
| Estimativas salariais: cache de pesquisas (90 dias) | pronto |
| Avaliação de pretensão salarial (`evaluate_salary`), com prioridade da faixa publicada na vaga | pronto |
| Política salarial lida pelo MCP (faixa por modalidade, local e moeda) | pronto |
| Busca de vagas por código na Gupy e no LinkedIn (`search_jobs`) e sugestão de buscas (`suggest_job_searches`) | pronto |
| Currículo e perfil por tools: diferenças na atualização (`diff_master`), campos do perfil (`add_profile_field`), seleção sugerida (`suggest_tailored_selection`) | pronto |
| Cofre local de dados sensíveis (DPAPI) e entrega condicionada para formulários | pronto |
| Triagem de uma vaga numa chamada (`triage_job`), com critérios fixos configuráveis | pronto |
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
| `VAGAS_SALARY_POLICY` | política salarial lida por `evaluate_salary` | `politica-salarial.md` ao lado do banco (o instalador cria um symlink para o da Skill) |
| `VAGAS_SENSITIVE_FILE` | cofre de dados sensíveis (CPF, RG...), cifrado pela DPAPI do Windows | `cofre.json` ao lado do banco |
| `VAGAS_SKILL_DIR` | pasta `skill/candidaturas` do repositório, onde `add_profile_field` grava os campos novos do perfil | a pasta para onde aponta o symlink da política salarial (criado pelo instalador) |
| `VAGAS_TRIAGE_CRITERIA` | critérios fixos de triagem lidos por `triage_job` | `criterios-triagem.md` ao lado do banco (o instalador cria um symlink para o da Skill) |
| `VAGAS_SALARY_TTL_DAYS` | validade do cache de salários, em dias | `90` |
| `VAGAS_EXPORT_DIR` | pasta dos CSVs exportados (ex.: `/mnt/c/Users/<usuário>/Documents/vagas` para abrir no Windows) | `exports` ao lado do banco |
| `VAGAS_LINKEDIN_MIN_MINUTES` | intervalo mínimo entre leituras do seu perfil do LinkedIn, em minutos | `60` |
| `VAGAS_LINKEDIN_HEADLESS` | `0` mostra a janela do navegador durante a leitura | `1` (invisível) |
| `VAGAS_LINKEDIN_JOBS_MIN_SECONDS` | intervalo mínimo entre leituras e buscas de vagas no LinkedIn, em segundos | `20` |
| `VAGAS_SITE_MIN_SECONDS` | intervalo mínimo entre requisições ao mesmo site de vagas, em segundos | `3` |
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
- gera `Downloads\candidaturas.zip`. Ele se recusa a gerar o zip se o `perfil.md`, o `politica-salarial.md` ou o `criterios-triagem.md` tiverem campos `<PREENCHER>`.

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

## Leitor do LinkedIn

A tool `import_linkedin_profile` lê o **seu próprio** perfil do LinkedIn por código (Playwright), em cerca de 3 minutos, e devolve os itens já no formato do currículo geral. São lidos:
- headline e About;
- experiências, incluindo cargos agrupados por empresa, modalidade e anexos;
- formação;
- certificações, com mês de emissão, ID e link real da credencial;
- voluntariado, idiomas e skills.

Ela só roda quando você pede para montar ou atualizar o currículo geral, e não altera o rascunho nem o currículo aprovado: devolve os itens e registra o texto como fonte para o relatório de revisão.

**Instalação:** os instaladores (`scripts/instalar_claude_code.py` e `scripts/instalar_desktop.py`) já incluem o leitor na cópia estável, com o extra `[linkedin]` e o navegador Chromium.

**Login (uma vez):** no terminal do WSL, rode o comando abaixo. Abre uma janela do navegador; entre na sua conta, inclusive com 2FA. A senha não passa pelo código: só a sessão fica salva, em `~/.local/share/vagas/linkedin-browser`, com acesso restrito ao seu usuário.

```bash
~/.local/share/vagas/venv/bin/python -m vagas.linkedin login
```

**Cuidados com a sua conta:**
- só o seu perfil é lido, e só quando você pede;
- há um intervalo mínimo entre leituras (`VAGAS_LINKEDIN_MIN_MINUTES`, padrão 60);
- diante de login, captcha ou verificação de segurança, o leitor **para** e pede para você rodar o login de novo. Não há nenhuma técnica de disfarce de automação.

Os Termos do LinkedIn restringem automação; o risco de usar o leitor é seu. Se ele falhar, a Skill volta à leitura pelo navegador.

**Limitação:** a interface atual do LinkedIn não mostra o total de itens de cada seção. O leitor rola até a lista parar de crescer e informa quantos itens leu, para você conferir.

**Diagnóstico:** `python -m vagas.linkedin capture <URL do perfil>` salva o HTML das páginas numa pasta local fora do repositório. Para testar o leitor contra o seu perfil, rode:

```bash
VAGAS_TEST_LINKEDIN_PROFILE=https://www.linkedin.com/in/<perfil>/ .venv/bin/pytest -q tests/test_linkedin_real.py
```

## Skill "candidaturas"

A Skill diz ao Claude quando e em que ordem usar as tools. É ela que garante, por exemplo, que a deduplicação aconteça antes de abrir um formulário e que o Claude pare antes de enviar.

| Arquivo | Conteúdo | Versionado |
|---|---|---|
| `SKILL.md` | escolha do fluxo e **triagem** (duplicata, critérios, aderência, salário) | sim |
| `candidatar.md` | candidatura: currículo personalizado, formulário, bloqueios, revisão antes do envio | sim |
| `buscar.md` | busca de vagas a partir do currículo | sim |
| `curriculo.md` | montar ou atualizar o currículo geral a partir do PDF e do LinkedIn | sim |
| `perfil.md` | dados para formulários (contato, respostas padrão) | não (use `perfil.example.md`) |
| `criterios-triagem.md` | critérios fixos da triagem (cargos alvo, empresas ignoradas, termos de vaga exclusiva PcD, locais aceitos); lidos pelo MCP em `triage_job` | não (use `criterios-triagem.example.md`) |
| `politica-salarial.md` | faixas por modalidade, local e moeda, modo e multiplicador PJ; lida pelo MCP em `evaluate_salary` | não (use `politica-salarial.example.md`) |

Quando um formulário pede um dado que ainda não está no perfil, a Skill acrescenta o campo no `perfil.md` (com a sua resposta, depois que você responde) e no `perfil.example.md` (com valor fictício). Assim o campo fica documentado para as próximas candidaturas. Dados sensíveis (CPF, RG, senhas, dados bancários) entram só como campo, com o valor "informar manualmente". O `perfil.example.md` é versionado: faça commit dele de vez em quando.

Antes de usar, crie e preencha os três arquivos pessoais:

```bash
cd ~/projects/mcp-vagas/skill/candidaturas
cp -n perfil.example.md perfil.md
cp -n politica-salarial.example.md politica-salarial.md
cp -n criterios-triagem.example.md criterios-triagem.md
```

**Claude Code:** instale a Skill, os comandos e o MCP com um comando. Ele cria symlinks em `~/.claude/skills`, então existe uma cópia só, sempre igual ao repositório:

```bash
python3 scripts/instalar_claude_code.py
```

**Claude Desktop/Cowork:** compacte a pasta, incluindo os seus `perfil.md` e `politica-salarial.md`, e envie o zip em Configurações → Skills. Isso faz uma cópia, então repita o envio a cada mudança na Skill ou nos seus dados.

```bash
cd ~/projects/mcp-vagas/skill && zip -r /mnt/c/Users/<usuário>/Downloads/candidaturas.zip candidaturas
```

A Skill descreve ações no navegador ("abra a vaga", "anexe o PDF") sem depender de uma ferramenta específica. O cliente precisa ter alguma, como o Claude in Chrome no Desktop ou um MCP de navegador no Claude Code.

## Comandos

No Claude Code, os fluxos também podem ser disparados por comandos:

| Comando | O que faz |
|---|---|
| `/generate-master-resume [PDF] [URL do LinkedIn]` | monta ou atualiza o currículo geral |
| `/search-jobs [critério]` | busca vagas e monta a lista de trabalho |
| `/apply <URL da vaga>` | candidatura completa, parando antes do envio |
| `/screen <URL da vaga>` | só a triagem, registrando `a_aplicar` ou `descartada` |
| `/work-list` | vagas a aplicar, da maior para a menor aderência |
| `/pending` | o que depende de você e o que está sem resposta há mais de 30 dias |
| `/export-applications` | exporta as candidaturas para CSV |

Cada comando só dispara o fluxo correspondente da Skill `candidaturas`, então as regras ficam num lugar só (`skill/comandos/`). O instalador do Desktop também gera um zip por comando em `Downloads\vagas-comandos`. Use-os se o Desktop oferecer comandos de Skills; senão, peça em texto.

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
| `import_linkedin_profile` | lê o seu perfil do LinkedIn por código e devolve os itens no formato do currículo geral (só a pedido) |
| `save_resume_source` | registra como fonte do currículo as seções do seu LinkedIn ou o texto de um PDF (ex.: anexado no chat) |
| `save_master_draft` | grava o rascunho YAML do currículo geral, com relatório de revisão contra todas as fontes |
| `approve_master` | aprova o rascunho (só com aprovação explícita do usuário) |
| `get_master_resume` | devolve o currículo geral aprovado |
| `render_master_resume` | gera o PDF do currículo geral completo |
| `create_tailored_resume` | valida e gera um currículo personalizado |
| `read_job_posting` | lê a página de uma vaga (Gupy, LinkedIn Jobs e sites com dados estruturados) e devolve os campos normalizados; Indeed e Glassdoor bloqueiam leitura automática |
| `triage_job` | triagem inteira de uma vaga numa chamada: duplicata, leitura, critérios fixos, aderência, registro e salário; devolve o que ainda exige julgamento ou pesquisa |
| `get_sensitive_field` | entrega um dado do cofre (CPF, RG...) para um formulário confiável de uma candidatura triada, com a sua confirmação; registra o uso sem o valor |
| `suggest_tailored_selection` | propõe a seleção inicial do currículo personalizado de uma candidatura, pelos termos da vaga |
| `add_profile_field` | acrescenta um campo de formulário ao `perfil.md` e ao `perfil.example.md` (dados sensíveis só como "informar manualmente") |
| `diff_master` | compara itens das fontes com o currículo geral aprovado: novos, alterados e ausentes, com IDs preservados |
| `score_job_match` | aderência de uma vaga ao currículo geral: nota 0–100, termos presentes e ausentes (indicativa) |
| `list_resumes` / `get_resume` | consulta currículos personalizados gerados |
| `find_salary_estimate` | consulta o cache de salários (empresa e mercado; chamar antes de pesquisar) |
| `save_salary_estimate` | registra uma pesquisa de salários (inclusive "nada encontrado") |
| `suggest_job_searches` | monta as buscas a partir dos cargos alvo, dos locais e das skills do currículo |
| `search_jobs` | executa uma busca na Gupy ou no LinkedIn, registra e marca as vagas já registradas (Indeed e Glassdoor: navegador) |
| `find_job_search` / `save_job_search` | consulta e registra buscas de vagas por site, consulta e local |
| `evaluate_salary` | decide aplicar/não aplicar/pesquisar e o valor de pretensão; lê a política salarial e escolhe a faixa pela modalidade, local e moeda da vaga |

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

### Cofre de dados sensíveis

CPF, RG e outros documentos da lista fechada podem ficar num cofre local, para o Claude preenchê-los nos formulários com a sua confirmação. Cada valor é cifrado pela DPAPI do Windows, ligada ao seu usuário: o arquivo no WSL só guarda o texto cifrado (decisão em [docs/adr/0001](docs/adr/0001-cofre-de-dados-sensiveis-com-dpapi.md)). Senhas, dados bancários e cartões nunca entram no cofre.

O cadastro é feito só por você, no terminal do WSL. O valor é digitado sem aparecer na tela e não passa pela conversa:

```bash
~/.local/share/vagas/venv/bin/python -m vagas.sensitive set cpf     # pede o valor duas vezes
~/.local/share/vagas/venv/bin/python -m vagas.sensitive list        # só os nomes dos campos
~/.local/share/vagas/venv/bin/python -m vagas.sensitive remove cpf
```

Campos aceitos: `cpf`, `rg`, `rg_orgao_emissor`, `cnh`, `pis`, `ctps`, `titulo_eleitor`, `passaporte` e `nome_mae`. O CPF tem os dígitos verificadores conferidos. O comando marca no `perfil.md` os campos que estão no cofre ("no cofre"), sem o valor.

Na candidatura, o Claude só recebe um dado do cofre (`get_sensitive_field`) quando três condições valem:
- a candidatura foi triada e está aberta (`a_aplicar` ou `pendente_usuario`);
- o formulário está em https, no domínio da vaga, na Gupy ou no LinkedIn;
- você confirmou aquele uso na revisão antes do envio.

Cada uso fica no histórico da candidatura (campo, domínio, data), sem o valor. Se algo não bater, a candidatura fica `pendente_usuario` com o motivo.
