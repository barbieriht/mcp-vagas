# Cofre de dados sensíveis cifrado com a DPAPI do Windows

Os dados sensíveis liberados pelo usuário (CPF, RG e similares, lista fechada em `vagas.sensitive.ALLOWED_FIELDS`) ficam em `cofre.json`, na pasta de dados. Cada valor é cifrado pela DPAPI do Windows no escopo do usuário, chamada pelo `powershell.exe` a partir do WSL, com os dados passando pela entrada padrão.

Escolhemos a DPAPI porque atende aos três critérios da spec #100: não guardar texto puro, funcionar tanto pelo Claude Code quanto pelo Claude Desktop (os dois rodam o servidor dentro do WSL) e não pedir senha a cada uso. O preço é depender do Windows: fora do WSL, o cofre não abre.

## Alternativas consideradas

- **Secret Service (chaveiro do Linux):** o Desktop chama o servidor pelo `wsl.exe`, sem sessão gráfica para destrancar o chaveiro.
- **Gerenciador de Credenciais do Windows:** exigiria P/Invoke via PowerShell para ler as credenciais, o que é mais frágil, sem ganho de segurança sobre a DPAPI.
- **Arquivo cifrado com chave em arquivo ou em variável de ambiente:** a chave ficaria tão exposta quanto o valor.

## Consequências

- O cadastro é só pelo terminal (`python -m vagas.sensitive set <campo>`, com valor sem eco), e o valor nunca passa pela conversa no cadastro.
- Na entrega para preencher um formulário, o valor passa pelo contexto do modelo. As condições de entrega e a confirmação do usuário (#102) restringem isso a formulários legítimos.
- Apagar o perfil do Windows ou trocar de máquina torna o cofre ilegível. Nesse caso é preciso cadastrar de novo; não há sincronização.
