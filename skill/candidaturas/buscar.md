# Buscar vagas

A busca termina quando:
- cada busca executada foi registrada;
- cada vaga encontrada foi triada (ficou `a_aplicar` ou `descartada`) ou identificada como já registrada;
- o Thiago recebeu o resumo da lista de trabalho.

## Passos

1. **Montar as buscas.** Chame `suggest_job_searches`. Ela combina os cargos alvo, os locais dos critérios de triagem e as skills mais citadas no currículo geral. Se o Thiago pediu algo específico (cargo, empresa, local), ajuste as consultas ou acrescente outras.
2. **Executar na Gupy e no LinkedIn.** Para cada busca sugerida sem `recent`, chame `search_jobs` com a consulta, o site, o local e os filtros. Ela já consulta `find_job_search`, registra a busca e devolve o `search_id`. Se voltar `skipped`, a busca foi feita há pouco: pule. Se o LinkedIn limitar as buscas, siga com as da Gupy e tente o LinkedIn mais tarde.
3. **Indeed e Glassdoor.** Eles bloqueiam a leitura automática: busque pelo navegador. Antes, chame `find_job_search`; se `recent` for verdadeiro, pule. Filtre por vagas recentes quando o site permitir e registre com `save_job_search`, incluindo os filtros e `results_count`, também quando não houver resultados.
4. **Triar cada resultado.** Faça a triagem do [SKILL.md](SKILL.md) de cada vaga com `registered` vazio, passando o `search_id` para `triage_job`. As que já têm `registered` entram no resumo com o status atual. A triagem já lê e registra a vaga; abra a vaga no navegador só quando a triagem automática falhar.
5. **Resumo.** Apresente ao Thiago:
   - as novas vagas `a_aplicar`, da maior para a menor aderência, com empresa, cargo, modalidade, `match_score`, os principais termos ausentes e a pretensão sugerida;
   - as descartadas, com o motivo de cada uma;
   - as já registradas, com o status atual.

   Pergunte em quais ele quer se candidatar. Cada uma segue o fluxo de [candidatar.md](candidatar.md).
