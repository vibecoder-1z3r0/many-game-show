"""Database engine and session dependency."""

import os
from collections.abc import Generator
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

# MANYGAMESHOW_DB_PATH lets tooling (e.g. scripts/screenshots.py) use a
# throwaway database instead of the dev one.
_DB_PATH = Path(
    os.environ.get("MANYGAMESHOW_DB_PATH")
    or Path(__file__).parent.parent.parent / "manygameshow.db"
)
DATABASE_URL = f"sqlite:///{_DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session]:
    with Session(engine) as session:
        yield session
