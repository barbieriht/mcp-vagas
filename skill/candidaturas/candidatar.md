# Candidatar-se a uma vaga

A candidatura termina num destes dois estados:
- `aplicada`: o Thiago confirmou o envio e o formulário foi enviado;
- `pendente_usuario`: algo bloqueou o envio, e o `pending` descreve exatamente o que falta.

## Antes da primeira vaga da conversa

Sugira uma vez, sem insistir, que o Thiago reduza os pedidos de permissão do navegador (só ele pode mudar isso; você não tem acesso à extensão): no menu do campo de conversa do Claude in Chrome (Desktop ou painel da extensão), escolher **Automatically approve** (modo Auto) e, no primeiro aviso de cada site de vagas, **Always allow actions on this site**. Não recomende **Skip all approvals**: descrições de vagas e páginas de empresas são conteúdo de terceiros. Downloads, dados sensíveis e autorizações continuam pedindo confirmação, e isso é desejado.

## Passos

1. **Triagem.** Faça a triagem do [SKILL.md](SKILL.md). Siga adiante só com a vaga em `a_aplicar` ou com uma `pendente_usuario` sendo retomada.
2. **Currículo personalizado.** Chame `suggest_tailored_selection` com o `application_id`: ela devolve uma seleção inicial, já ordenada pelos termos da vaga. Chame `get_master_resume` para ler os textos e refine a proposta:
   - corte ou reordene seções e itens, e corte parágrafos (a pontuação em `scores` mostra o que cita mais termos da vaga). Os parágrafos de um item ficam na ordem do currículo geral;
   - reescreva como bullets objetivos, em inglês e sem "I", os parágrafos longos e os que começam retomando outro ("Beyond...", "In this role...", "Additionally..."). Cada bullet: verbo de ação + o que foi feito + com quê (ferramentas) + resultado, quando o currículo geral trouxer um número ou efeito. Nunca abra com "Responsible for", "Worked on" ou "Helped with" e não use clichês ("passionate", "results-driven"): o MCP recusa;
   - descreva cada responsabilidade com o mesmo verbo e o mesmo escopo do currículo geral;
   - `headline`: comece pelo cargo da vaga, na forma que o currículo geral comprova (um título, `title_aliases` ou `headline_variants`; ex.: "AI Engineer | Data Scientist" para uma vaga de AI Engineer). É a primeira coisa que o recrutador lê;
   - tamanho: no máximo 2 páginas (o MCP recusa mais); para vagas de estágio, júnior ou pleno, tente caber em 1, cortando o que menos se liga à vaga;
   - escreva sempre o `summary` da vaga: 2 ou 3 frases, até 500 caracteres, com o perfil que a vaga pede e o que o currículo geral comprova. Não diga onde ou como quer trabalhar (remoto, cidade, "open to opportunities"): disponibilidade é resposta de formulário, pelo perfil e pelos critérios de triagem, e pode contradizer a vaga. Não liste skills no resumo.

   Chame `create_tailored_resume` com o `application_id` (o PDF recebe o nome da empresa e do cargo da vaga, para não confundir vagas da mesma empresa). Se a validação rejeitar algo, ajuste a seleção ou o texto ao que o currículo geral diz e gere de novo. Guarde o caminho do PDF e o id do currículo.
