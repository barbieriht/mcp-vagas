---
name: candidaturas
description: Vagas de emprego do Thiago com o MCP "vagas". Use para buscar vagas, triar ou avaliar uma vaga, candidatar-se, preencher formulários de candidatura, responder perguntas de processos seletivos (LinkedIn, Gupy, Indeed, Glassdoor, sites de empresas) ou montar e atualizar o currículo geral a partir do PDF e do LinkedIn.
---

# Candidaturas

Fontes da verdade:
- **Currículo geral aprovado** (`get_master_resume`) para experiência, formação, trabalho voluntário, certificações, skills e idiomas.
- [politica-salarial.md](politica-salarial.md) para a política salarial.
- [perfil.md](perfil.md) para os dados de formulário. Ele é carregado só na hora de preencher.
- **MCP "vagas"** como registro de tudo o que acontece com cada vaga.

## Escolha o fluxo

- O Thiago traz uma vaga e quer se candidatar: siga [candidatar.md](candidatar.md).
- Ele pede para buscar vagas: siga [buscar.md](buscar.md).
- Ele só quer saber se uma vaga vale a pena: faça a **triagem** abaixo e informe o resultado.
- Ele pediu para montar ou atualizar o currículo geral (pelo PDF, pelo LinkedIn ou pelos dois): siga [curriculo.md](curriculo.md). Esse fluxo roda só a pedido dele.

## Triagem

Toda vaga passa pela triagem antes de qualquer outra ação. Ela termina com a vaga registrada no MCP como `a_aplicar` ou `descartada`, ou identificada como já registrada.

1. **Duplicata.** Chame `find_application` com a URL e a empresa.
   - `pendente_usuario`: retome a candidatura pelo que está em `pending`.
   - `a_aplicar`: a vaga já foi triada. Siga para o próximo passo do fluxo com esse registro.
   - Qualquer outro status: informe o status atual ao Thiago e encerre a vaga.
   - Mesma empresa com outra vaga de cargo e senioridade parecidos, possivelmente de outra plataforma: pergunte ao Thiago se é a mesma vaga.
2. **Leitura da vaga.** Registre cargo, senioridade, modalidade, local, regime (CLT, PJ ou desconhecido), moeda, faixa salarial publicada (se houver) e a descrição completa.
3. **Critérios.**
   - **Cargos:** Data Scientist (júnior a sênior) e AI/ML Engineer. Analista ou engenheiro de dados entram quando a aderência ao currículo for boa.
   - **Locais:**
     - remoto, inclusive internacional;
     - São Carlos-SP;
     - híbrido com deslocamento viável a partir de São Carlos;
     - híbrido ou presencial em São Paulo e região, usando a faixa salarial de SP.
   - **Experiência exigida:** vagas que pedem 5 anos ou mais seguem na triagem quando a aderência técnica é alta.
   - **Prioridade:** vagas júnior em empresas grandes ou conhecidas merecem atenção extra.
   - **Descarte direto:** vagas da CI&T e vagas exclusivas para PcD.
   - **Avaliação normal:** BairesDev e vagas presenciais seguem os mesmos critérios das demais.

   Se a vaga reprovar aqui, chame `add_application` com status `descartada` e `discard_reason` explicando o critério, e encerre a vaga.
4. **Aderência.** Chame `score_job_match` com a descrição. Os termos em `match_terms` (`matched`) guiam o currículo personalizado, e os de `missing` mostram lacunas. A nota é indicativa e complementa os critérios.
5. **Registro.** Chame `add_application` com status `a_aplicar`, a descrição, `match_score`, `match_terms` e, se a vaga veio de uma busca, `search_id`.
6. **Salário.** Mapeie o cargo para `role_key` (Data Scientist: `data_scientist`; ML Engineer: `ml_engineer`; AI Engineer: `ai_engineer`; engenheiro de dados: `data_engineer`; analista de dados: `data_analyst`) e a senioridade para o enum do MCP.
   1. Se a vaga publica faixa salarial: chame `save_salary_estimate` com source "vaga", a empresa e o `application_id`.
   2. Senão, chame `find_salary_estimate` com a empresa. Para o escopo que não estiver fresco (`fresh_company`, `fresh_market`), pesquise salários na web (Glassdoor, LinkedIn Salary, guias salariais) e registre com `save_salary_estimate`, uma linha por dado, com fonte e URL. Se não encontrar nada, registre a pesquisa com a lista de pontos vazia.
   3. Chame `evaluate_salary` com o `application_id` e a política de [politica-salarial.md](politica-salarial.md): `my_min` e `my_max` da faixa da modalidade da vaga, o modo e o `pj_multiplier`.
      - `pesquisar`: complete a pesquisa do passo anterior e avalie de novo.
      - `nao_aplicar`: chame `update_application` com status `descartada` e `discard_reason` igual ao `reason`.
      - `aplicar`: a vaga segue na lista de trabalho, e o `value_to_inform` será a pretensão informada.
