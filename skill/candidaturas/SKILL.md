---
name: candidaturas
description: Vagas de emprego do Thiago com o MCP "vagas". Use para buscar vagas, triar ou avaliar uma vaga, candidatar-se, preencher formulários de candidatura, responder perguntas de processos seletivos (LinkedIn, Gupy, Indeed, Glassdoor, sites de empresas) ou montar e atualizar o currículo geral a partir do PDF e do LinkedIn.
---

# Candidaturas

Fontes da verdade:
- **Currículo geral aprovado** (`get_master_resume`) para experiência, formação, trabalho voluntário, certificações, skills e idiomas.
- [politica-salarial.md](politica-salarial.md) para a política salarial. O MCP a lê sozinho em `evaluate_salary`.
- [criterios-triagem.md](criterios-triagem.md) para os critérios fixos da triagem. O MCP os lê sozinho em `triage_job`.
- [perfil.md](perfil.md) para os dados de formulário. Ele é carregado só na hora de preencher.
- **MCP "vagas"** como registro de tudo o que acontece com cada vaga.

## Vagas citadas viram link

Sempre que citar uma vaga ao Thiago (resumo, tabela, lista de trabalho, pendência, duplicata), escreva o nome dela como link Markdown para a página da vaga: `[Cargo — Empresa](url)`, com o `url` que as tools retornam. Assim ele abre a vaga clicando no nome. Não repita a URL crua ao lado. Se a vaga não tiver `url`, escreva o nome sem link.

## Primeiro uso

Antes de qualquer fluxo, e sempre que uma tool reclamar de pasta não configurada, chame `get_config`.
Se `needs_setup` trouxer chaves, o MCP ainda não sabe onde guardar aqueles arquivos. Pergunte ao Thiago, uma chave por vez:

- `resume_out`: pasta dos PDFs de currículo. Sugira a primeira de `suggestions` (no WSL, costuma ser `Documents` do Windows, para anexar o PDF no navegador) e diga que ele pode escolher outra.
- `export_dir`: pasta dos CSVs exportados. Sugira uma de `suggestions` ou aceite o `default`.
- `master_resume`: arquivo YAML do currículo geral. Sugira o `default` (fica no WSL, fora do `/mnt/c`, que é lento).
- `login_method`: como entrar nos sites de vagas, `linkedin` ou `google` (aceite "gmail" como google).
- `login_email`: só aparece em `needs_setup` quando o login é `google`. Pergunte qual e-mail da conta Google usar (pode ser diferente do e-mail do `perfil.md`).

Grave cada resposta com `set_config` (sem `value` para aceitar o `default`) e leia o `warnings` do retorno: se uma variável de ambiente sobrepõe o valor, avise o Thiago. Não escolha a pasta dos currículos sozinho. `max_open_tabs` (limite de abas de candidatura abertas) tem padrão e não é perguntado: só mude se o Thiago pedir. Depois de configurado, `get_config` não pergunta de novo; para mudar depois, o Thiago pede e você chama `set_config`.

## Escolha o fluxo

- O Thiago traz uma vaga e quer se candidatar: siga [candidatar.md](candidatar.md).
- Ele pede para buscar vagas: siga [buscar.md](buscar.md).
- Ele só quer saber se uma vaga vale a pena: faça a **triagem** abaixo e informe o resultado.
- Ele pediu para montar ou atualizar o currículo geral (pelo PDF, pelo LinkedIn ou pelos dois): siga [curriculo.md](curriculo.md). Esse fluxo roda só a pedido dele.

## Várias vagas