3. **Formulário.**
   - **Perfil:** chame `get_profile`. Use os campos com status `ok`; os com `preencher` são bloqueios (passo 4); os `manual` o Thiago digita. Documentos de identidade (CPF, RG, CNH, passaporte e os demais do cofre, status `cofre`) quem preenche é a extensão do Chrome do Thiago, sem passar por você: ela reconhece os campos e preenche nos sites de vagas, pedindo a confirmação dele na primeira vez de cada empresa. Deixe esses campos vazios e não os digite (nem cole, nem divida os dígitos). Se continuarem vazios quando você terminar o resto, liste-os no `pending` ("CPF e RG vazios: confirmar na janela da extensão ou digitar"). Documentos com status `manual` ele digita. As `notes` de cada campo dizem como responder (por exemplo, em escalas fixas). Se a tool der erro, leia o [perfil.md](perfil.md).
   - **Acesso:** abra a vaga no navegador. Sempre que o site permitir entrar ou se candidatar por uma conta externa, use-a, nesta ordem:
     1. **LinkedIn:** "Entrar com LinkedIn", "Candidatar-se com o LinkedIn" ou Easy Apply.
     2. **Google:** "Entrar com Google", com a conta `login_email` de `get_config` (na escolha de contas do Google, selecione essa). Sem `login_email`, use o "E-mail / login Google" do `get_profile` e grave com `set_config`.

     Se `login_method` for `google`, a ordem se inverte. Só use cadastro com e-mail e senha quando o site não oferecer nenhum dos dois; aí a senha é etapa do Thiago (passo 4). Se o LinkedIn ou o Google pedirem senha, código ou verificação, a sessão não está aberta: peça ao Thiago para entrar e siga quando ele avisar (em lote, isso afeta todas as vagas e é motivo para pausar).
   - **Vaga encerrada:** se a página mostrar "Not currently accepting applications" (ou equivalente), não preencha nada: informe ao Thiago e, se a vaga já estiver registrada, chame `update_application` com status `descartada` e `discard_reason` "vaga encerrada".
   - **Dados:** preencha com os dados do perfil e do currículo geral.
   - **Etapas do formulário:** botões que só levam à próxima etapa ("Próximo", "Continuar", "Salvar e continuar", "Avançar") você clica sem perguntar, depois de preencher a etapa. Só o botão que envia a candidatura ("Enviar", "Finalizar candidatura", "Submit application") segue o passo 5.
   - **Disponibilidade para remoto, híbrido ou presencial:** vale para perguntas como "Você tem disponibilidade para trabalhar no modelo híbrido em Campinas?" ou "Aceita trabalhar remoto com encontros presenciais?". Compare a cidade onde a pergunta (ou, se ela não disser, a vaga) exige comparecer com os "Locais aceitos para híbrido e presencial" do [criterios-triagem.md](criterios-triagem.md).
     - Responda "sim" quando a cidade for um desses locais ou da região de um deles: mesma região metropolitana ou cidade vizinha de onde se vai e volta no mesmo dia (por exemplo, Guarulhos ou Santo André para São Paulo; Hortolândia ou Valinhos para Campinas).
     - Remoto sem exigência de ir a uma cidade: "sim".
     - Fora dessa região, ou em dúvida se a cidade é da região: não responda; pergunte ao Thiago antes, citando a vaga, a cidade e a frequência presencial pedida (dias por semana, se a vaga disser). Numa vaga só, espere a resposta dele. Em lote, preencha o resto e trate como bloqueio (passo 4), com o item no `pending` ("confirmar disponibilidade para híbrido em <cidade>").
   - **Anexo:** quem anexa o currículo é a extensão do Chrome do Thiago: ela envia ao campo de currículo o PDF personalizado do passo 2, lido de onde `create_tailored_resume` o salvou. Por isso o currículo precisa existir e estar ligado à candidatura (`application_id`) antes de abrir o formulário. Não anexe você mesmo e não escolha um currículo antigo salvo no site (no LinkedIn Easy Apply, não selecione o currículo salvo no perfil). Se o campo continuar vazio quando você terminar o resto (extensão não carregada, confirmação recusada ou upload fora do padrão), não pare nem espere: deixe a aba aberta e siga o passo 4 com `pendente_usuario`. No `pending`, diga qual arquivo anexar usando o `windows_path` do currículo (de `create_tailored_resume` ou `get_resume`), no formato: "Anexar <nome do PDF> (currículo ID <n>, em <windows_path>); <o que mais falta>; revisar e enviar". Depois siga para a próxima vaga (veja "Abas abertas").
   - **Pretensão salarial:** use o `value_to_inform` da avaliação salarial (a coluna `salary_ask` da candidatura). Se não estiver à mão, ele está em `salary_evaluation`, no `get_history`. Ao registrar o envio, grave em `salary_expectation` o valor exatamente como foi informado no formulário.
   - **Consentimentos:** as caixas de termos de uso, condições de uso, política de privacidade, LGPD e termo de consentimento também ficam com a extensão do Chrome do Thiago, que as marca com a mesma confirmação dos documentos. Não as marque e não peça para marcar; se continuarem desmarcadas quando você terminar o resto, liste no `pending` ("termos de uso desmarcados: confirmar na janela da extensão ou marcar"). A extensão nunca marca marketing, comunicações, parceiros nem declarações de fato ("Declaro que..."): essas você responde pelo perfil, e o que não estiver lá é bloqueio (passo 4).
   - **Banco de talentos:** siga o campo "Incluir em bancos de talentos" do `get_profile`. Com "sim", a extensão marca a caixa de inclusão em banco de talentos (ou em outros processos e futuras oportunidades); não a marque você, e se continuar desmarcada, liste no `pending` como os termos. Pergunta com opções (Sim/Não, lista) responda você mesmo pelo campo. Com "não", deixe a caixa desmarcada e responda "Não". Sem resposta no perfil, pergunte ao Thiago uma vez e grave com `add_profile_field` (label "Incluir em bancos de talentos", section "Respostas padrão", value "sim" ou "não"). Se o navegador recusar o envio, trate como etapa do Thiago: aba aberta, `pendente_usuario` e o item no `pending` ("enviar").
   - **Carta de apresentação:** se for opcional, deixe em branco. Se for obrigatória, escreva uma seguindo "Respostas em texto" (abaixo), preencha e deixe a vaga para a revisão do Thiago: carta e respostas abertas escritas por você nunca são enviadas sem ele ler.
