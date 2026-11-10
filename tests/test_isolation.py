"""Os testes nunca enxergam os dados reais do usuário (banco, cofre, perfil, política, critérios)."""

from pathlib import Path

from vagas.db import default_db_path
from vagas.salary_policy import default_policy_path
from vagas.sensitive import default_vault_path
from vagas.triage import default_criteria_path

REAL_DATA = Path.home() / ".local/share/vagas"


def test_default_paths_never_point_to_the_real_data_folder():
    for path in (default_db_path(), default_vault_path(), default_policy_path(), default_criteria_path()):
        assert REAL_DATA not in path.parents and path.parent != REAL_DATA, path
