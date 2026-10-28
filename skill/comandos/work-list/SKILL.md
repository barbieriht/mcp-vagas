---
name: work-list
description: Mostra a lista de vagas a aplicar, da maior para a menor aderência ao currículo.
disable-model-invocation: true
---

Chame `list_applications` com status `a_aplicar`. Mostre uma tabela, na ordem recebida, com:
- empresa, cargo e modalidade;
- `match_score` e os principais termos ausentes de `match_terms`;
- a pretensão sugerida (`value_to_inform` em `salary_evaluation`, quando houver);
- a URL.

Termine perguntando em quais vagas o Thiago quer se candidatar. Cada uma segue o fluxo de candidatura da skill **candidaturas** (candidatar.md).
