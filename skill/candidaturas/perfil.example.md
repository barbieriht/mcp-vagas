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
