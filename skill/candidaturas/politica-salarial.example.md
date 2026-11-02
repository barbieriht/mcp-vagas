# Política salarial

Lida pelo MCP em `evaluate_salary` (variável `VAGAS_SALARY_POLICY`), que escolhe a faixa pela modalidade, pelo local e pela moeda da vaga. Copie para `politica-salarial.md` e troque os valores; os valores aceitos estão no fim do arquivo.

- Modo: minimo
  - minimo: aplicar se a mediana de mercado for maior ou igual ao mínimo da faixa
  - faixa: aplicar só se a mediana estiver dentro da faixa
- Multiplicador PJ: 1.4
- Remoto nacional (BRL, CLT): mínimo 8000, máximo 12000
- Híbrido/presencial em São Paulo e região (BRL, CLT): mínimo 10000, máximo 15000
- Híbrido/presencial em São Carlos e região (BRL, CLT): usar a faixa do remoto nacional
- Internacional (USD): mínimo 3000

## Valores aceitos

Maiúsculas, acentos e ponto final no fim da linha são ignorados.

- **Modo:** `minimo` ou `faixa`. Sem a linha, vale `minimo`. O modo `faixa` exige `máximo` em todas as faixas usadas.
- **Multiplicador PJ:** número maior que zero, com ponto ou vírgula (`1.4` ou `1,4`). Converte as faixas CLT para vagas PJ.
- **Faixas:** uma linha por faixa, no formato `- <nome> (<moeda>[, CLT]): mínimo <valor>[, máximo <valor>]`.
  - Moeda: `BRL`, `USD` ou `EUR`. Obrigatória; as moedas nunca são convertidas entre si.
  - `CLT`: opcional. A faixa marcada com `CLT` é multiplicada pelo multiplicador em vagas PJ; sem ela, o valor vale para qualquer regime.
  - Valores mensais, como `8000`, `8.000` ou `R$ 8.000,00`. `máximo` é opcional.
  - Modalidade: as palavras remoto, híbrido ou presencial no nome dizem a quais modalidades a faixa vale (`Híbrido/presencial` = as duas). Sem nenhuma delas, vale para todas.
  - Local: a cidade depois de "em" (por exemplo, `em São Paulo e região`). A faixa vale quando o local da vaga cita essa cidade. Sem "em", vale para qualquer local.
  - No lugar dos valores, `usar a faixa do <nome de outra faixa>` copia os valores daquela faixa.
