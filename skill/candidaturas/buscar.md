# Buscar vagas

A busca termina quando:
- cada busca executada foi registrada;
- cada vaga encontrada foi triada (ficou `a_aplicar` ou `descartada`) ou identificada como já registrada;
- o usuário recebeu o resumo da lista de trabalho.

## Passos

1. **Disparar a busca em lote.** Chame `start_search_run`. Ela executa em segundo plano as buscas sugeridas (`suggest_job_searches`, sem as feitas há pouco) na Gupy e no LinkedIn e a triagem (`triage_job`) de cada vaga nova. Padrão: no LinkedIn, só as buscas remotas e uma página por busca. Se o usuário pediu algo específico (só um site, mais páginas, buscas por cidade no LinkedIn), ajuste `sources`, `max_pages` ou `linkedin_remote_only`. Para uma consulta fora das sugeridas (cargo, empresa, local), use `search_jobs` e `triage_job` como no plano B.
2. **Acompanhar.** Diga ao usuário que a busca está rodando e quanto ela deve levar (cerca de 20 s por requisição no LinkedIn). Consulte `get_search_run` de tempos em tempos e mostre o `progress`, sem repetir a consulta em sequência. Se o status for `error` ou `interrompida`, informe o erro e ofereça disparar de novo: as buscas já feitas ficam registradas e não se repetem.
3. **Indeed e Glassdoor.** Eles bloqueiam a leitura automática: se o usuário quiser, busque pelo navegador. Antes, chame `find_job_search`; se `recent` for verdadeiro, pule. Registre com `save_job_search`, incluindo os filtros e `results_count`, também quando não houver resultados, e trie cada vaga com `triage_job` e o `search_id`.
4. **Resolver o que ficou para julgamento.** Com o status `done`, use o `summary`:
   - `possiveis_duplicatas`: mostre ao usuário as duas vagas (`url` e `matches`) e pergunte se são a mesma. Se não forem, chame `triage_job` com `not_duplicate` igual a true;
   - `needs`: resolva cada tipo como no passo 3 da triagem do [SKILL.md](SKILL.md) (pesquisa salarial, modalidade, local, senioridade);
   - `errors`: vagas que não puderam ser lidas (por exemplo, LinkedIn limitado) podem ser triadas mais tarde com `triage_job`.
5. **Resumo.** Chame `work_list` e apresente ao usuário:
   - as vagas prontas para candidatura (`ready`) e as que ainda têm pendência (`pending`), como no comando /work-list;
   - as descartadas, com o motivo de cada uma;
   - quantas vagas já estavam registradas e quantas buscas foram puladas por serem recentes.

   Pergunte em quais ele quer se candidatar. Cada uma segue o fluxo de [candidatar.md](candidatar.md).
6. **Regra da pretensão (só na primeira vez).** Se `work_list` trouxer `salary_rule.chosen` falso, pergunte ao usuário como a pretensão deve sair do valor de mercado (`salary_market`). Mostre as opções com o exemplo de uma vaga da tabela:
   - `teto` (padrão): a mediana do mercado, limitada ao máximo de cada faixa da [política salarial](politica-salarial.md). O teto não exclui vagas da triagem: só limita a pretensão delas;
   - `meio_termo`: a média entre o mínimo da política e a mediana do mercado;
   - `percentil_25`: o quartil inferior das fontes de mercado;
   - `ponto_baixo`: a mediana do ponto baixo de cada fonte (a média publicada ou, sem ela, o mínimo da faixa).

   Grave a resposta com `set_config` (`salary_rule`). As vagas já registradas são reavaliadas na hora: mostre a tabela ajustada com `reevaluated.changed` (vaga como link, valor de mercado, pretensão antes e depois). Se ele quiser trocar depois, é o mesmo `set_config`.

## Plano B: busca passo a passo

Use quando `start_search_run` não puder rodar (por exemplo, erro ao iniciar o processo):
1. Chame `suggest_job_searches`.
2. Para cada busca sem `recent`, chame `search_jobs` com a consulta, o site, o local e os filtros. Se voltar `skipped`, pule; se o LinkedIn limitar, siga com a Gupy e tente o LinkedIn mais tarde.
3. Trie cada resultado com `registered` vazio pela triagem do [SKILL.md](SKILL.md), passando o `search_id` para `triage_job`.
