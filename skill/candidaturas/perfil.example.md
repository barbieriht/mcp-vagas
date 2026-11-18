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
- Idiomas: português (nativo), inglês intermediário-avançado (B2, certificado), espanhol básico (A2.3, certificado)
  - Em formulários com escala fixa, escolher a opção mais próxima de B2 / A2 sem arredondar para cima.
- Anos de experiência a declarar: calculado
  - "calculado" usa os anos somados das experiências do currículo geral, arredondados para o ano mais próximo. Escreva um número para declarar outro valor.
- Experiência CLT: nenhuma (apenas PJ e estágio)
- Área de atuação/estudo: escolher a opção ligada a inteligência artificial, se houver
- Parentes na empresa: não
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
- Você já foi empregado(a) do Banco Bradesco S.A. ou de empresas do conglomerado econômico? (opções Sim, atuei como jovem aprendiz, Sim, atuei como estagiário(a), Sim, atuei em cargo efetivo, Não atuei): <...>
- Você tem conhecimento de qualquer fato que possa caracterizar risco de envolvimento com práticas de lavagem de dinheiro ou financiamento ao terrorismo? (opções Sim, Não): <...>
- Considere-me para outras posições e permita que minhas informações possam ser pesquisadas (banco de talentos) (opções Sim, Não): <...>
- Étnico/Racial | Você se autodeclara como uma pessoa (opções Amarela, Branca, Indígena, Não branca, Parda (Negra), Preta (Negra), Prefiro não informar, Outra): <...>
- Como ficou sabendo de nossas oportunidades? (opções Eventos, Indicação, Linkedin, Instagram, Outros): <...>
- Alguém que trabalha nesta empresa indicou você para esta vaga? (opções Sim, Não): <...>
- Você trabalha na empresa Vibra Energia? (opções Sim, Não): <...>
- Salário Atual: <...>
- É colaborador Luza Group? (opções Sim, Não): <...>
- Foi indicado? (opções Não, Sim): <...>
- How familiar are you with modeling in general? (opções I have never trained an ML model and I don’t know what is involved in the process, I understand the basics of modeling but I never trained a model myself, I have trained basic models myself and I’m familiar with learning theory, I have experience training models and I’m familiar with the details and possible pitfalls): <...>
- What is your experience working on different stages in the lifecycle of a machine learning model? (opções I do not have experience working with ML models, I have experience training and validating ML models, I have experience training, validating and deploying ML models, I have experience training, validating, deploying and operating ML models): <...>
- What is your experience with machine learning models used in a production environment, to drive business decisions? (opções I have experience working with ML models but not in a production environment, I have worked with ML models in a production environment in small to mid-sized companies or organizations, I have worked with ML models in a production environment in large-scale companies or organizations): <...>
- Are you legally authorized to work in the country where this position is located? (Brazil) (opções Yes, No): <...>
- Will you require sponsorship for employment visa status now or in the future? (opções Yes, No): <...>
- Do you require relocation for this role? (hybrid in São Paulo, Belo Horizonte, Campinas or Rio de Janeiro) (opções No, I don't require relocation, Yes, I require relocation and am willing to relocate, Yes, I require relocation but am not willing to relocate): <...>
- Have you previously worked at Nubank or any company acquired by Nubank? (opções Yes, No): <...>
- Have you participated in a hiring process with Nubank in the last 6 months? (opções Yes, No): <...>
- Check Yes or No to indicate your agreement to receive text message updates via SMS and/or WhatsApp from Nubank regarding your job application. (opções Yes - I consent to receiving SMS text messages, No - I do not consent to receiving SMS text messages): <...>
- Você possui algum(a) parente que trabalha na Vibra Energia? (opções Sim, Não): <...>
- Já trabalhou ou prestou serviços para a Vibra Energia por intermédio de alguma outra empresa? (opções Sim, Não): <...>
- Você é sócio(a) de alguma empresa que atualmente presta serviço para a Vibra Energia? (opções Sim, Não): <...>
- Você tem ou já teve algum contato com broker que atue em mercados correlatos ao da Vibra Energia? (opções Sim, Não): <...>
- Você é uma pessoa politicamente exposta? (opções Sim, Não): <...>
- Você possui participação ou é titular de alguma empresa que esteja com CNPJ ativo? (opções Sim, Não): <...>
