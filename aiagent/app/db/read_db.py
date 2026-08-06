from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import AGENT_READ_DATABASE_URL, AGENT_READ_DB_SSL_CA


class AgentReadDatabaseError(RuntimeError):
    pass


def _engine_options(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}

    options = {
        "pool_size": 3,
        "max_overflow": 1,
        "pool_recycle": 1800,
        "pool_pre_ping": True,
    }
    if AGENT_READ_DB_SSL_CA:
        options["connect_args"] = {"ssl": {"ca": AGENT_READ_DB_SSL_CA}}
    return options


agent_read_engine = None
AgentReadSessionLocal = None
if AGENT_READ_DATABASE_URL:
    agent_read_engine = create_engine(
        AGENT_READ_DATABASE_URL,
        **_engine_options(AGENT_READ_DATABASE_URL),
    )
    if not AGENT_READ_DATABASE_URL.startswith("sqlite"):
        @event.listens_for(agent_read_engine, "connect")
        def _set_read_only(dbapi_connection, _connection_record) -> None:
            with dbapi_connection.cursor() as cursor:
                cursor.execute("SET SESSION TRANSACTION READ ONLY")

    AgentReadSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=agent_read_engine,
    )


@contextmanager
def get_read_session() -> Iterator[Session]:
    if AgentReadSessionLocal is None:
        raise AgentReadDatabaseError(
            "AI 읽기 전용 데이터베이스가 설정되지 않았습니다."
        )
    session = AgentReadSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