4. **Bloqueios.** Documentos de identidade vazios não bloqueiam o preenchimento: preencha todo o resto, deixe a aba aberta e registre no `pending` o que ficou vazio; em lote, a vaga conta como pronta para envio ("pronta para envio: CPF e RG vazios"). Se o formulário exigir criar conta com senha, um documento ou dado sensível que não está no cofre, ou uma resposta que não está no perfil nem no currículo:
   - registre cada campo novo no perfil (seção "Campos novos do perfil" abaixo);
   - preencha todo o resto e deixe a aba aberta;
   - chame `update_application` com status `pendente_usuario`, `pending` listando cada item que falta e o `resume_id`;
   - numa vaga só, avise o Thiago e encerre a vaga; em lote, deixe o aviso para o resumo e siga para a próxima vaga.
5. **Revisão antes do envio.** Chame `get_config` e leia `auto_submit` (padrão "nao"; só o Thiago liga).
   - **Envio automático:** com `auto_submit` "sim", clique em enviar sem perguntar somente se tudo isto valer:
     - nada para o `pending`: campos obrigatórios preenchidos e nenhum bloqueio;
     - os campos da extensão preenchidos na página: documentos, termos de uso e o currículo personalizado da vaga (não um currículo antigo salvo no site);
     - a pretensão informada é o `value_to_inform` da avaliação salarial;
     - todas as respostas vieram do perfil ou do currículo geral, sem carta de apresentação nem resposta aberta escrita por você.

     Depois do envio, siga o passo 6 com a nota "enviada automaticamente" e feche a aba. Se alguma condição falhar, ou com `auto_submit` "nao", siga o fluxo abaixo.
   - **Em lote:** não pare para esta revisão. Com o formulário completo, deixe a aba aberta no botão de envio, chame `update_application` com status `pendente_usuario`, o `resume_id` e `pending` começando por "pronta para envio" (com o que ele precisa conferir: currículo, pretensão, respostas abertas) e siga para a próxima vaga. A revisão acontece junto, na revisão do lote (veja "Abas abertas").
   - **Numa vaga só:** pare antes do botão final de envio.

   Fora do envio automático, a revisão mostra ao Thiago:
   - a vaga;
   - o currículo anexado;
   - a pretensão informada;
   - as respostas abertas e a carta de apresentação, se houver;
   - os documentos que ficaram vazios, um por linha: "CPF vazio na vaga X da empresa Y (domínio Z): confirme na janela da extensão ou digite".

   Clique em enviar somente depois que ele confirmar.
6. **Registro final.** Depois do envio confirmado, chame `update_application` com status `aplicada`, o `resume_id`, a `salary_expectation` (pretensão como foi informada) e uma nota com a data e a plataforma.
   - **Testes e etapas depois do envio.** Se a página de confirmação (ou o e-mail dela) pedir teste técnico, coding challenge, teste de proficiência, questionário de perfil, vídeo gravado ou qualquer avaliação, a candidatura já está concluída: o seu trabalho acabou. Não faça nem inicie o teste (muitos têm cronômetro) e não espere o Thiago fazê-lo. Registre a pendência em `pending` (nome do teste, link e prazo, se houver), mantendo o status `aplicada`. Sem etapa extra, deixe `pending` vazio.
   - **Próxima vaga.** Com a candidatura registrada, siga para a próxima vaga do pedido sem esperar. Veja "Várias vagas" no [SKILL.md](SKILL.md).

