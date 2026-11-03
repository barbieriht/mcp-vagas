# Buscar vagas

A busca termina quando:
- cada busca executada foi registrada;
- cada vaga encontrada foi triada (ficou `a_aplicar` ou `descartada`) ou identificada como já registrada;
- o Thiago recebeu o resumo da lista de trabalho.

## Passos

1. **Disparar a busca em lote.** Chame `start_search_run`. Ela executa em segundo plano as buscas sugeridas (`suggest_job_searches`, sem as feitas há pouco) na Gupy e no LinkedIn e a triagem (`triage_job`) de cada vaga nova. Padrão: no LinkedIn, só as buscas remotas e uma página por busca. Se o Thiago pediu algo específico (só um site, mais páginas, buscas por cidade no LinkedIn), ajuste `sources`, `max_pages` ou `linkedin_remote_only`. Para uma consulta fora das sugeridas (cargo, empresa, local), use `search_jobs` e `triage_job` como no plano B.
2. **Acompanhar.** Diga ao Thiago que a busca está rodando e quanto ela deve levar (cerca de 20 s por requisição no LinkedIn). Consulte `get_search_run` de tempos em tempos e mostre o `progress`, sem repetir a consulta em sequência. Se o status for `error` ou `interrompida`, informe o erro e ofereça disparar de novo: as buscas já feitas ficam registradas e não se repetem.
3. **Indeed e Glassdoor.** Eles bloqueiam a leitura automática: se o Thiago quiser, busque pelo navegador. Antes, chame `find_job_search`; se `recent` for verdadeiro, pule. Registre com `save_job_search`, incluindo os filtros e `results_count`, também quando não houver resultados, e trie cada vaga com `triage_job` e o `search_id`.
4. **Resolver o que ficou para julgamento.** Com o status `done`, use o `summary`:
   - `possiveis_duplicatas`: mostre ao Thiago as duas vagas (`url` e `matches`) e pergunte se são a mesma. Se não forem, chame `triage_job` com `not_duplicate` igual a true;
   - `needs`: resolva cada tipo como no passo 3 da triagem do [SKILL.md](SKILL.md) (pesquisa salarial, modalidade, local, senioridade);
   - `errors`: vagas que não puderam ser lidas (por exemplo, LinkedIn limitado) podem ser triadas mais tarde com `triage_job`.
5. **Resumo.** Apresente ao Thiago:
   - as novas vagas `a_aplicar` do `summary`, da maior para a menor aderência, com empresa, cargo, modalidade, `match_score` e a pretensão sugerida (`value_to_inform`);
   - as descartadas, com o motivo de cada uma;
   - quantas vagas já estavam registradas e quantas buscas foram puladas por serem recentes.

   Pergunte em quais ele quer se candidatar. Cada uma segue o fluxo de [candidatar.md](candidatar.md).

## Plano B: busca passo a passo

Use quando `start_search_run` não puder rodar (por exemplo, erro ao iniciar o processo):
1. Chame `suggest_job_searches`.
2. Para cada busca sem `recent`, chame `search_jobs` com a consulta, o site, o local e os filtros. Se voltar `skipped`, pule; se o LinkedIn limitar, siga com a Gupy e tente o LinkedIn mais tarde.
3. Trie cada resultado com `registered` vazio pela triagem do [SKILL.md](SKILL.md), passando o `search_id` para `triage_job`.
