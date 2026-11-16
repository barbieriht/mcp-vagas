# Aprovação por plataforma e consentimento de privacidade na extensão

Nos ATS multiempresa, a empresa é só um subdomínio ou um caminho de um domínio comum (`cielo.inhire.app`, `bradesco.csod.com`, `boards.greenhouse.io/acme`), e a página é a mesma em todas. Pedir a confirmação empresa por empresa interrompia os lotes sem proteger nada a mais. Agora a chave da aprovação é a plataforma, e um "Permitir sempre" vale para todas as empresas dela.

- **Plataformas padrão:** valem mesmo sem configuração (`autofill.DEFAULT_PLATFORMS`): `gupy.io`, `inhire.app`, `csod.com`, `factorialhr.com.br`, `myworkdayjobs.com`, `greenhouse.io`, `lever.co`, `smartrecruiters.com` e `recruitee.com`. Cada uma foi conferida:
  - `gupy.io`, `inhire.app` e `csod.com` aparecem em vagas reais da base;
  - `factorialhr.com.br` foi vista numa candidatura;
  - as outras pelo formato público de uma página por empresa num domínio comum.
- **Configuração:** `autofill_platforms` acrescenta plataformas (só das listas conhecidas em `autofill.py`), e `-dominio` tira uma padrão. Quem já tinha `gupy.io` configurado não perde nada.
- **Casamento:** por sufixo de domínio (`host == plataforma` ou termina em `"." + plataforma`), nunca por substring. `inhire.app.evil.com` e `evilinhire.app` não casam.
- **O que a aprovação cobre:** na plataforma inteira, "Permitir sempre" vale para documentos do cofre, termos, banco de talentos (só com "sim" no perfil) e o anexo do currículo. Na aprovação por empresa, continua valendo só para o que estava na tela.
- **O currículo continua sendo da empresa:** a aprovação da plataforma não deixa o PDF de uma vaga ir para o formulário de outra empresa. O currículo é sempre o da candidatura daquela página.

## Consentimento de privacidade

A caixa de privacidade segue a mesma confiança dos outros campos: site de vagas conhecido, plataforma ou o site de uma candidatura aberta (inclusive o `form_url`). Ela também segue a mesma confirmação. Não há uma permissão à parte que valha em qualquer site. A extensão reconhece:

- política, aviso ou declaração de privacidade, LGPD e tratamento ou processamento de dados pessoais, em português e inglês;
- rótulos que só dizem "Concordo", "Aceito" ou "I agree": o texto do aceite vem do bloco logo antes da caixa;
- caixas nativas escondidas sob um componente sem `<label>`;
- etapas de SPA renderizadas depois de "Avançar".

Marketing, newsletter, alertas de vagas por e-mail, parceiros e banco de talentos sem "sim" no perfil continuam desmarcados.

## Alternativas consideradas

- **Consentimento de privacidade em qualquer site de candidatura:** reconhecer "site de candidatura" por heurística amplia permissões sem uma lista explícita, e foi descartado.
- **Oracle Recruiting Cloud por assinatura (`/sites/<site>/job/<id>/apply` e marcas do DOM):** ele roda em domínio da própria empresa (`explore-jobs.ciklum.com`), e a assinatura poderia ser imitada por qualquer site. A aprovação nesses casos continua por site (o domínio da empresa), e o site entra quando vira o `form_url` de uma candidatura.
- **Só `gupy.io` aprovada por inteiro, como antes:** a aprovação era pedida empresa por empresa nas plataformas iguais.

## Consequências

- **Risco aceito:** uma empresa qualquer da plataforma recebe o CPF depois de uma única aprovação naquela plataforma. Para pedir a aprovação empresa por empresa numa delas, configure `-dominio`.
- **Aprovações antigas:**
  - nas plataformas padrão, as aprovações por empresa (`cielo.inhire.app`) deixam de ser consultadas, porque a chave passa a ser `inhire.app`, e a primeira aprovação na plataforma é pedida uma vez;
  - as aprovações que já estavam na chave da plataforma (`gupy.io`, `csod.com`) valem só para o que cobriam; o que faltar é pedido uma vez, e daí em diante a aprovação cobre tudo.