## Abas abertas

Em lote, `max_open_tabs` é quantos formulários você deixa abertos antes de pausar e perguntar ao Thiago como seguir. Cada vaga deixada em `pendente_usuario` com o formulário aberto ocupa uma aba, tanto a pronta para envio quanto a que tem algo faltando.
- Chame `get_config` e leia `max_open_tabs` (padrão 12; ele muda com `set_config`). Se o Thiago disser na conversa quantas abas quer, grave com `set_config` antes de começar.
- Conte as abas de candidatura que você deixou abertas nesta conversa. Depois de um envio confirmado (`aplicada`), feche a aba da vaga. Nunca feche abas que você não abriu.
- Enquanto houver vagas no pedido e o número de abas abertas estiver abaixo do limite, siga para a próxima vaga, sem pausar.
- Ao chegar no limite (ou ao fim da lista), não abra outro formulário: faça a **revisão do lote**. Mostre uma linha por aba aberta: a vaga como link, o currículo anexado (ou o PDF a anexar, com nome e `windows_path`), a pretensão, as respostas abertas e o que falta. As prontas para envio vêm primeiro. Ela entra no resumo do lote ([SKILL.md](SKILL.md)). Pergunte quais enviar e o que fazer com as demais.
- Para cada vaga que o Thiago confirmar, clique em enviar, registre como `aplicada` (passo 6) e feche a aba. Com abas liberadas, continue o lote pelas vagas restantes, que seguem como `a_aplicar`.

## Campos novos do perfil

Todo dado pedido por um formulário que ainda não está no [perfil.md](perfil.md) nem no currículo geral passa a ser documentado, para que da próxima vez seja preenchido direto.

1. **Registrar o campo.** Chame `add_profile_field` com o rótulo como o formulário pede e, se o assunto combinar com uma seção existente (contato, respostas padrão), a `section`. Ela grava o campo no [perfil.md](perfil.md) e no [perfil.example.md](perfil.example.md), no formato certo; sem `section`, o campo vai para "Outros campos de formulário". Se a opção é de lista fechada (por exemplo, "Como soube da vaga?"), inclua as opções oferecidas no rótulo.
2. **Guardar a resposta.** Quando o Thiago responder, chame `add_profile_field` de novo com o mesmo rótulo e a resposta em `value`: ela troca o `<PREENCHER>` pela resposta.
3. **Dados sensíveis.** Para CPF, RG, passaporte, senhas e dados bancários, chame `add_profile_field` sem `value` (com `sensitive` true se o rótulo não deixar claro). O campo fica como `informar manualmente`, e o valor é digitado pelo Thiago no formulário. Documentos da lista do cofre (CPF, RG, CNH, PIS, CTPS, título de eleitor, passaporte, nome da mãe) podem ir para o cofre, e daí a extensão do Chrome os preenche: sugira ao Thiago cadastrar pelo terminal (`python -m vagas.sensitive set cpf`). Nunca peça o valor na conversa. Senhas e dados bancários ficam sempre manuais.

Se a tool der erro por não achar a pasta da Skill (por exemplo, na Skill instalada por zip no Desktop), mostre ao Thiago as linhas exatas a acrescentar em cada arquivo, no formato `- <rótulo>: <valor>`.

## Respostas em texto

Vale para cartas de apresentação, perguntas abertas e campos livres:
- **Idioma:** o mesmo do formulário. Em português, use acentuação e pontuação corretas.
- **Voz:** primeira pessoa, natural e direta, em texto corrido sem negrito.
- **Conteúdo:** quando couber, fale de crescimento profissional e aprendizado contínuo, e da conciliação entre trabalho e pesquisa (doutorado em andamento).
- **Fatos:** use somente fatos do currículo geral e do perfil, com os mesmos números, tecnologias e escopo de responsabilidade. Quando a pergunta pedir algo que não está nessas fontes, trate como bloqueio (passo 4).
