# Documentos do cofre preenchidos por uma extensão do Chrome, não pelo modelo

O Claude in Chrome se recusa a digitar documentos de identidade em formulários, mesmo com autorização do usuário, e isso não é configurável. O preenchimento passa a ser de uma extensão local do Chrome (`extension/`), que conversa por native messaging com um host do mcp-vagas (`python -m vagas.autofill_host`, rodando no WSL pelo `wsl.exe`). O modelo não vê nem decide nada: deixa os campos vazios e, se continuarem vazios na revisão, os lista como pendência.

A decisão de quem recebe o documento fica numa regra fixa e numa confirmação humana, não no julgamento do modelo. A regra fixa é https, sites de vagas conhecidos, domínios extras do config e sites de candidaturas abertas. A confirmação é uma janela da extensão na primeira vez de cada empresa. Essa janela fica fora da página e fora do alcance do agente que controla a aba. Nos agregadores (LinkedIn, Indeed...), a URL não identifica a empresa, então a confirmação vale por vaga e nunca fica guardada.

## Alternativas consideradas

- **Tool do MCP que injeta os valores na página:** o servidor não alcança a aba do Claude in Chrome. Controlar o Chrome por depuração remota exige um perfil separado (o Chrome 136+ bloqueia no perfil padrão) e abre a porta a qualquer processo local. Além disso, quem chamaria a tool seria o modelo, que recusa pelo mesmo motivo.
- **`get_sensitive_field` entregando o valor ao modelo (ADR 0001):** o modelo do navegador recusa digitar. A tool foi removida, junto com `sensitive_autofill`.
- **Publicar na Chrome Web Store:** daria instalação com um clique e atualização automática, mas exige conta de desenvolvedor e revisão a cada versão, sem ganho para um único usuário.

## Consequências

- O usuário carrega a extensão uma vez (Modo do desenvolvedor → Carregar sem compactação). O Chrome não permite instalação silenciosa de extensões fora da loja. O id é fixo pela `key` do manifest, e o host só aceita esse id.
- Os valores não passam mais pelo contexto do modelo, nem no cadastro nem no uso.
- A extensão observa todas as páginas https, mas só consulta o host quando acha um campo com cara de documento. A decisão final é sempre do host.
- Num site de plataforma (ex.: `gupy.io`), uma vaga falsa publicada por terceiros também receberia o documento depois da confirmação. A confirmação por empresa mostra o endereço para o usuário julgar.

## Termos de uso (#155)

A extensão também marca o aceite de termos de uso e da política de privacidade, porque o Claude in Chrome também recusa essa marcação. A regra fica na mesma classificação no host, e a confirmação por empresa passa a mostrar o texto de cada termo. A aceitação continua sendo do usuário, dada naquela janela. Ficam de fora, por regra, marketing, parceiros, banco de talentos e declarações de fato: uma declaração marcada automaticamente pode ser falsa. Caixas que misturam termos e marketing também ficam de fora. O `autofill.log` guarda o texto exato aceito, como comprovante.

## Anexo do currículo (#157)

A ferramenta de upload do Claude in Chrome não alcança arquivos do disco. A extensão anexa ao campo de currículo o PDF personalizado da candidatura daquela página, lido do caminho registrado por `create_tailored_resume` (`resumes.pdf_path`, na pasta `resume_out`), sem cópia. O host escolhe a candidatura pela URL da página. Quando há mais de uma candidatura possível, quem escolhe é o usuário, na janela de confirmação. A aprovação permanente passou a guardar escopos (documentos, termos, currículo) e só cobre o que a janela mostrou. O arquivo vai em base64 numa mensagem de native messaging, limitada a 1 MB; acima de 700 KB, o anexo fica com o usuário.

## Aprovação por plataforma

Confirmar empresa por empresa pesa em plataformas onde o usuário se candidata a muitas empresas, como a Gupy, que dá um subdomínio a cada uma. A opção `autofill_platforms` do config (desligada por padrão) faz um "Permitir sempre" valer para a plataforma inteira: a chave da aprovação passa a ser o domínio da plataforma (`gupy.io`). O risco aceito é o da vaga falsa citado acima: numa plataforma aprovada, o documento iria para qualquer empresa dela sem nova confirmação. Ficou restrito às plataformas de recrutamento conhecidas, onde quem publica é cliente da plataforma; agregadores continuam confirmando por vaga. A janela ainda aparece para escopos não aprovados e para escolher entre currículos, e a busca do currículo continua sendo por empresa, para não anexar o currículo de uma candidatura a outra empresa da mesma plataforma.
