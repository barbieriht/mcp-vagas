---
name: pending
description: Mostra o que depende do Thiago e as candidaturas sem resposta há mais de 30 dias.
disable-model-invocation: true
---

1. Chame `list_applications` com `only_pending` e mostre, para cada candidatura, empresa, cargo, status e o que falta (`pending`).
2. Chame `list_applications` com `stale_days` igual a 30 e mostre as candidaturas sem resposta, com a data do último evento (`last_event_at`).

Se as duas listas estiverem vazias, diga que não há nada pendente.
