# Política salarial

Lida pelo MCP em `evaluate_salary` (variável `VAGAS_SALARY_POLICY`), que escolhe a faixa pela modalidade, pelo local e pela moeda da vaga. Faixas mensais; as marcadas com CLT são multiplicadas pelo multiplicador em vagas PJ. Uma faixa vale para as modalidades citadas no nome (nenhuma = todas) e para a cidade depois de "em" (nenhuma = qualquer local).

- Modo: minimo
  - minimo: aplicar se a mediana de mercado for maior ou igual ao mínimo da faixa
  - faixa: aplicar só se a mediana estiver dentro da faixa
- Multiplicador PJ: 1.4
- Remoto nacional (BRL, CLT): mínimo 8000, máximo 12000
- Híbrido/presencial em São Paulo e região (BRL, CLT): mínimo 10000, máximo 15000
- Híbrido/presencial em São Carlos e região (BRL, CLT): usar a faixa do remoto nacional
- Internacional (USD): mínimo 3000
