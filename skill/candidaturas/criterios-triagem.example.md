# Critérios de triagem

Lidos pelo MCP em `triage_job` e `suggest_job_searches` (variável `VAGAS_TRIAGE_CRITERIA`). Copie para `criterios-triagem.md` e troque os valores; os valores aceitos estão no fim do arquivo.

- Cargos alvo: data_scientist, ml_engineer, ai_engineer
- Cargos condicionados à aderência: data_engineer, data_analyst
- Aderência mínima: 50
- Empresas ignoradas: Empresa Exemplo
- Termos de vaga exclusiva PcD: exclusiva para PcD, exclusiva PcD, exclusiva para pessoas com deficiência, vaga afirmativa para PcD
- Vagas afirmativas que posso disputar: nenhuma
- Locais aceitos para híbrido e presencial: São Paulo, Campinas
- Senioridades buscadas:
- Anos por senioridade: junior 0, pleno 3, senior 5
- Estados aceitos para híbrido e presencial: SP

## Valores aceitos

Listas separadas por vírgula. Maiúsculas, acentos e ponto final são ignorados.

- **Cargos alvo** (obrigatório) e **Cargos condicionados à aderência** (opcional): um ou mais destes cargos, pelo código ou pelo nome em português ou inglês.
  - `data_scientist`: cientista de dados, data scientist
  - `ml_engineer`: engenheiro de machine learning, machine learning engineer
  - `ai_engineer`: engenheiro de IA, AI engineer
  - `data_engineer`: engenheiro de dados, data engineer
  - `data_analyst`: analista de dados, data analyst

  Cargo alvo segue na triagem. Cargo condicionado só segue com aderência igual ou maior que a mínima. Cargo reconhecido que não está em nenhuma das duas listas é descartado; título não reconhecido vai para o seu julgamento.
- **Aderência mínima:** número inteiro de 0 a 100 (aceita `%`). Sem a linha, vale 50.
- **Empresas ignoradas:** nomes livres. A comparação ignora maiúsculas, acentos e sufixos como Ltda e S.A.
- **Termos de vaga exclusiva PcD:** textos livres, procurados no título e na descrição da vaga.
- **Vagas afirmativas que posso disputar:** grupos cujas vagas afirmativas ou exclusivas você quer disputar: `mulheres`, `pessoas negras`, `LGBTQIA+`, `PcD`, `50+`, `indígenas`, ou `nenhuma`. A triagem detecta vagas afirmativas pelo título e pela descrição ("vaga exclusiva para mulheres", "afirmativa para pessoas negras") e descarta as de grupos que não estão na lista; sem a linha, vale `nenhuma`. Frases de inclusão ("incentivamos candidaturas de mulheres...") não contam. Vaga que se diz afirmativa sem citar um grupo reconhecido vira um item `afirmativa` em `needs`, para o seu julgamento. Com `PcD` na lista, os termos de PcD acima deixam de descartar a vaga.
- **Locais aceitos para híbrido e presencial:** nomes de cidades, procurados no local da vaga. Vagas remotas são sempre aceitas pelo local. Vaga híbrida ou presencial fora desses locais não é descartada: a triagem pede o seu julgamento (deslocamento viável?).
- **Anos por senioridade** (opcional): para vagas cujo título não diz a senioridade, a triagem usa os anos de experiência pedidos na descrição ("4+ years", "mínimo de 5 anos", "3 a 5 anos": vale o menor). Cada item é uma senioridade e o mínimo de anos: `junior 0, pleno 3, senior 5` (o padrão). Senioridades aceitas: as mesmas de "Senioridades buscadas".
- **Estados aceitos para híbrido e presencial** (opcional): siglas ou nomes de estados (`SP`, `Minas Gerais`). Vaga híbrida ou presencial em outro estado é descartada; no mesmo estado mas fora dos locais aceitos, a triagem pede o seu julgamento. Vazio: não filtra por estado.
- **Senioridades buscadas** (opcional, só afeta `suggest_job_searches`): `estagio`, `junior`, `pleno`, `senior` ou `especialista`; também com acento, como Estágio, Júnior e Sênior. Com valores, cada cargo vira uma busca por senioridade; vazio, as buscas saem sem senioridade.
