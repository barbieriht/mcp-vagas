---
name: screen
description: Faz só a triagem de uma vaga e registra o resultado (a aplicar ou descartada).
argument-hint: "<URL da vaga>"
disable-model-invocation: true
---

Use a skill **candidaturas** e faça somente a triagem (SKILL.md) da vaga: $ARGUMENTS

Ao final, informe o resultado: duplicata e status atual, ou registrada como `a_aplicar` (com `match_score`, termos ausentes e pretensão sugerida), ou `descartada` (com o motivo). Não abra formulário.

Se nenhuma URL ou descrição de vaga foi informada, peça antes de começar.
