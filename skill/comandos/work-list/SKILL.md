---
name: work-list
description: Mostra a lista de vagas a aplicar, da maior para a menor aderência ao currículo.
disable-model-invocation: true
---

Chame `work_list` e mostre as duas listas como vierem, sem recalcular:
- **Prontas para candidatura** (`ready`): uma tabela com empresa, cargo, modalidade, `match_score`, a pretensão (`value_to_inform`) e a URL. Nos termos ausentes (`missing`), mostre os relacionados (`related`) como "XGBoost: você tem LightGBM".
- **Com pendência** (`pending`): empresa, cargo e o que falta (`pending`).

Termine perguntando em quais vagas prontas o Thiago quer se candidatar e se quer resolver as pendências. Cada candidatura segue o fluxo da skill **candidaturas** (candidatar.md).
