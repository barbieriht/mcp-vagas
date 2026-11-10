# mcp-vagas

Um assistente de candidaturas a vagas para o Claude. Você conversa com o Claude, e ele:

- **busca vagas** na Gupy e no LinkedIn a partir dos cargos que você procura, descarta as que não servem e monta uma lista ordenada pela aderência ao seu currículo;
- **gera um currículo em PDF para cada vaga**, a partir do seu currículo geral, sem inventar nada (o servidor recusa números, tecnologias ou cargos que não estão no seu currículo);
- **preenche os formulários** no navegador e para antes do envio, para você conferir;
- **acompanha cada processo**: etapas, pendências, histórico e quem não respondeu.

Tudo roda no seu computador (um servidor MCP local e um banco SQLite): não há conta, nuvem nem assinatura. A configuração é feita num **painel no navegador**, sem editar arquivos.

## O que você precisa

| | |
|---|---|
| Sistema | Windows (com ou sem WSL), Linux ou macOS (macOS ainda sem testes) |
| Claude | [Claude Desktop](https://claude.ai/download) (Windows; no macOS, com o registro do MCP feito à mão) ou [Claude Code](https://code.claude.com/docs) (Windows, Linux e macOS) |
| Para preencher formulários | Google Chrome (ou Edge) com a extensão [Claude in Chrome](https://code.claude.com/docs/en/chrome) |
| Programas | [`uv`](https://docs.astral.sh/uv/) e Git. O `uv` baixa o Python 3.12 sozinho; não é preciso instalar Typst nem LaTeX |

## 1. Instalar

### Windows (sem WSL)

No PowerShell:

```powershell
winget install astral-sh.uv Git.Git          # se ainda não tiver; depois abra um PowerShell novo
git clone https://github.com/barbieriht/mcp-vagas.git $HOME\projects\mcp-vagas
cd $HOME\projects\mcp-vagas
uv run --no-project -p 3.12 scripts\instalar_desktop.py --sem-skill    # Claude Desktop e extensão do Chrome
uv run --no-project -p 3.12 scripts\instalar_claude_code.py            # opcional: Claude Code
```

### Linux ou macOS

No terminal:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # se ainda não tiver o uv (no macOS também: brew install uv)
git clone https://github.com/barbieriht/mcp-vagas.git ~/projects/mcp-vagas
cd ~/projects/mcp-vagas
python3 scripts/instalar_claude_code.py             # Claude Code, Skill, comandos e extensão do Chrome
```

No Linux, para guardar CPF e RG com segurança, instale também o chaveiro do sistema: `sudo apt install libsecret-tools` (ou o equivalente da sua distribuição).

### Windows com WSL

No terminal do WSL, com o `uv` instalado no Linux:

```bash
git clone https://github.com/barbieriht/mcp-vagas.git ~/projects/mcp-vagas
cd ~/projects/mcp-vagas
python3 scripts/instalar_desktop.py --sem-skill     # Claude Desktop (Windows) e extensão do Chrome
python3 scripts/instalar_claude_code.py             # opcional: Claude Code no WSL
```

**O que os instaladores fazem:** instalam uma cópia estável do servidor, registram o MCP "vagas" no Claude Desktop e/ou no Claude Code, instalam a Skill "candidaturas" e os comandos, e registram a extensão do Chrome. Podem ser rodados de novo a qualquer momento. O `--sem-skill` deixa o zip da Skill do Desktop para depois da configuração (passo 2).

## 2. Configurar (painel no navegador)

Abra o painel:

| Sistema | Comando |
|---|---|
| Windows (sem WSL) | `& "$env:LOCALAPPDATA\vagas\venv\Scripts\python.exe" -m vagas.panel` |
| Linux, macOS ou WSL | `~/.local/share/vagas/venv/bin/python -m vagas.panel` |

Ele abre uma página no navegador. Preencha e clique em **Salvar tudo**. Nada é gravado enquanto houver um campo com erro, e o erro aparece ao lado do campo.

| Seção | O que preencher |
|---|---|
| **Pastas e opções** | onde salvar os PDFs dos currículos (escolha uma pasta que o navegador alcance, como `Documentos\Curriculos`), o PDF do seu currículo atual e o link do seu perfil do LinkedIn |
| **Perfil para formulários** | contato, idiomas, respostas padrão (disponibilidade, contratação PJ, diversidade...) e portfólio |
| **Critérios de triagem** | cargos que você procura, senioridades, cidades e estados aceitos para vagas presenciais, empresas a evitar |
| **Política salarial** | o mínimo (e, se quiser, o máximo) por faixa: remoto, híbrido em uma cidade, internacional... |
| **Documentos do cofre** | CPF, RG e outros documentos, cifrados no seu computador. A extensão do Chrome os preenche nos formulários, e o Claude nunca vê os valores |

O painel só aceita conexões do seu computador e só abre pelo link que o comando mostra. Para voltar a ele, rode o comando de novo. Preferir editar os arquivos à mão também funciona: veja [Arquivos pessoais à mão](docs/referencia.md#arquivos-pessoais-à-mão).

**Claude Desktop:** depois de salvar, gere o zip da Skill, rodando o instalador de novo sem o `--sem-skill`. Em seguida, envie `Downloads\candidaturas.zip` em **Configurações → Skills** e reinicie o Desktop (feche também pelo ícone perto do relógio).

## 3. Montar o seu currículo geral (uma vez)

O currículo geral é a base de todos os currículos personalizados: nada fora dele entra num currículo de vaga.

1. Faça login no LinkedIn para o leitor do seu perfil (uma vez; a senha não passa pelo código):
   ```bash
   ~/.local/share/vagas/venv/bin/python -m vagas.linkedin login
   ```
   No Windows sem WSL: `& "$env:LOCALAPPDATA\vagas\venv\Scripts\python.exe" -m vagas.linkedin login`.
2. Peça ao Claude: *"Monte meu currículo geral"*. Ele usa o PDF e o LinkedIn configurados no painel e pergunta quando as fontes divergem.
3. Revise o rascunho no painel, na seção **Currículo geral**: edite o que quiser e clique em **Salvar tudo**.
4. Ainda na seção, confira o que muda e o que não aparece no PDF nem no LinkedIn, e clique em **Aprovar o rascunho**. Pela conversa também dá: diga ao Claude *"pode aprovar"*.

Para atualizar depois (emprego novo, curso novo), peça *"atualize meu currículo geral"* e aprove de novo.

## 4. Preparar o navegador (para preencher formulários)

1. Instale a extensão [Claude in Chrome](https://code.claude.com/docs/en/chrome) e entre com a mesma conta do Claude.
2. Carregue a extensão do mcp-vagas, que anexa o currículo certo e preenche os documentos do cofre e os termos de uso: abra `chrome://extensions`, ligue o **Modo do desenvolvedor**, clique em **Carregar sem compactação** e escolha a pasta:
   - Windows (com ou sem WSL): `%LOCALAPPDATA%\vagas\extensao`
   - Linux e macOS: a pasta `extension/` do repositório
3. No Windows, use o **Claude Desktop** para as candidaturas (no WSL, o Claude Code não conecta ao navegador). No Linux e no macOS, use o Claude Code com `claude --chrome`. Para o Claude Desktop no macOS, o registro do MCP é manual: veja [Instalação manual nos clientes](docs/referencia.md#instalação-manual-nos-clientes).

Na primeira vez de cada empresa, a extensão mostra o que vai preencher e pede a sua confirmação.

## 5. Usar no dia a dia

Peça em linguagem natural ou use os comandos:

| Você quer | Peça ao Claude |
|---|---|
| achar vagas novas | `/search-jobs` ou *"busque vagas para mim"* |
| ver o que vale a pena aplicar | `/work-list` (da maior para a menor aderência) |
| saber se uma vaga serve | `/screen <link da vaga>` |
| candidatar-se | `/apply <link da vaga>` ou *"candidate-se às 5 primeiras da lista"* |
| ver o que depende de você | `/pending` |
| contar uma novidade | *"passei para a entrevista técnica da Acme"* |
| levar tudo para uma planilha | `/export-applications` |

Para ver todas as vagas de uma vez, com filtros (status, site, data, aderência), contagens e o histórico de cada uma, abra o painel na aba **Vagas**. Lá também dá para mudar a etapa, anotar, descartar várias vagas de uma vez e reabrir uma descartada por engano.

O Claude nunca envia uma candidatura sem a sua confirmação; o envio automático é opcional e vem desligado (painel → Pastas e opções → Envio automático). Ele também nunca se candidata duas vezes à mesma vaga, mesmo vinda de outro site.

## Atualizar

```bash
cd ~/projects/mcp-vagas && git pull      # no Windows: cd $HOME\projects\mcp-vagas; git pull
```

Depois, rode de novo os instaladores do passo 1 e abra uma conversa nova. No Claude Desktop, reenvie o zip da Skill se ela mudou, e na extensão do Chrome clique em recarregar.

## Problemas comuns

| Problema | O que fazer |
|---|---|
| O painel diz "Acesso negado" | Abra pelo link que o comando `vagas.panel` mostra (ele tem um código de acesso). Rodar o comando de novo mostra o link |
| O instalador parou ao gerar o zip da Skill | Os arquivos pessoais ainda não estão preenchidos: preencha no painel (passo 2) e rode o instalador de novo |
| O Claude Desktop não mostra o "vagas" | Feche o Desktop por completo (inclusive pelo ícone perto do relógio) e abra de novo. Se continuar, veja o log em **Configurações → Desenvolvedor** e rode o instalador de novo |
| O LinkedIn pediu login ou verificação | Rode o comando de login do passo 3 e tente de novo |
| A extensão não preencheu nada | Recarregue a extensão em `chrome://extensions`. O ícone dela mostra **!** com o motivo quando algo falha |
| Linux: "não tem onde guardar o cofre" | Instale o `secret-tool` (`sudo apt install libsecret-tools`) com um chaveiro ativo (GNOME Keyring ou KWallet) |
| Rede corporativa: erro de certificado ao baixar | Rode os instaladores com `UV_SYSTEM_CERTS=1` (no PowerShell: `$env:UV_SYSTEM_CERTS=1`), para o `uv` usar os certificados do sistema |

## Privacidade e segurança

- Tudo fica no seu computador: banco, configuração, currículos e PDFs. Os seus arquivos pessoais ficam fora do git.
- CPF, RG e os outros documentos ficam num cofre cifrado: pela DPAPI no Windows e pelo chaveiro do sistema no Linux. Quem os preenche é a extensão do Chrome, com a sua confirmação; o Claude nunca vê os valores. No macOS ainda não há cofre, então os documentos você digita.
- O leitor do LinkedIn lê só o **seu** perfil, só quando você pede, e para diante de login ou verificação, sem técnicas de disfarce. Respeite os termos de uso de cada site; automatizar o LinkedIn é por sua conta e risco.

## Limitações

- A busca automática cobre Gupy e LinkedIn. Indeed e Glassdoor bloqueiam a leitura automática, então nesses sites a busca é feita pelo navegador.
- O foco são vagas no Brasil, e os textos da Skill estão em português. O currículo geral e os currículos personalizados são em inglês.
- macOS ainda não foi testado e não tem cofre de documentos.

## Mais detalhes

- [Referência](docs/referencia.md): configuração completa e variáveis de ambiente, instalação manual, leitor do LinkedIn, Skill, tools do MCP, funcionamento do cofre e da extensão, e desenvolvimento.
- [Decisões de arquitetura](docs/adr/) e [issues](https://github.com/barbieriht/mcp-vagas/issues).

## Contribuindo

Sugestões e correções são bem-vindas. Abra uma [issue](https://github.com/barbieriht/mcp-vagas/issues) antes de um PR grande. O projeto segue TDD e as convenções do [CLAUDE.md](CLAUDE.md); rode `.venv/bin/pytest -q` antes de abrir o PR (veja [Desenvolvimento](docs/referencia.md#desenvolvimento)). Nunca inclua dados pessoais reais em testes, exemplos ou issues.

## Licença

[GPL-3.0](LICENSE). Você pode usar, estudar, modificar e redistribuir; versões modificadas distribuídas também precisam ser GPL-3.0, com o código aberto.
