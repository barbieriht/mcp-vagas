# Critérios de triagem

Lidos pelo MCP em `triage_job` e `suggest_job_searches` (variável `VAGAS_TRIAGE_CRITERIA`). Copie para `criterios-triagem.md` e troque os valores; os valores aceitos estão no fim do arquivo.

- Cargos alvo: data_scientist, ml_engineer, ai_engineer
- Cargos condicionados à aderência: data_engineer, data_analyst
- Aderência mínima: 50
- Empresas ignoradas: Empresa Exemplo
- Vagas afirmativas que posso disputar: nenhuma
- Locais aceitos para híbrido e presencial: São Paulo, Campinas
- Senioridades buscadas:
- Níveis de experiência: junior 0-2, pleno 2-5, senior 5-8, especialista 7-12+, staff 10-15+
- Estados aceitos para híbrido e presencial: SP

Os níveis de experiência só embasam a candidatura: a triagem compara os seus anos de experiência (somados do currículo geral) com a faixa do nível da vaga e mostra o enquadramento. Quem decide é a lista de "Senioridades buscadas": vaga de nível que está nela segue mesmo fora do seu enquadramento; vaga de nível fora dela é descartada.

| Nível | Experiência aproximada | Característica |
|---|---|---|
| Júnior | 0–2 anos | Desenvolvimento de competências fundamentais |
| Pleno | 2–5 anos | Autonomia na execução e resolução de problemas |
| Sênior | 5–8 anos | Liderança técnica e resolução de problemas complexos |
| Especialista | 7–12+ anos | Profundidade técnica e referência em um domínio específico |
| Staff / Principal | 10–15+ anos | Influência arquitetural e técnica em escala organizacional |

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
- **Vagas afirmativas que posso disputar:** grupos cujas vagas afirmativas ou exclusivas você quer disputar: `mulheres`, `pessoas negras`, `LGBTQIA+`, `PcD`, `50+`, `indígenas`, ou `nenhuma`. A triagem detecta vagas afirmativas pelo título e pela descrição ("vaga exclusiva para mulheres", "afirmativa para pessoas negras") e descarta as de grupos que não estão na lista; sem a linha, vale `nenhuma`. Frases de inclusão ("incentivamos candidaturas de mulheres...") não contam. Vaga que se diz afirmativa sem citar um grupo reconhecido vira um item `afirmativa` em `needs`, para o seu julgamento. Vagas exclusivas para PcD ("exclusiva para PcD", "vaga destinada a pessoas com deficiência"...) são reconhecidas pela própria ferramenta; com `PcD` na lista, elas deixam de ser descartadas.
- **Locais aceitos para híbrido e presencial:** nomes de cidades, procurados no local da vaga. Vagas remotas são sempre aceitas pelo local. Vaga híbrida ou presencial fora desses locais não é descartada: a triagem pede o seu julgamento (deslocamento viável?).
- **Níveis de experiência** (opcional; também aceito como "Anos por senioridade"): a faixa de anos de cada nível, no formato `pleno 2-5` (ou `2 a 5`, `2–5`); `+` no fim ou só o mínimo (`staff 10+`, `pleno 3`) deixam a faixa sem teto. Sem a linha, vale a tabela acima: `junior 0-2, pleno 2-5, senior 5-8, especialista 7-12, staff 10-15`. Serve para: classificar vagas cujo título não diz o nível, pelos anos pedidos na descrição ("4+ years", "mínimo de 5 anos", "3 a 5 anos": vale o menor, e o nível é o maior cujo mínimo cabe); e mostrar o seu enquadramento. Níveis aceitos: os mesmos de "Senioridades buscadas".
- **Estados aceitos para híbrido e presencial** (opcional): siglas ou nomes de estados (`SP`, `Minas Gerais`). Vaga híbrida ou presencial em outro estado é descartada; no mesmo estado mas fora dos locais aceitos, a triagem pede o seu julgamento. Vazio: não filtra por estado.
- **Senioridades buscadas** (opcional; também aceito como "Senioridades a que me candidato"): `estagio`, `junior`, `pleno`, `senior`, `especialista` ou `staff` (Staff/Principal); também com acento, como Estágio, Júnior e Sênior. São os níveis a que você se candidata: vaga de nível fora da lista é descartada na triagem, mesmo que você se enquadre nele; vaga de nível da lista segue mesmo fora do seu enquadramento. Nas buscas, cada cargo vira uma busca por senioridade. Vazio: todos os níveis seguem e as buscas saem sem senioridade.
