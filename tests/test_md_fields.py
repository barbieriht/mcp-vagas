"""Campos "- Rótulo: valor" dos arquivos pessoais: ler e trocar só os valores, preservando o resto."""

import os

import pytest

from vagas.md_fields import apply, parse, write_atomic

TEXT = """# Título

Texto livre com dois-pontos: não é campo.

## Contato
- Nome: Fulano de Tal
- LinkedIn: https://linkedin.com/in/fulano
- Data de nascimento: <PREENCHER: DD/MM/AAAA>

## Respostas
- Idiomas: português (nativo)
  - Em formulários com escala fixa, escolher a opção mais próxima.
- Diversidade (respostas usadas nos formulários):
  - Sexo: <...>
  - Raça/etnia: Prefiro não responder
- Incluir em bancos de talentos: sim
  - Valores aceitos: sim ou não.

## Valores aceitos
- Nome: qualquer texto
"""


def test_reads_items_by_section_with_sub_items_and_stops_at_accepted_values():
    items = parse(TEXT)

    assert [(i.id, i.value) for i in items] == [
        ("Contato/Nome", "Fulano de Tal"),
        ("Contato/LinkedIn", "https://linkedin.com/in/fulano"),
        ("Contato/Data de nascimento", "<PREENCHER: DD/MM/AAAA>"),
        ("Respostas/Idiomas", "português (nativo)"),
        ("Respostas/Diversidade (respostas usadas nos formulários)", ""),
        ("Respostas/Diversidade (respostas usadas nos formulários)/Sexo", "<...>"),
        ("Respostas/Diversidade (respostas usadas nos formulários)/Raça/etnia", "Prefiro não responder"),
        ("Respostas/Incluir em bancos de talentos", "sim"),
    ]
    idiomas = next(i for i in items if i.label == "Idiomas")
    talentos = next(i for i in items if i.label == "Incluir em bancos de talentos")
    assert idiomas.notes == ["Em formulários com escala fixa, escolher a opção mais próxima."]
    assert talentos.notes == ["Valores aceitos: sim ou não."]


def test_apply_changes_only_the_values_and_keeps_everything_else():
    changed = apply(TEXT, {"Contato/Nome": "Maria Teste",
                           "Respostas/Diversidade (respostas usadas nos formulários)/Sexo": "Prefiro não responder"})

    expected = (TEXT.replace("- Nome: Fulano de Tal", "- Nome: Maria Teste")
                .replace("  - Sexo: <...>", "  - Sexo: Prefiro não responder"))
    assert changed == expected


def test_ids_ignore_case_and_accents():
    assert "- Nome: Maria" in apply(TEXT, {"contato/NOME": "Maria"})


def test_unknown_field_is_an_error():
    with pytest.raises(KeyError):
        apply(TEXT, {"Contato/Apelido": "x"})


def test_values_with_line_breaks_are_refused():
    with pytest.raises(ValueError):
        apply(TEXT, {"Contato/Nome": "Maria\n- CPF: 123"})


def test_write_keeps_a_symlink_pointing_to_the_real_file(tmp_path):
    real = tmp_path / "skill" / "criterios.md"
    real.parent.mkdir()
    real.write_text("antes\n", encoding="utf-8")
    link = tmp_path / "dados" / "criterios.md"
    link.parent.mkdir()
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symlink exige privilégio neste sistema")

    write_atomic(link, "depois\n")

    assert link.is_symlink() and real.read_text(encoding="utf-8") == "depois\n"
    assert not list(real.parent.glob("*.tmp"))


def test_write_preserves_crlf_free_utf8(tmp_path):
    path = tmp_path / "perfil.md"

    write_atomic(path, "- Nome: Ção\n")

    assert path.read_bytes() == "- Nome: Ção\n".encode("utf-8")
    assert os.listdir(tmp_path) == ["perfil.md"]
