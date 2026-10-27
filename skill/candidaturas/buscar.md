# Buscar vagas

A busca termina quando:
- cada busca executada foi registrada;
- cada vaga encontrada foi triada (ficou `a_aplicar` ou `descartada`) ou identificada como já registrada;
- o Thiago recebeu o resumo da lista de trabalho.

## Passos

1. **Montar as buscas.** Chame `get_master_resume` e leia a [politica-salarial.md](politica-salarial.md). Monte consultas combinando:
   - cargos alvo: Data Scientist, Machine Learning Engineer, AI Engineer, Data Engineer e Data Analyst;
   - variações em português dos cargos;
   - a senioridade que o currículo sustenta;
   - de uma a três tecnologias centrais do currículo.

   Use estes locais: remoto, São Carlos e São Paulo. Use estes sites: LinkedIn, Gupy, Indeed e Glassdoor. Se o Thiago pediu algo específico (cargo, empresa, local), use isso.
2. **Evitar repetição.** Para cada consulta, site e local, chame `find_job_search`. Se `recent` for verdadeiro, pule essa combinação.
3. **Executar.** Faça a busca no site, filtrando por vagas recentes quando o site permitir. Registre com `save_job_search`, incluindo os filtros usados e `results_count`, também quando não houver resultados. Guarde o `search_id`.
4. **Triar cada resultado.** Abra cada vaga, leia a descrição completa e faça a triagem do [SKILL.md](SKILL.md) passando o `search_id`. A triagem já registra a vaga.
5. **Resumo.** Apresente ao Thiago:
   - as novas vagas `a_aplicar`, da maior para a menor aderência, com empresa, cargo, modalidade, `match_score`, os principais termos ausentes e a pretensão sugerida;
   - as descartadas, com o motivo de cada uma;
   - as já registradas, com o status atual.

   Pergunte em quais ele quer se candidatar. Cada uma segue o fluxo de [candidatar.md](candidatar.md).
