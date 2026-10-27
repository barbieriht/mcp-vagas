# Montar ou atualizar o currículo geral

O currículo geral reúne **todas** as informações profissionais do Thiago. Tudo o que entra nos currículos personalizados sai dele. O fluxo termina num destes estados:
- o Thiago aprovou explicitamente uma versão (`approve_master`);
- o rascunho está salvo e o Thiago está revisando, com o caminho do arquivo e o relatório de revisão em mãos.

## Passos

1. **Ponto de partida.** Chame `get_master_resume`.
   - Se já existe um currículo geral aprovado, isto é uma **atualização**: parta dele, mantenha os IDs existentes (os currículos personalizados já gerados apontam para eles) e acrescente ou corrija só o que mudou.
   - Se não existe, é uma **criação**.
2. **PDF.** Se o Thiago tiver o currículo em PDF, chame `extract_resume_text` com o caminho. Caminhos do Windows são aceitos.
3. **LinkedIn.** Leia somente o perfil do próprio Thiago, no navegador em que ele está logado, no ritmo de uma pessoa. A URL do perfil vem do pedido dele; se ele não informar, pergunte. Para cada seção:
   - **About:** está na página do perfil.
   - **Experience, Education, Licenses & certifications e Volunteering:** abra a página de detalhes ("Show all", por exemplo `/details/experience/`, `/details/education/`, `/details/certifications/`, `/details/volunteering-experiences/`).
   - Role até o fim, até a lista parar de carregar.
   - Compare a quantidade de itens lidos com a contagem que a página mostra, por exemplo "Licenses & certifications (38)". Continue rolando até elas baterem.

   Copie o texto completo de cada seção e chame `save_resume_source` com a URL do perfil e as seções lidas.
4. **Combinar.** Monte o rascunho em inglês com a união das fontes:
   - About vira o `summary`;
   - cada cargo de Experience vira um item próprio, inclusive cargos diferentes na mesma empresa, com descrição em parágrafos;
   - Education vira `education`;
   - Licenses & certifications viram `certifications`, agrupadas por tema, com emissor, ano e link da credencial;
   - Volunteering vira `volunteering`;
   - skills e idiomas vêm do PDF.

   IDs são slugs legíveis e estáveis (`exp-empresa-cargo`, `exp-empresa-cargo-p1`).
5. **Divergências.** Liste ao Thiago o que as fontes dizem de forma diferente (datas, cargos, nomes, níveis de idioma) e pergunte qual vale. Use a resposta dele no rascunho.
6. **Rascunho.** Chame `save_master_draft`. Se ele recusar por haver edições do Thiago ainda não aprovadas, pergunte se pode sobrescrever.
7. **Revisão.** Mostre ao Thiago o caminho do arquivo e cada item do `review`. São números, datas, nomes e termos que não foram encontrados em nenhuma fonte. Corrija os que forem erro de transcrição e peça que ele revise e edite o arquivo.
8. **Aprovação.** Quando o Thiago disser que revisou e aprova, chame `approve_master`.
