# Montar ou atualizar o currículo geral

O currículo geral é um **superconjunto**: guarda tudo o que as fontes trazem sobre o Thiago, e quem escolhe o que entra em cada vaga é o currículo personalizado. Na dúvida entre incluir e deixar de fora, inclua.

O fluxo termina num destes estados:
- o Thiago aprovou explicitamente uma versão (`approve_master`);
- o rascunho está salvo e o Thiago está revisando, com o caminho do arquivo, o relatório de revisão e a lista de conflitos em mãos.

## Passos

1. **Fontes e ponto de partida.**
   - Peça de uma vez ao Thiago o **caminho local** do PDF (pode ser do Windows) e a URL do perfil do LinkedIn, caso ele não tenha informado.
   - Chame `get_master_resume`. Se já existe um currículo geral aprovado, isto é uma **atualização**: parta dele, mantenha os IDs existentes (os currículos personalizados já gerados apontam para eles) e acrescente ou corrija só o que mudou. Se não existe, é uma **criação**.
2. **PDF.**
   - Com o caminho local, chame `extract_resume_text`.
   - Se o PDF só estiver anexado no chat, o MCP não enxerga o arquivo. Leia o conteúdo do anexo e registre o texto completo com `save_resume_source` (kind "pdf", `text` com o texto e `url` com o nome do arquivo).
3. **LinkedIn.** Leia somente o perfil do próprio Thiago, no navegador em que ele está logado, no ritmo de uma pessoa.
   1. **Página principal.** Abra o perfil e role até o fim antes de ler: About e Experience só aparecem no texto da página depois da rolagem. Leia o About e anote o **N** de cada botão "Show all N ..." (experiências, formação, certificações, voluntariado).
   2. **Páginas de detalhes.** Para cada seção, abra a página de detalhes (`/details/experience/`, `/details/education/`, `/details/certifications/`, `/details/volunteering-experiences/`). As listas carregam em lotes: role até o fim, espere, leia, e repita até a quantidade de itens lidos igualar o N.
      - Sem N disponível, pare quando três condições valerem juntas: rodapé da página visível, nenhum indicador de carregamento e duas leituras seguidas com a mesma quantidade. Diga ao Thiago que essa seção não teve a contagem verificada.
   3. **Links das credenciais.** O texto da página mostra só "Show credential". Leia o endereço (href) desses links pela árvore de acessibilidade da própria página de detalhes (por exemplo, read_page ou find no Claude in Chrome), sem abrir cada credencial. Se não for possível, registre emissor, data e ID e avise que os links ficaram de fora.
   4. **Anexos.** Em experiências com anexos (apresentações, artigos, certificados), copie o título de cada anexo junto com o texto da experiência: eles comprovam fatos citados no currículo.
   5. **Registro.** Chame `save_resume_source` (kind "linkedin") com a URL do perfil e o texto completo de cada seção lida.
   6. Feche a aba aberta para a leitura.
4. **Combinar.** Monte o rascunho em inglês com a união das fontes:
   - About vira o `summary`; headlines diferentes entre as fontes ficam em `headline_variants`, com a principal em `headline`.
   - Cada cargo de Experience vira um item próprio, inclusive cargos diferentes na mesma empresa, com descrição em parágrafos. Qualificadores do cargo ("EMBRAPII-funded project") vão em `context`. Outras formas do título usadas nas fontes ficam em `title_aliases`.
   - Cidade do escritório em `location` e modalidade em `work_mode` (remote, hybrid, onsite), mesmo quando a cidade parecer irrelevante para as vagas: formulários pedem.
   - Education vira `education`. Formação em andamento tem `end: "Present"` e a previsão de término em `notes` (por exemplo, "Expected Jul 2030"); a data prevista nunca vai em `end`.
   - Licenses & certifications viram `certifications`, agrupadas por tema. Cada item com `name` em inglês, `name_original` com o título exato quando a credencial não está em inglês, emissor, `issued` (YYYY-MM), `credential_id`, link e a descrição do curso, quando houver.
   - Volunteering vira `volunteering`.
   - Skills e idiomas vêm do PDF.

   IDs são slugs legíveis e estáveis (`exp-empresa-cargo`, `exp-empresa-cargo-p1`).
5. **Diferenças entre fontes.** Classifique cada diferença e resolva conforme o tipo:

   | Tipo | Exemplos | O que fazer |
   |---|---|---|
   | Conteúdo presente em só uma fonte | uma frase só no PDF; um voluntariado só no LinkedIn | incluir, sem perguntar |
   | Granularidade ou forma | PDF junta dois cursos que o LinkedIn separa; título traduzido e original; "2019–2024" e "Mar 2019 – Feb 2024" | resolver pelas regras abaixo, sem perguntar |
   | Conflito factual | data, cargo, instituição, nível de idioma ou status (concluído ou em andamento) incompatíveis | perguntar ao Thiago, numa lista única |

   Regras fixas:
   - Fica a versão mais granular: itens separados e datas com mês.
   - Uma frase que aparece em mais de um cargo fica em cada cargo onde a fonte a coloca.
   - Parágrafos equivalentes entre PDF e LinkedIn viram um só, com todos os termos técnicos que aparecem em qualquer das versões.
   - Credencial com o mesmo `credential_id` repetida na mesma fonte vira um item só, com a data de emissão mais antiga.
   - Qualificadores, previsões e variantes vão para os campos próprios descritos no passo 4.
6. **Rascunho.** Chame `save_master_draft`. Se ele recusar por haver edições do Thiago ainda não aprovadas, pergunte se pode sobrescrever.
7. **Revisão.** Mostre ao Thiago:
   - o caminho do arquivo;
   - cada item do `review` (números, datas, nomes e termos que não estão em nenhuma fonte), já corrigindo os que forem erro de transcrição;
   - os conflitos factuais do passo 5, com a pergunta sobre cada um;
   - as seções do LinkedIn cuja contagem não foi verificada.

   Peça que ele revise e edite o arquivo.
8. **Erros na fonte.** Quando a leitura revelar erros no próprio LinkedIn ou no PDF (credenciais duplicadas, datas inconsistentes, títulos divergentes), sugira ao Thiago corrigi-los lá, além de resolver no rascunho.
9. **Aprovação.** Quando o Thiago disser que revisou e aprova, chame `approve_master`.