Quando o Thiago pede para se candidatar a várias vagas, trate uma de cada vez e não espere por ele entre elas. Sua tarefa em cada vaga termina no envio da candidatura (ou num bloqueio); testes de perfil ou de habilidade são dele.
- Formulário completo: não pare para revisar cada formulário. Deixe a aba aberta, registre `pendente_usuario` com `pending` "pronta para envio…" e siga para a próxima; o envio sai na revisão do lote ([candidatar.md](candidatar.md#abas-abertas)).
- `aplicada`: registre, anote em `pending` qualquer teste ou etapa pedida depois do envio e siga para a próxima vaga.
- `pendente_usuario`: algo bloqueou o envio (por exemplo, o navegador não anexou o PDF). Registre o `pending`, deixe a aba aberta, respeitando o limite de abas de [candidatar.md](candidatar.md#abas-abertas), e siga para a próxima.
- `encerrada` e `descartada`: informe o motivo no resumo e siga para a próxima.

Só pause o lote em três casos: as abas abertas chegaram a `max_open_tabs` (padrão 12), as vagas do pedido acabaram, ou a causa afeta todas as vagas (por exemplo, o login pedido pelo site não funciona ou a sessão expirou). Formulário pronto, campo que falta ou anexo que não subiu não são motivo para pausar. Ao pausar e ao final, entregue um resumo único com: candidaturas feitas; **pendências do Thiago** (cada teste ou etapa com link e prazo, e cada `pendente_usuario` com o que falta e, quando houver PDF a anexar, o currículo certo daquela vaga: nome do arquivo e `windows_path`); vagas descartadas ou encerradas. O comando `/pending` lista essas pendências depois.

## Triagem

Toda vaga passa pela triagem antes de qualquer outra ação. Ela termina com a vaga registrada no MCP como `a_aplicar` ou `descartada`, ou identificada como já registrada.

1. **Triagem automática.** Chame `triage_job` com a URL e, se a vaga veio de uma busca, o `search_id`. Ela verifica duplicata, lê a vaga, aplica os critérios fixos de [criterios-triagem.md](criterios-triagem.md), calcula a aderência, registra a vaga e avalia o salário pela política. Não refaça essas etapas.
2. **Resultado.** Siga pelo `decision`:
   - `ja_registrada`: veja o status da `application`. Em `pendente_usuario`, retome pelo que está em `pending`. Em `a_aplicar`, siga para o próximo passo do fluxo. Em qualquer outro status, informe o status ao Thiago e encerre a vaga.
   - `possivel_duplicata`: nada foi registrado. Mostre ao Thiago as vagas em `matches` e pergunte se é a mesma vaga. Se não for, chame `triage_job` de novo com `not_duplicate` igual a true.
   - `encerrada`: o LinkedIn avisa que a vaga não aceita mais candidaturas (`closed`). Nada foi registrado. Informe ao Thiago e encerre a vaga.
   - `descartada`: informe o motivo (`discard_reason`) e encerre a vaga.
   - `a_aplicar`: resolva cada item de `needs`. O `detail` de cada item diz o que fazer.
3. **Julgamento dos `needs`.**
   - `afirmativa`: a vaga se diz afirmativa sem citar um grupo reconhecido. Leia a descrição; se for para um grupo fora de "Vagas afirmativas que posso disputar" em [criterios-triagem.md](criterios-triagem.md), descarte com `update_application` (`descartada` e `discard_reason`).
   - `cargo`: o título não foi reconhecido. Confirme a família pela descrição: Data Scientist (júnior a sênior) e AI/ML Engineer entram; analista ou engenheiro de dados, só com boa aderência ao currículo.
   - `local`: híbrido com deslocamento viável a partir de São Carlos é aceito.
   - `pesquisa_salarial`: pesquise salários na web com as consultas de `queries`, na ordem: primeiro o cargo da vaga com a empresa e a cidade, depois a empresa no Levels.fyi, por último o mercado. Registre com `save_salary_estimate`, uma linha por dado, com fonte e URL:
     - dado da própria empresa: com `company`. Remuneração total anual (Levels.fyi) vai com período `ano`;
     - empresa pesquisada sem dados do cargo: registre com `company` e a lista de pontos vazia, para a busca não se repetir;
     - dado de mercado: sem `company`. Se não encontrar nada, registre a pesquisa com a lista de pontos vazia.

     Fontes aceitas: Glassdoor, LinkedIn Salary, Indeed Salários, Levels.fyi (dados da empresa), guias salariais de recrutadoras (Robert Half, Michael Page, Hays) e a própria vaga. Não registre matérias jornalísticas, blogs nem posts que repetem números ("carreira que paga R$ 22 mil"): eles puxam a mediana para cima. Registre como a fonte publica: média em `avg_value` quando houver, faixa em `min_value`/`max_value`. Se encontrar no cache uma pesquisa com fonte fora dessa lista, descarte-a com `discard_salary_estimate` e pesquise de novo.

     Use só dados do mesmo cargo: salário de outro cargo da empresa (por exemplo, engenheiro de software genérico) não serve. Depois chame `evaluate_salary` com o `application_id`, o regime (`contract`) e a moeda da vaga. Se o resultado for `nao_aplicar`, chame `update_application` com status `descartada` e `discard_reason` igual ao `reason`.
   - `modalidade`, `senioridade`, `aderencia` e `salario`: siga o `detail`.
   - **Experiência exigida:** vagas que pedem 5 anos ou mais seguem quando a aderência técnica é alta.
   - **Prioridade:** vagas júnior em empresas grandes ou conhecidas merecem atenção extra.

   Se o julgamento reprovar a vaga, chame `update_application` com status `descartada` e `discard_reason` explicando o critério.
4. **Resumo.** Informe ao Thiago a decisão, os motivos (`reasons`), o enquadramento de nível (`level`: os anos dele contra a faixa do nível da vaga; fora do enquadramento não impede a candidatura quando o nível está entre as "Senioridades buscadas"), a aderência e, se houver, o valor de mercado (`median`) e a pretensão (`value_to_inform`, com a regra em `rule`; `capped` = limitada ao teto da política). Termos ausentes com relacionados (`related`) são diferença de ferramenta, não de competência: mostre-os assim ("XGBoost: você tem LightGBM").

### Triagem manual (plano B)

Use só quando `triage_job` der erro (o site bloqueou a leitura, a página não tem dados estruturados ou falta um arquivo de critérios). Leia a vaga pelo navegador e faça as etapas à mão:

1. **Duplicata.** Chame `find_application` com a URL e a empresa.
   - `pendente_usuario`: retome a candidatura pelo que está em `pending`.
   - `a_aplicar`: a vaga já foi triada. Siga para o próximo passo do fluxo com esse registro.
   - Qualquer outro status: informe o status atual ao Thiago e encerre a vaga.
   - Mesma empresa com outra vaga de cargo e senioridade parecidos, possivelmente de outra plataforma: pergunte ao Thiago se é a mesma vaga.
2. **Leitura da vaga.** Registre cargo, senioridade, modalidade, local, regime (CLT, PJ ou desconhecido), moeda, faixa salarial publicada (se houver) e a descrição completa.
3. **Critérios.** Aplique os de [criterios-triagem.md](criterios-triagem.md) (cargos alvo, empresas ignoradas, vagas afirmativas ou exclusivas PcD fora dos grupos que ele pode disputar, locais aceitos) e os julgamentos do passo 3 acima.

   Se a vaga reprovar aqui, chame `add_application` com status `descartada` e `discard_reason` explicando o critério, e encerre a vaga.
4. **Aderência.** Chame `score_job_match` com a descrição. Os termos em `match_terms` (`matched`) guiam o currículo personalizado, e os de `missing` mostram lacunas. A nota é indicativa e complementa os critérios.
5. **Registro.** Chame `add_application` com status `a_aplicar`, a descrição, `match_score`, `match_terms` e, se a vaga veio de uma busca, `search_id`.
6. **Salário.** Mapeie o cargo para `role_key` (Data Scientist: `data_scientist`; ML Engineer: `ml_engineer`; AI Engineer: `ai_engineer`; engenheiro de dados: `data_engineer`; analista de dados: `data_analyst`) e a senioridade para o enum do MCP.
   1. Se a vaga publica faixa salarial: chame `save_salary_estimate` com source "vaga", a empresa e o `application_id`.
   2. Senão, chame `find_salary_estimate` com a empresa. Para o escopo que não estiver fresco (`fresh_company`, `fresh_market`), pesquise salários na web (Glassdoor, LinkedIn Salary, guias salariais) e registre com `save_salary_estimate`, uma linha por dado, com fonte e URL. Se não encontrar nada, registre a pesquisa com a lista de pontos vazia.
   3. Chame `evaluate_salary` com o `application_id`, o regime (`contract`) e a moeda da vaga. O MCP lê a política salarial e escolhe a faixa pela modalidade e pelo local da candidatura; não passe valores da política. Se o local não estiver coberto pela política, o erro diz isso: confira o local com o Thiago.
      - `pesquisar`: complete a pesquisa do passo anterior e avalie de novo.
      - `nao_aplicar`: chame `update_application` com status `descartada` e `discard_reason` igual ao `reason`.
      - `aplicar`: a vaga segue na lista de trabalho, e o `value_to_inform` será a pretensão informada.
