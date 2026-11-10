# Extensão e cofre no Linux e no macOS

A extensão do Chrome também funciona fora do Windows (#170). O host de native messaging é o mesmo `vagas.autofill_host`. O que muda é onde o cofre guarda os documentos, escolhido em `vagas.sensitive.default_backend()`:

- **Windows e WSL:** DPAPI ([ADR 0001](0001-cofre-de-dados-sensiveis-com-dpapi.md)).
- **Linux:** o chaveiro do sistema (Secret Service: GNOME Keyring, KWallet), pelo `secret-tool`. O `cofre.json` guarda só um identificador aleatório por campo, e o valor fica no chaveiro. O valor vai pela entrada padrão e nunca aparece na linha de comando. Ao trocar ou apagar um campo, o item antigo sai do chaveiro.
- **Sem chaveiro (Linux sem `secret-tool`) e macOS:** sem cofre (`NoVaultBackend`). O cadastro explica o motivo, e a extensão continua anexando o currículo e marcando os termos de uso. Os documentos ficam com o usuário.

O instalador do Claude Code (`scripts/instalar_claude_code.py`), fora do WSL, registra o manifest do host nas pastas `NativeMessagingHosts` dos navegadores instalados (Chrome, Chromium, Edge e Brave; Chrome se nenhum for encontrado). O host é um script `sh` que roda a cópia estável com o mesmo `VAGAS_DB` do registro do MCP. A Skill continua sendo achada pelo symlink da política salarial ao lado do banco.

## Alternativas consideradas

- **Pacote `keyring`:** cobriria Linux e macOS numa API só, mas é dependência nova, e o `secret-tool` resolve o Linux sem ela. Fica para quando o macOS entrar.
- **Keychain do macOS pelo `security`:** `add-generic-password -w <valor>` põe o valor na linha de comando, visível para outros processos. O modo interativo (`security -i`, comandos pela entrada padrão) evitaria isso, mas não há como testar o macOS aqui, e um cofre sem teste não entra. Fica como continuação.
- **Cifrar com uma chave guardada no chaveiro:** exigiria uma biblioteca de criptografia (a biblioteca padrão não tem AES).
- **Por que o Secret Service foi descartado na ADR 0001 e agora entra:** lá, o Claude Desktop chamava o servidor pelo `wsl.exe`, sem sessão gráfica para destrancar o chaveiro. No Linux nativo, o Chrome roda o host dentro da sessão do usuário, com o chaveiro já desbloqueado.

## Consequências

- O cofre não é portátil entre sistemas: um `cofre.json` do Linux só tem identificadores do chaveiro daquela máquina.
- Teste real: `VAGAS_TEST_SECRET_SERVICE=1` roda o cofre e a extensão de ponta a ponta contra um chaveiro desbloqueado. Sem chaveiro, um teste ponta a ponta confirma o anexo e os termos com o cofre vazio.
