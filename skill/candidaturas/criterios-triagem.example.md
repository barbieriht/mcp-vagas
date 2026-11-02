# Critérios de triagem

Lidos pelo MCP em `triage_job` e `suggest_job_searches` (variável `VAGAS_TRIAGE_CRITERIA`). Copie para `criterios-triagem.md` e troque os valores; os valores aceitos estão no fim do arquivo.

- Cargos alvo: data_scientist, ml_engineer, ai_engineer
- Cargos condicionados à aderência: data_engineer, data_analyst
- Aderência mínima: 50
- Empresas ignoradas: Empresa Exemplo
- Termos de vaga exclusiva PcD: exclusiva para PcD, exclusiva PcD, exclusiva para pessoas com deficiência, vaga afirmativa para PcD
- Locais aceitos para híbrido e presencial: São Paulo, Campinas
- Senioridades buscadas:

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
- **Locais aceitos para híbrido e presencial:** nomes de cidades, procurados no local da vaga. Vagas remotas são sempre aceitas pelo local. Vaga híbrida ou presencial fora desses locais não é descartada: a triagem pede o seu julgamento (deslocamento viável?).
- **Senioridades buscadas** (opcional, só afeta `suggest_job_searches`): `estagio`, `junior`, `pleno`, `senior` ou `especialista`; também com acento, como Estágio, Júnior e Sênior. Com valores, cada cargo vira uma busca por senioridade; vazio, as buscas saem sem senioridade.
