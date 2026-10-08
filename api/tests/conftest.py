import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from pocketscan_api.config import get_settings
from pocketscan_api.db import get_engine, get_session
from pocketscan_api.main import app

API_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    """The app wired to the per-test session, so nothing persists."""
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. Run scripts/init-and-run-local-postgresql.py "
            "and export the URL it prints."
        )
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        raise RuntimeError(
            f"Refusing to run: database {database!r} does not end in '_test', "
            "and the tests drop every table."
        )
    return url


@pytest.fixture(scope="session", autouse=True)
def _point_app_at_test_database() -> Iterator[None]:
    """Make settings, the app engine and Alembic's env.py use the test database."""
    patch = pytest.MonkeyPatch()
    patch.setenv("POCKETSCAN_DATABASE_URL", _test_database_url())
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    patch.undo()
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture(scope="session")
def alembic_cfg() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    # script_location is relative to the working directory, so make it absolute.
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    return config


@pytest.fixture(scope="session")
def engine(alembic_cfg: Config) -> Iterator[Engine]:
    """The test database, freshly migrated to head."""
    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session in a transaction that is rolled back after each test."""
    with engine.connect() as connection:
        transaction = connection.begin()
        # create_savepoint lets code under test call commit() without
        # really committing; it commits to a savepoint instead.
        with Session(connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


@pytest.fixture
def committed_jobs(engine: Engine) -> Iterator[None]:
    """These tests really commit (no rollback), so empty the tables around them.

    CASCADE from job reaches job_protein; CASCADE from protein reaches structure,
    analysis_run and pocket (and job_protein again).
    """

    def truncate() -> None:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE job, protein RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture
def result_body() -> dict[str, Any]:
    return {
        "sequence": "MKVLAAGIVGLLLAQ",
        "structure": {
            "source": "alphafold",
            "source_version": "v6",
            "gcs_uri": "gs://bucket/AF-P08100-F1.pdb",
        },
        "run": {
            "tool": "fpocket",
            "tool_version": "4.0+4bb0d84",
            "params": {"min_alpha_sphere": 3.0},
        },
        "pockets": [
            {
                "rank": 1,
                "score": 0.9,
                "volume_a3": 410.5,
                "mean_sasa_a2": 22.1,
                "mean_plddt": 91.3,
                "residues": ["A:12:LEU", "A:13:GLY"],
            },
            {
                "rank": 2,
                "score": 0.4,
                "volume_a3": 150.0,
                "mean_sasa_a2": None,
                "mean_plddt": 74.0,
                "residues": ["A:40:ALA"],
            },
        ],
    }
