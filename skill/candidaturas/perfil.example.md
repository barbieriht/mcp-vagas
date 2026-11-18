# Dados para formulários

Fonte da verdade para experiência, idiomas e skills: o currículo geral aprovado no MCP "vagas".
Este arquivo guarda só o que não está no currículo ou respostas padrão de formulário.

## Contato e identificação
- Nome: Fulano de Tal
- Telefone: +55 (00) 00000-0000
- E-mail / login Google: fulano@example.com
- LinkedIn: https://linkedin.com/in/fulano
- GitHub: https://github.com/fulano
- Portfólio: <link do portfólio (Behance, site pessoal, itch.io...), ou "não tenho">
- Endereço: Rua Exemplo, 100, CEP 00000-000, Cidade - UF
- Naturalidade: Cidade - UF
- Data de nascimento: <PREENCHER: DD/MM/AAAA>

## Respostas padrão
- Idiomas: português (nativo), inglês (avançado), espanhol (básico)
  - Nível que você declara nos formulários (nativo, fluente, avançado, intermediário ou básico). A certificação fica em "Certificações de idiomas".
- Certificações de idiomas: inglês (B2, certificado), espanhol (A2.3, certificado)
  - Certificado e nível CEFR (A1 a C2). Vale para o currículo e para as perguntas que pedem certificação ou nível CEFR; as demais usam o nível de "Idiomas".
- Anos de experiência a declarar: calculado
  - "calculado" usa os anos somados das experiências do currículo geral, arredondados para o ano mais próximo. Escreva um número para declarar outro valor.
- Experiência CLT: nenhuma (apenas PJ e estágio)
- Área de atuação/estudo: escolher a opção ligada a inteligência artificial, se houver
- Parentes na empresa: não
- Trabalha atualmente na empresa da vaga: pelo currículo geral
  - Sim quando o currículo geral tem uma experiência em andamento na empresa da vaga; senão, Não. Vale para "Você trabalha na empresa X?", "É colaborador X?" e "Are you a current employee?".
- Já trabalhou na empresa da vaga: pelo currículo geral
  - Sim quando alguma experiência do currículo geral é na empresa da vaga; senão, Não. Empresas adquiridas por ela não entram na comparação.
- Foi indicado por alguém da empresa: <...>
  - Valores aceitos: Sim ou Não. Vale para todas as empresas ("Foi indicado?", "Alguém que trabalha nesta empresa indicou você?", "Were you referred?").
- Cargo público: nunca ocupou
- Aceita contratação no modelo PJ?: <...>
- Disponibilidade e interesse em contratação temporária (projeto de 2 meses)?: <...>
- Valor da última remuneração: <...>

## Diversidade e inclusão
Respostas usadas nos formulários; "Prefiro não responder" vale em todas. O Claude responde por estes campos e nunca deduz a resposta por nome, foto ou contexto.
- Possui deficiência: <...>
  - Valores aceitos: Sim, Não ou Prefiro não responder. Também decide a triagem: só com "Sim" as vagas exclusivas para PcD seguem.
- Cor/raça (IBGE): <...>
  - Valores aceitos: Branca, Preta, Parda, Amarela, Indígena ou Prefiro não responder.
- Sexo: <...>
- Identidade de gênero: <...>
- Orientação sexual: <...>

## Consentimentos
O que você autoriza nos formulários. Quem marca as caixas de termos é a opção "Quem marca os termos de uso e privacidade" do painel (`consent_mode`): a extensão do Chrome (padrão), o Claude ou você.
- Autorizar uso de dados para recrutamento (termos, privacidade, LGPD): <...>
  - Valores aceitos: autorizo ou não autorizo. Com "não autorizo", nenhuma caixa de termos é marcada, e a candidatura fica para você.
- Marketing e comunicações: <...>
  - Valores aceitos: sim ou não. Sem "sim", as caixas de marketing, comunicações e parceiros ficam desmarcadas.
- Incluir em bancos de talentos: <...>
  - Valores aceitos: sim ou não. Com "sim", a caixa de banco de talentos é marcada e o Claude responde "sim" quando o formulário pergunta.

