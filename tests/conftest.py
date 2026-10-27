import pytest

from vagas.db import connect
from vagas.repo import Repo
from vagas.server import build_server


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "vagas.db"


@pytest.fixture
def repo(db_path):
    conn = connect(db_path)
    yield Repo(conn)
    conn.close()


@pytest.fixture
def server(db_path):
    return build_server(db_path)


@pytest.fixture
def anyio_backend():
    return "asyncio"
