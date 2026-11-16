"""Respostas de formulário tiradas do perfil: a opção do formulário que equivale ao valor do perfil, sem adivinhar."""

import pytest
from mcp import Client

from test_sensitive import FakeBackend
from vagas.db import connect
from vagas.form_answers import resolve
from vagas.profile_fields import ProfileFiles
from vagas.repo import Repo
from vagas.sensitive import Vault
from vagas.server import build_server

pytestmark = pytest.mark.anyio

PERFIL = """\
# Dados para formulários

## Contato e identificação
- Nome: Maria Teste

## Respostas padrão
- Idiomas: português (nativo), inglês intermediário-avançado (B2, certificado), espanhol básico (A2.3, certificado)
  - Em formulários com escala fixa, escolher a opção mais próxima de B2 / A2 sem arredondar para cima.
- Experiência CLT: nenhuma (apenas PJ e estágio)
- Aceita contratação no modelo PJ?: sim
- Como soube da vaga?: LinkedIn
- Valor da última remuneração: <PREENCHER>

## Diversidade e inclusão
- Possui deficiência: Não
- Cor/raça (IBGE): Branca
- Sexo: Masculino
- Identidade de gênero: Homem cisgênero
- Orientação sexual: Prefiro não responder

## Outros campos de formulário
- CPF: no cofre (extensão do Chrome)
"""


@pytest.fixture
def skill(tmp_path, monkeypatch):
    folder = tmp_path / "skill"
    folder.mkdir()
    (folder / "perfil.md").write_text(PERFIL, encoding="utf-8")
    (folder / "perfil.example.md").write_text(PERFIL, encoding="utf-8")
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(folder))
    return folder


@pytest.fixture
def profile(skill):
    return ProfileFiles(skill).get_profile(vault_fields=["cpf"])


@pytest.mark.parametrize("question, options, answer", [
    ("Cor/Raça", ["Branco", "Preto", "Pardo", "Amarelo", "Indígena", "Prefiro não informar"], "Branco"),
    ("Qual a sua etnia?", ["Branca", "Negra", "Asiática"], "Branca"),
    ("Sexo", ["Masculino", "Feminino"], "Masculino"),
    ("Gênero", ["Homem", "Mulher", "Outro"], "Homem"),  # identidade "Homem cisgênero" -> a opção ampla
    ("Identidade de gênero", ["Homem cis", "Mulher cis", "Homem trans", "Não binário"], "Homem cis"),
    ("Você é pessoa com deficiência (PcD)?", ["Sim", "Não"], "Não"),
    ("Possui alguma deficiência?", ["Possuo deficiência", "Não possuo deficiência", "Prefiro não responder"],
     "Não possuo deficiência"),
    ("Orientação sexual", ["Heterossexual", "Homossexual", "Bissexual", "Não desejo informar"], "Não desejo informar"),
])
def test_diversity_questions_pick_the_equivalent_option(profile, question, options, answer):
    result = resolve(profile, question, options)

    assert result["answer"] == answer
    assert result["source"]["kind"] == "perfil" and result["source"]["field"]


def test_an_option_list_without_the_equivalent_answer_blocks(profile):
    result = resolve(profile, "Orientação sexual", ["Heterossexual", "Homossexual", "Bissexual"])

    assert result["blocked"] and "Prefiro não responder" in result["reason"]
    assert "answer" not in result


def test_the_option_is_never_guessed_from_a_broad_list(profile):
    # "Negra" junta preta e parda no IBGE: não é a resposta de quem se declara branca, nem de nenhuma outra
    result = resolve(profile, "Raça", ["Negra", "Não negra"])

    assert result["blocked"]


@pytest.mark.parametrize("question, options, answer", [
    ("Você possui experiência em regime CLT?", ["Sim", "Não"], "Não"),
    ("Aceita contratação no modelo PJ?", ["Sim", "Não"], "Sim"),
    ("Como soube da vaga?", ["Indicação", "LinkedIn", "Site da empresa"], "LinkedIn"),
    ("Como soube da vaga?", [], "LinkedIn"),
])
def test_other_profile_fields_answer_by_label(profile, question, options, answer):
    assert resolve(profile, question, options)["answer"] == answer


@pytest.mark.parametrize("question, options, answer", [
    ("Nível de inglês", ["Básico", "Intermediário", "Avançado", "Fluente"], "Intermediário"),  # B2: não sobe a C1
    ("English level", ["A1", "A2", "B1", "B2", "C1", "C2"], "B2"),
    ("Nível de espanhol", ["Básico", "Intermediário", "Avançado"], "Básico"),
    ("Inglês", ["Intermediário", "Intermediário avançado", "Avançado"], "Intermediário avançado"),
])
def test_language_scales_take_the_closest_level_without_rounding_up(profile, question, options, answer):
    result = resolve(profile, question, options)

    assert result["answer"] == answer and result["source"]["field"] == "Idiomas"


