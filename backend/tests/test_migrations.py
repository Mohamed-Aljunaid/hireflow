import io
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config(url: str, buffer: io.StringIO | None = None) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"), output_buffer=buffer)
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    return cfg


def test_upgrade_and_downgrade_sqlite(tmp_path: Path) -> None:
    db = tmp_path / "migrate.db"
    cfg = alembic_config(f"sqlite+aiosqlite:///{db.as_posix()}")

    command.upgrade(cfg, "head")
    engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    cols = {c["name"] for c in sa.inspect(engine).get_columns("cvs")}
    assert cols == {"id", "filename", "content_type", "raw_text", "parsed", "created_at"}
    engine.dispose()

    command.downgrade(cfg, "base")
    engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    assert "cvs" not in sa.inspect(engine).get_table_names()
    engine.dispose()


def test_postgres_offline_sql_uses_jsonb_and_timestamptz() -> None:
    buf = io.StringIO()
    cfg = alembic_config("postgresql+asyncpg://u:p@localhost/db", buf)
    command.upgrade(cfg, "head", sql=True)
    sql = buf.getvalue()
    assert "CREATE TABLE cvs" in sql
    assert "parsed JSONB NOT NULL" in sql
    assert "created_at TIMESTAMP WITH TIME ZONE NOT NULL" in sql
    assert "id UUID NOT NULL" in sql


def test_models_match_migrations(tmp_path: Path) -> None:
    """Autogenerate finds no diff between the ORM models and the migrated schema."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db import models  # noqa: F401
    from app.db.base import Base

    db = tmp_path / "diff.db"
    command.upgrade(alembic_config(f"sqlite+aiosqlite:///{db.as_posix()}"), "head")
    engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []
