# Candidatar-se a uma vaga

A candidatura termina num destes dois estados:
- `aplicada`: o Thiago confirmou o envio e o formulário foi enviado;
- `pendente_usuario`: algo bloqueou o envio, e o `pending` descreve exatamente o que falta.

## Antes da primeira vaga da conversa

Sugira uma vez, sem insistir, que o Thiago reduza os pedidos de permissão do navegador (só ele pode mudar isso; você não tem acesso à extensão): no menu do campo de conversa do Claude in Chrome (Desktop ou painel da extensão), escolher **Automatically approve** (modo Auto) e, no primeiro aviso de cada site de vagas, **Always allow actions on this site**. Não recomende **Skip all approvals**: descrições de vagas e páginas de empresas são conteúdo de terceiros. Downloads, dados sensíveis e autorizações continuam pedindo confirmação, e isso é desejado.

## Passos

1. **Triagem.** Faça a triagem do [SKILL.md](SKILL.md). Siga adiante só com a vaga em `a_aplicar` ou com uma `pendente_usuario` sendo retomada.
2. **Currículo personalizado.** Chame `suggest_tailored_selection` com o `application_id`: ela devolve uma seleção inicial, já ordenada pelos termos da vaga. Chame `get_master_resume` para ler os textos e refine a proposta:
   - corte ou reordene itens e parágrafos (a pontuação em `scores` mostra o que cita mais termos da vaga);
   - reescreva parágrafos longos como bullets objetivos, em inglês;
   - descreva cada responsabilidade com o mesmo verbo e o mesmo escopo do currículo geral.

   Chame `create_tailored_resume` com o `application_id` (o PDF recebe o nome da empresa e do cargo da vaga, para não confundir vagas da mesma empresa). Se a validação rejeitar algo, ajuste a seleção ou o texto ao que o currículo geral diz e gere de novo. Guarde o caminho do PDF e o id do currículo.
3. **Formulário.**
   - **Perfil:** chame `get_profile`. Use os campos com status `ok`; os com `preencher` são bloqueios (passo 4); os `manual` o Thiago digita; os `cofre` são preenchidos na revisão (passo 5). As `notes` de cada campo dizem como responder (por exemplo, em escalas fixas). Se a tool der erro, leia o [perfil.md](perfil.md).
   - **Acesso:** abra a vaga no navegador e entre pelo login padrão de `get_config` (`login_method`). Com `linkedin`, aplique ou entre com a conta do LinkedIn; com `google`, entre com a conta Google de `login_email`. Se o site não oferecer esse método, use o outro e avise o Thiago. Se `login_method` não estiver configurado, pergunte e grave com `set_config`.
   - **Vaga encerrada:** se a página mostrar "Not currently accepting applications" (ou equivalente), não preencha nada: informe ao Thiago e, se a vaga já estiver registrada, chame `update_application` com status `descartada` e `discard_reason` "vaga encerrada".
   - **Dados:** preencha com os dados do perfil e do currículo geral.
   - **Anexo:** anexe o PDF personalizado. Se o navegador não conseguir anexar (por exemplo, a ferramenta de upload não aceita caminhos do disco ou o arquivo está no Windows, fora do seu ambiente), não pare nem espere: preencha o resto, deixe a aba aberta e siga o passo 4 com `pendente_usuario`. No `pending`, diga qual arquivo anexar usando o `windows_path` do currículo (de `create_tailored_resume` ou `get_resume`), no formato: "Anexar <nome do PDF> (currículo ID <n>, em <windows_path>); <o que mais falta>; revisar e enviar". Depois siga para a próxima vaga (veja "Abas abertas").
   - **Pretensão salarial:** use o `value_to_inform` da avaliação salarial. Se não estiver à mão, ele está em `salary_evaluation`, no `get_history`.
   - **Consentimentos:** marque os de privacidade e LGPD exigidos pelo formulário. Se o navegador recusar marcar os termos de uso ou a declaração, ou o envio, trate como etapa do Thiago: aba aberta, `pendente_usuario` e o item no `pending` ("aceitar os termos e enviar").
4. **Bloqueios.** Campos com status `cofre` em `get_profile` não bloqueiam: eles são preenchidos na revisão (passo 5), com a confirmação do Thiago. Se o formulário exigir criar conta com senha, um documento ou dado sensível que não está no cofre, ou uma resposta que não está no perfil nem no currículo:
   - registre cada campo novo no perfil (seção "Campos novos do perfil" abaixo);
   - preencha todo o resto e deixe a aba aberta;
   - chame `update_application` com status `pendente_usuario`, `pending` listando cada item que falta e o `resume_id`;
   - avise o Thiago e encerre a vaga.