def test_a_level_below_every_option_blocks(profile):
    assert resolve(profile, "Nível de espanhol", ["Avançado", "Fluente"])["blocked"]


def test_fields_still_to_fill_and_documents_block_without_creating_anything(profile):
    pending = resolve(profile, "Valor da última remuneração", [])
    document = resolve(profile, "CPF", [])

    assert pending == {"blocked": True, "missing_field": "Valor da última remuneração", "existing": True,
                       "reason": pending["reason"]}
    assert document["blocked"] and "extensão" in document["reason"] and "missing_field" not in document


def test_a_question_the_profile_does_not_have_asks_for_a_new_field(profile):
    result = resolve(profile, "Qual o seu tamanho de camiseta?", ["P", "M", "G"])

    assert result == {"blocked": True, "missing_field": "Qual o seu tamanho de camiseta? (opções P, M, G)",
                      "existing": False, "section": None, "reason": result["reason"]}


def test_a_colon_in_the_question_never_breaks_the_profile_line(profile):
    assert resolve(profile, "Disponibilidade: início imediato?", ["Sim", "Não"])["missing_field"] \
        == "Disponibilidade - início imediato? (opções Sim, Não)"


def test_diversity_questions_wait_for_a_pending_migration_without_creating_fields(skill):
    old = PERFIL.split("## Diversidade e inclusão")[0] + "- Diversidade:\n  - Sexo Masculino\n  - Branco/Latino\n"
    (skill / "perfil.md").write_text(old, encoding="utf-8")
    profile = ProfileFiles(skill).get_profile(vault_fields=[])

    result = resolve(profile, "Raça/cor", ["Branca", "Parda"])

    assert result["blocked"] and "apply_profile_migration" in result["reason"] and "missing_field" not in result


def test_a_missing_diversity_question_gets_its_field_in_the_diversity_section(skill):
    (skill / "perfil.md").write_text(PERFIL.replace("- Possui deficiência: Não\n", ""), encoding="utf-8")
    profile = ProfileFiles(skill).get_profile(vault_fields=[])

    result = resolve(profile, "Você é PcD?", ["Sim", "Não"])

    assert result["missing_field"] == "Possui deficiência" and result["section"] == "Diversidade e inclusão"


@pytest.mark.parametrize("options, answer", [
    ([], "4"),
    (["Menos de 1 ano", "1 a 3 anos", "3 a 5 anos", "Mais de 5 anos"], "3 a 5 anos"),
    (["0-2", "2-4", "4-6", "6+"], "4-6"),
    (["1+", "3+", "5+"], "3+"),
])
def test_years_of_experience_come_from_the_profile_calculation(profile, options, answer):
    result = resolve(profile, "Quantos anos de experiência você tem na área?", options, years=4)

    assert result["answer"] == answer and result["source"]["kind"] == "experiencia"


def test_salary_expectation_comes_from_the_application(profile):
    assert resolve(profile, "Pretensão salarial", [], salary=11800)["answer"] == "11800"
    assert resolve(profile, "Pretensão salarial (CLT)", ["Até R$ 8.000", "R$ 8.001 a R$ 12.000",
                                                         "Acima de R$ 12.000"], salary=11800)["answer"] \
        == "R$ 8.001 a R$ 12.000"
    assert resolve(profile, "Pretensão salarial", [])["blocked"]


async def test_the_tool_answers_and_registers_a_missing_field_once(db_path, skill):
    conn = connect(db_path)
    app = Repo(conn).add_application(company="Acme", role="Cientista de Dados", source="gupy", status="a_aplicar",
                                     url="https://acme.gupy.io/jobs/1")["application"]
    conn.execute("UPDATE applications SET salary_ask = 9500 WHERE id = ?", (app["id"],))
    conn.commit()
    conn.close()
    async with Client(build_server(db_path, vault=Vault(skill / "cofre.json", FakeBackend()))) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        race = (await client.call_tool("resolve_form_answer", {"question": "Raça/cor", "options": ["Branca", "Parda"]}))
        salary = (await client.call_tool("resolve_form_answer", {"question": "Pretensão salarial",
                                                                 "application_id": app["id"]}))
        first = (await client.call_tool("resolve_form_answer", {"question": "Tamanho de camiseta",
                                                                "options": ["P", "M"]})).structured_content
        again = (await client.call_tool("resolve_form_answer", {"question": "Tamanho de camiseta",
                                                                "options": ["P", "M"]})).structured_content

    assert race.structured_content["answer"] == "Branca"
    assert salary.structured_content["answer"] == "9500"
    assert first["missing_field"] == again["missing_field"] == "Tamanho de camiseta (opções P, M)"
    assert first["created"] is True and again["created"] is False
    perfil = (skill / "perfil.md").read_text(encoding="utf-8")
    assert perfil.count("- Tamanho de camiseta (opções P, M): <PREENCHER>") == 1
    assert "add_profile_field" in tools["resolve_form_answer"].description
