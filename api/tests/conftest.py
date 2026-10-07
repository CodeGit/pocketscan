import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from pocketscan_api.config import get_settings
from pocketscan_api.db import get_engine

API_DIR = Path(__file__).resolve().parents[1]


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