5. **Revisão antes do envio.** Pare antes do botão final de envio. Mostre ao Thiago:
   - a vaga;
   - o currículo anexado;
   - a pretensão informada;
   - as respostas abertas;
   - os dados do cofre que o formulário pede, um por linha: "vou preencher o seu CPF na vaga X da empresa Y (domínio Z)".

   Dados do cofre:
   - Só depois que o Thiago confirmar explicitamente, chame `get_sensitive_field` com o campo, o `application_id` e a URL atual do formulário (`form_url`). Digite o valor só no campo do formulário: nunca o escreva na conversa.
   - Se a tool recusar (domínio diferente do da vaga, candidatura não triada, campo fora do cofre), não preencha. Chame `update_application` com status `pendente_usuario`, `pending` dizendo qual dado falta e o motivo da recusa, e avise o Thiago.

   Clique em enviar somente depois que ele confirmar.
6. **Registro final.** Depois do envio confirmado, chame `update_application` com status `aplicada`, o `resume_id` e uma nota com a data e a plataforma.
   - **Testes e etapas depois do envio.** Se a página de confirmação (ou o e-mail dela) pedir teste técnico, coding challenge, teste de proficiência, questionário de perfil, vídeo gravado ou qualquer avaliação, a candidatura já está concluída: o seu trabalho acabou. Não faça nem inicie o teste (muitos têm cronômetro) e não espere o Thiago fazê-lo. Registre a pendência em `pending` (nome do teste, link e prazo, se houver), mantendo o status `aplicada`. Sem etapa extra, deixe `pending` vazio.
   - **Próxima vaga.** Com a candidatura registrada, siga para a próxima vaga do pedido sem esperar. Veja "Várias vagas" no [SKILL.md](SKILL.md).

## Abas abertas

Cada vaga deixada em `pendente_usuario` com o formulário aberto ocupa uma aba. Para não sobrecarregar o computador do Thiago:
- Chame `get_config` e leia `max_open_tabs` (padrão 12; ele muda com `set_config`).
- Conte as abas de candidatura que você deixou abertas nesta conversa. Depois de um envio confirmado (`aplicada`), feche a aba da vaga. Nunca feche abas que você não abriu.
- Ao chegar no limite, não abra outro formulário: encerre o lote, deixe as vagas restantes como `a_aplicar` e entregue o resumo, pedindo ao Thiago que conclua e feche as abas pendentes e peça de novo para continuar.
- No resumo, uma linha por aba aberta: empresa, cargo, o PDF a anexar (nome e `windows_path`) e o que falta.

## Campos novos do perfil

Todo dado pedido por um formulário que ainda não está no [perfil.md](perfil.md) nem no currículo geral passa a ser documentado, para que da próxima vez seja preenchido direto.

1. **Registrar o campo.** Chame `add_profile_field` com o rótulo como o formulário pede e, se o assunto combinar com uma seção existente (contato, respostas padrão), a `section`. Ela grava o campo no [perfil.md](perfil.md) e no [perfil.example.md](perfil.example.md), no formato certo; sem `section`, o campo vai para "Outros campos de formulário". Se a opção é de lista fechada (por exemplo, "Como soube da vaga?"), inclua as opções oferecidas no rótulo.
2. **Guardar a resposta.** Quando o Thiago responder, chame `add_profile_field` de novo com o mesmo rótulo e a resposta em `value`: ela troca o `<PREENCHER>` pela resposta.
3. **Dados sensíveis.** Para CPF, RG, passaporte, senhas e dados bancários, chame `add_profile_field` sem `value` (com `sensitive` true se o rótulo não deixar claro). O campo fica como `informar manualmente`, e o valor é digitado pelo Thiago no formulário. Documentos da lista do cofre (CPF, RG, CNH, PIS, CTPS, título de eleitor, passaporte, nome da mãe) podem ir para o cofre: sugira ao Thiago cadastrar pelo terminal (`python -m vagas.sensitive set cpf`). Nunca peça o valor na conversa. Senhas e dados bancários ficam sempre manuais.

Se a tool der erro por não achar a pasta da Skill (por exemplo, na Skill instalada por zip no Desktop), mostre ao Thiago as linhas exatas a acrescentar em cada arquivo, no formato `- <rótulo>: <valor>`.

## Respostas em texto

Vale para cartas de apresentação, perguntas abertas e campos livres:
- **Idioma:** o mesmo do formulário. Em português, use acentuação e pontuação corretas.
- **Voz:** primeira pessoa, natural e direta, em texto corrido sem negrito.
- **Conteúdo:** quando couber, fale de crescimento profissional e aprendizado contínuo, e da conciliação entre trabalho e pesquisa (doutorado em andamento).
- **Fatos:** use somente fatos do currículo geral e do perfil, com os mesmos números, tecnologias e escopo de responsabilidade. Quando a pergunta pedir algo que não está nessas fontes, trate como bloqueio (passo 4).
