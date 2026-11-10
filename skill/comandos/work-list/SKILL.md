---
name: work-list
description: Mostra a lista de vagas a aplicar, da maior para a menor aderência ao currículo.
disable-model-invocation: true
---

Chame `work_list` e mostre as duas listas como vierem, sem recalcular:
- **Prontas para candidatura** (`ready`): uma tabela com a vaga como link (`[Cargo — Empresa](url)`), modalidade, `match_score`, o valor de mercado (`salary_market`), a pretensão (`value_to_inform`) e a regra (`salary_rule`). Nos termos ausentes (`missing`), mostre os relacionados (`related`) como "XGBoost: você tem LightGBM".
- **Com pendência** (`pending`): a vaga como link e o que falta (`pending`).

Se `salary_rule.chosen` for falso, ofereça escolher a regra da pretensão como no passo 6 de buscar.md (skill **candidaturas**).

Termine perguntando em quais vagas prontas o usuário quer se candidatar e se quer resolver as pendências. Cada candidatura segue o fluxo da skill **candidaturas** (candidatar.md).
