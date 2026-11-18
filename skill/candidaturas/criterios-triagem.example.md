# Critérios de triagem

Lidos pelo MCP em `triage_job` e `suggest_job_searches` (variável `VAGAS_TRIAGE_CRITERIA`). Copie para `criterios-triagem.md` e troque os valores; os valores aceitos estão no fim do arquivo.

- Cargos alvo: <PREENCHER: os cargos do seu currículo que você busca>
- Cargos condicionados à aderência:
- Aderência mínima: 50
- Empresas ignoradas: Empresa Exemplo
- Vagas afirmativas que posso disputar: nenhuma
- Locais aceitos para híbrido e presencial: SP: São Paulo, Campinas
- Senioridades buscadas:
- Níveis de experiência: junior 0-2, pleno 2-5, senior 5-8, especialista 7-12+, staff 10-15+

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

- **Cargos alvo** (obrigatório) e **Cargos condicionados à aderência** (opcional): os cargos que você busca, em texto livre, como o seu currículo ou as vagas os chamam (`Desenvolvedor Backend, Product Manager`). Sinônimos vão entre parênteses: `Product Manager (PM, Gerente de Produto)`. O painel e a tool `suggest_target_roles` sugerem os cargos do seu currículo geral aprovado; nada é marcado sem você confirmar. A vaga casa com o cargo quando o título tem todas as palavras dele (ou de um sinônimo), sem contar acentos, maiúsculas, gênero, plural e nível ("Desenvolvedora Backend Pleno" casa com "Desenvolvedor Backend").

  Algumas famílias já trazem os nomes em português e inglês e também podem ser escritas pelo código: `data_scientist` (cientista de dados, data scientist), `ml_engineer` (engenheiro de machine learning, machine learning engineer), `ai_engineer` (engenheiro de IA, AI engineer), `data_engineer` (engenheiro de dados, data engineer) e `data_analyst` (analista de dados, data analyst).

  Cargo alvo segue na triagem. Cargo condicionado só segue com aderência igual ou maior que a mínima. Cargo reconhecido que não está em nenhuma das duas listas é descartado; título não reconhecido vai para o seu julgamento.
- **Aderência mínima:** número inteiro de 0 a 100 (aceita `%`). Sem a linha, vale 50.
- **Empresas ignoradas:** nomes livres. A comparação ignora maiúsculas, acentos e sufixos como Ltda e S.A.
- **Vagas afirmativas que posso disputar:** grupos cujas vagas afirmativas ou exclusivas você quer disputar: `mulheres`, `pessoas negras`, `LGBTQIA+`, `PcD`, `50+`, `indígenas`, ou `nenhuma`. A triagem detecta vagas afirmativas pelo título e pela descrição ("vaga exclusiva para mulheres", "afirmativa para pessoas negras") e descarta as de grupos que não estão na lista; sem a linha, vale `nenhuma`. Frases de inclusão ("incentivamos candidaturas de mulheres...") não contam. Vaga que se diz afirmativa sem citar um grupo reconhecido vira um item `afirmativa` em `needs`, para o seu julgamento. Vagas exclusivas para PcD ("exclusiva para PcD", "vaga destinada a pessoas com deficiência"...) são reconhecidas pela própria ferramenta. Quem decide se você as disputa é o campo "Possui deficiência" do perfil: só com "Sim" elas seguem; com "Não", "Prefiro não responder" ou o campo a preencher, são descartadas, mesmo com `PcD` nesta lista. Sem o campo no perfil, vale `PcD` nesta lista.
- **Locais aceitos para híbrido e presencial:** cidades agrupadas por estado, no formato `UF: cidade, cidade`, com os grupos separados por ponto e vírgula (por exemplo, `SP: São Carlos, São Paulo, Barueri; RJ: Niterói; MG:`). O estado vale pela sigla ou pelo nome. Vagas remotas são sempre aceitas pelo local. Vaga híbrida ou presencial numa das cidades do grupo, no mesmo estado, é aceita (São Carlos de SP não aceita São Carlos de SC; se a vaga não informa o estado, vale só a cidade). Os estados dos grupos são os estados aceitos: vaga híbrida ou presencial em outro estado é descartada; num estado aceito mas fora das cidades dele (ou num estado sem cidades, como `MG:` acima), a triagem pede o seu julgamento (deslocamento viável?). Cidades sem `UF:` na frente (o formato antigo, `São Paulo, Campinas`) valem em qualquer estado. Vazio: nenhuma cidade aceita de antemão e nenhum filtro por estado.
- **Níveis de experiência** (opcional; também aceito como "Anos por senioridade"): a faixa de anos de cada nível, no formato `pleno 2-5` (ou `2 a 5`, `2–5`); `+` no fim ou só o mínimo (`staff 10+`, `pleno 3`) deixam a faixa sem teto. Sem a linha, vale a tabela acima: `junior 0-2, pleno 2-5, senior 5-8, especialista 7-12, staff 10-15`. Estágio e trainee são programas, não faixas de experiência, e ficam fora da tabela (inclua `trainee 0-1` se quiser o enquadramento). Serve para: classificar vagas cujo título não diz o nível, pelos anos pedidos na descrição ("4+ years", "mínimo de 5 anos", "3 a 5 anos": vale o menor, e o nível é o maior cujo mínimo cabe); e mostrar o seu enquadramento. Níveis aceitos: os mesmos de "Senioridades buscadas".
- **Estados aceitos para híbrido e presencial** (linha antiga, ainda lida): siglas ou nomes de estados, somados aos estados dos grupos de locais. O painel a junta aos grupos ao salvar.
- **Senioridades buscadas** (opcional; também aceito como "Senioridades a que me candidato"): `estagio`, `trainee`, `junior`, `pleno`, `senior`, `especialista` ou `staff` (Staff/Principal); também com acento, como Estágio, Júnior e Sênior. São os níveis a que você se candidata: vaga de nível fora da lista é descartada na triagem, mesmo que você se enquadre nele; vaga de nível da lista segue mesmo fora do seu enquadramento. Nas buscas, cada cargo vira uma busca por senioridade. Vazio: todos os níveis seguem e as buscas saem sem senioridade.
