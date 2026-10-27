# Candidatar-se a uma vaga

A candidatura termina num destes dois estados:
- `aplicada`: o Thiago confirmou o envio e o formulário foi enviado;
- `pendente_usuario`: algo bloqueou o envio, e o `pending` descreve exatamente o que falta.

## Passos

1. **Triagem.** Faça a triagem do [SKILL.md](SKILL.md). Siga adiante só com a vaga em `a_aplicar` ou com uma `pendente_usuario` sendo retomada.
2. **Currículo personalizado.** Chame `get_master_resume` e monte a seleção para a vaga:
   - destaque as experiências e parágrafos ligados aos termos de `match_terms` (`matched`);
   - reescreva parágrafos longos como bullets objetivos, em inglês;
   - descreva cada responsabilidade com o mesmo verbo e o mesmo escopo do currículo geral.

   Chame `create_tailored_resume` com o `application_id`. Se a validação rejeitar algo, ajuste a seleção ou o texto ao que o currículo geral diz e gere de novo. Guarde o caminho do PDF e o id do currículo.
3. **Formulário.**
   - **Acesso:** abra a vaga no navegador. Prefira aplicar ou entrar com LinkedIn; senão, entre com a conta Google do [perfil.md](perfil.md).
   - **Dados:** carregue o [perfil.md](perfil.md) e preencha com os dados dele e do currículo geral.
   - **Anexo:** anexe o PDF personalizado.
   - **Pretensão salarial:** use o `value_to_inform` da avaliação salarial. Se não estiver à mão, ele está em `salary_evaluation`, no `get_history`.
   - **Consentimentos:** marque os de privacidade e LGPD exigidos pelo formulário.
4. **Bloqueios.** Se o formulário exigir criar conta com senha, CPF, outro documento ou dado sensível, ou uma resposta que não está no perfil nem no currículo:
   - preencha todo o resto e deixe a aba aberta;
   - chame `update_application` com status `pendente_usuario`, `pending` listando cada item que falta e o `resume_id`;
   - avise o Thiago e encerre a vaga.
5. **Revisão antes do envio.** Pare antes do botão final de envio. Mostre ao Thiago:
   - a vaga;
   - o currículo anexado;
   - a pretensão informada;
   - as respostas abertas.

   Clique em enviar somente depois que ele confirmar.
6. **Registro final.** Depois do envio confirmado, chame `update_application` com status `aplicada`, `pending` vazio, o `resume_id` e uma nota com a data e a plataforma.

## Respostas em texto

Vale para cartas de apresentação, perguntas abertas e campos livres:
- **Idioma:** o mesmo do formulário. Em português, use acentuação e pontuação corretas.
- **Voz:** primeira pessoa, natural e direta, em texto corrido sem negrito.
- **Conteúdo:** quando couber, fale de crescimento profissional e aprendizado contínuo, e da conciliação entre trabalho e pesquisa (doutorado em andamento).
- **Fatos:** use somente fatos do currículo geral e do perfil, com os mesmos números, tecnologias e escopo de responsabilidade. Quando a pergunta pedir algo que não está nessas fontes, trate como bloqueio (passo 4).