## Outros campos de formulário
Campos pedidos por formulários que não se encaixam nas seções acima. Dados sensíveis: só o campo, com "informar manualmente", ou "no cofre (extensão do Chrome)" para documentos cadastrados no cofre (`python -m vagas.sensitive set <campo>`). Documento cadastrado no cofre vale mesmo se a linha disser "informar manualmente". Quem preenche esses documentos nos formulários é a extensão do Chrome, com a sua confirmação na primeira vez de cada empresa.
- <Rótulo do campo como o formulário pede>: <...>
- CPF: informar manualmente
- RG: informar manualmente
- Nos últimos 5 anos, você é ou foi Agente Público? (opções Sim, Não): <...>
- Você possui disponibilidade para viagens? (opções Sim, Não): <...>
- Você pertence a um dos grupos abaixo? (opções Pessoa preta, Pessoa parda, Indígena, Mulher, Pessoa com Deficiência, LGBTI+, Não pertenço a nenhum dos grupos, Prefiro não responder): <...>
- Are you willing to take a drug test, in accordance with local law/regulations? (opções Yes, No): <...>
- Travel Domestically (opções No, Yes): <...>
- Travel Internationally (opções No, Yes): <...>
- Minimum Pay: <...>
- Informe seu último salário Bruto: <...>
- Atua/atuava com plano de bônus no último emprego? (opções Sim, Não): <...>
- Você possui atualmente qualquer compromisso contratual com empregador anterior que possa impedir ou restringir sua contratação imediata, tais como cláusula de non-compete, garden leave ou obrigação similar? (opções Sim, Não): <...>
- Possui participação societária em alguma empresa? (opções Sim, Não): <...>
- Você tem conhecimento de qualquer fato que possa caracterizar risco de envolvimento com práticas de lavagem de dinheiro ou financiamento ao terrorismo? (opções Sim, Não): <...>
- Considere-me para outras posições e permita que minhas informações possam ser pesquisadas (banco de talentos) (opções Sim, Não): <...>
- Étnico/Racial | Você se autodeclara como uma pessoa (opções Amarela, Branca, Indígena, Não branca, Parda (Negra), Preta (Negra), Prefiro não informar, Outra): <...>
- Como ficou sabendo de nossas oportunidades? (opções Eventos, Indicação, Linkedin, Instagram, Outros): <...>
- Salário Atual: <...>
- How familiar are you with modeling in general? (opções I have never trained an ML model and I don’t know what is involved in the process, I understand the basics of modeling but I never trained a model myself, I have trained basic models myself and I’m familiar with learning theory, I have experience training models and I’m familiar with the details and possible pitfalls): <...>
- What is your experience working on different stages in the lifecycle of a machine learning model? (opções I do not have experience working with ML models, I have experience training and validating ML models, I have experience training, validating and deploying ML models, I have experience training, validating, deploying and operating ML models): <...>
- What is your experience with machine learning models used in a production environment, to drive business decisions? (opções I have experience working with ML models but not in a production environment, I have worked with ML models in a production environment in small to mid-sized companies or organizations, I have worked with ML models in a production environment in large-scale companies or organizations): <...>
- Are you legally authorized to work in the country where this position is located? (Brazil) (opções Yes, No): <...>
- Will you require sponsorship for employment visa status now or in the future? (opções Yes, No): <...>
- Do you require relocation for this role? (hybrid in São Paulo, Belo Horizonte, Campinas or Rio de Janeiro) (opções No, I don't require relocation, Yes, I require relocation and am willing to relocate, Yes, I require relocation but am not willing to relocate): <...>
- Have you participated in a hiring process with Nubank in the last 6 months? (opções Yes, No): <...>
- Check Yes or No to indicate your agreement to receive text message updates via SMS and/or WhatsApp from Nubank regarding your job application. (opções Yes - I consent to receiving SMS text messages, No - I do not consent to receiving SMS text messages): <...>
- Você possui algum(a) parente que trabalha na Vibra Energia? (opções Sim, Não): <...>
- Já trabalhou ou prestou serviços para a Vibra Energia por intermédio de alguma outra empresa? (opções Sim, Não): <...>
- Você é sócio(a) de alguma empresa que atualmente presta serviço para a Vibra Energia? (opções Sim, Não): <...>
- Você tem ou já teve algum contato com broker que atue em mercados correlatos ao da Vibra Energia? (opções Sim, Não): <...>
- Você é uma pessoa politicamente exposta? (opções Sim, Não): <...>
- Você possui participação ou é titular de alguma empresa que esteja com CNPJ ativo? (opções Sim, Não): <...>
