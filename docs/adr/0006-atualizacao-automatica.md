# Atualização automática a cada conversa

O servidor roda de uma cópia estável instalada num venv, separada do clone. Sem um passo manual (`git pull` e rodar o instalador de novo), cada máquina ficava na versão do dia em que o instalador rodou. Em 2026-11-18, outra máquina ainda gerava currículos com o padrão de nome antigo, de antes de 2026-11-16. Até esta máquina estava atrás do próprio repositório.

Agora, a cada sessão, o servidor roda `vagas.auto_update` numa thread, sem atrasar o protocolo:

- **Puxa só o que é seguro:** `git fetch` e `git merge --ff-only` da `main`. Isso só acontece se o clone está na `main`, sem arquivos rastreados editados e sem commits que não estão no GitHub. Os arquivos pessoais ficam fora do git e não contam. Com trabalho local, nada é puxado nem reinstalado, nem a versão da branch atual: o resultado diz o que fazer à mão.
- **Reinstala quando o clone e a cópia divergem:** a reinstalação usa o `uv`, no Python do próprio servidor. A referência é o commit gravado em `instalado.json`, ao lado do venv, pelos instaladores e pela própria atualização. Uma cópia de antes desta mudança, sem o registro, é reinstalada uma vez. Numa instalação editável (desenvolvimento), só puxa.
- **Ajusta os arquivos pessoais:** perfil, critérios e política recebem os campos de primeiro nível que o `.example.md` ganhou desde a versão instalada. Os campos são comparados pelo exemplo antigo, não pelo arquivo do usuário, e por isso um campo que ele apagou não volta. No perfil, o campo entra com `<PREENCHER>`, e o `get_profile` pede a resposta. Nos critérios e na política, entra vazio, e os leitores tratam o vazio como a linha ausente; um teste cobre cada campo dos exemplos. Mudanças de formato continuam nas migrações do `get_profile`, que pedem confirmação.
- **Conta ao usuário:** o resultado com novidade fica em `atualizacao.json` até o `get_config` o mostrar uma vez, mesmo que a conversa que o pediu tenha começado antes do fim da atualização. As instruções do servidor pedem o `get_config` no começo de cada conversa. O que só o usuário pode fazer vai em `actions`: conversa nova, recarregar a extensão, reenviar o zip da Skill do Desktop ou rodar os instaladores.
- **Nunca atrapalha o protocolo:** os subprocessos têm stdin fechado e saída capturada, e um lock evita duas sessões instalando ao mesmo tempo. Falhas viram aviso, e o servidor sobe mesmo assim.

Pode ser desligada com `auto_update = "nao"` no `config.toml` (ou `VAGAS_AUTO_UPDATE`).

## Alternativas consideradas

- **Só avisar que há versão nova:** o usuário continuaria dependendo de um passo manual que, na prática, ficou esquecido.
- **Reiniciar o servidor na versão nova no meio da sessão:** no stdio, trocar o processo derruba a conexão com o cliente. A versão nova vale a partir da próxima conversa.
- **Instalar direto do GitHub (`uv pip install git+https://...`):** a Skill, a extensão e os arquivos pessoais vivem no clone, então o clone precisa andar junto.
- **Acrescentar os campos novos com o valor do exemplo:** os exemplos trazem dados fictícios (como "Empresa Exemplo" nas empresas ignoradas), que mudariam a triagem sem o usuário saber.
