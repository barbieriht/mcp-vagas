# Política salarial

Lida pelo MCP em `evaluate_salary` (variável `VAGAS_SALARY_POLICY`), que escolhe a faixa pela modalidade, pelo local e pela moeda da vaga. O jeito mais fácil de editar é o painel de configuração (as faixas são montadas marcando tipos de vaga e locais). Para editar à mão, copie para `politica-salarial.md` e troque os valores; os valores aceitos estão no fim do arquivo.

- Modo: minimo
  - minimo: aplicar se a mediana de mercado for maior ou igual ao mínimo da faixa
  - faixa: aplicar só se a mediana estiver dentro da faixa
  - O `máximo` de uma faixa é o teto da pretensão: no modo minimo ele só limita o valor informado e nunca exclui a vaga da triagem; no modo faixa, a vaga cuja mediana passa do máximo é descartada.
  - Como a pretensão sai do valor de mercado (teto, meio-termo, percentil 25 ou ponto baixo) é escolhido no `config.toml` (`salary_rule`), não aqui.
- Multiplicador PJ: 1.4

- Faixa: mínimo 8000, máximo 12000
  - Tipos: remoto
  - Remoto: nacional
  - CLT: sim
- Faixa: mínimo 10000, máximo 15000
  - Tipos: híbrido, presencial
  - Locais: SP: São Paulo
  - CLT: sim
- Faixa: mínimo 9000, máximo 13000
  - Tipos: híbrido, presencial
  - Locais: SP: Campinas, demais cidades
  - CLT: sim
- Faixa: mínimo 3000
  - Tipos: remoto
  - Remoto: internacional
  - Moeda: USD

## Valores aceitos

Maiúsculas, acentos e ponto final no fim da linha são ignorados.

- **Modo:** `minimo` ou `faixa`. Sem a linha, vale `minimo`. O modo `faixa` exige `máximo` em todas as faixas usadas.
- **Multiplicador PJ:** número maior que zero, com ponto ou vírgula (`1.4` ou `1,4`). Converte as faixas CLT para vagas PJ.
- **Faixa:** um conjunto de vagas com um valor mensal, no formato `- Faixa: mínimo <valor>[, máximo <valor>]`, seguido dos subitens abaixo. Valores como `8000`, `8.000` ou `R$ 8.000,00`; `máximo` é opcional (no modo minimo, só limita a pretensão).
  - **Tipos** (obrigatório): `remoto`, `híbrido` e/ou `presencial`, separados por vírgula.
  - **Remoto** (com o tipo remoto): `nacional` (vaga paga em reais) ou `internacional` (vaga paga em dólar ou euro). Os dois não ficam na mesma faixa, porque as moedas nunca são convertidas entre si.
  - **Moeda** (só no remoto internacional): `USD` ou `EUR`. As outras faixas são sempre em `BRL`. Remoto internacional não fica na mesma faixa que híbrido ou presencial.
  - **Locais** (com híbrido ou presencial): no formato dos locais aceitos dos critérios de triagem, `UF: cidade, cidade` com os estados separados por ponto e vírgula. `demais cidades` vale para as cidades do estado que não estão em outra faixa da mesma modalidade (ex.: `SP: São Carlos, demais cidades; RJ: demais cidades`). A cidade da vaga é a primeira parte do local ("Campinas" em "Campinas, São Paulo, Brasil") e só vale no estado do grupo; se a vaga não informa o estado, vale só a cidade.
  - **CLT** (opcional): `sim` marca a faixa em CLT, multiplicada pelo multiplicador em vagas PJ; sem a linha, o valor vale para qualquer regime.
  - A mesma cidade (ou "demais cidades" do mesmo estado) numa mesma modalidade só pode estar em uma faixa; em modalidades diferentes, pode estar na mesma faixa ou em faixas diferentes.
