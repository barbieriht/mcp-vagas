# Critérios de triagem

Lidos pelo MCP em `triage_job` (variável `VAGAS_TRIAGE_CRITERIA`). Listas separadas por vírgula; maiúsculas e acentos são ignorados.

- Cargos alvo: data_scientist, ml_engineer, ai_engineer
- Cargos condicionados à aderência: data_engineer, data_analyst
- Aderência mínima: 50
- Empresas ignoradas: Empresa Exemplo
- Termos de vaga exclusiva PcD: exclusiva para PcD, exclusiva PcD, exclusiva para pessoas com deficiência, vaga afirmativa para PcD
- Locais aceitos para híbrido e presencial: São Paulo, Campinas

Cargos são os valores de `role_key`: data_scientist, ml_engineer, ai_engineer, data_engineer, data_analyst. Vagas remotas são sempre aceitas pelo local. Vaga híbrida ou presencial fora dos locais aceitos não é descartada: a triagem pede o seu julgamento (deslocamento viável?).
