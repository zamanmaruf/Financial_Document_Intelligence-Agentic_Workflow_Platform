"""SQLAlchemy engine and table definitions.

Tables keep indexed columns for querying plus a JSON ``payload`` holding the validated domain
model. SQLite is used locally; the same models run on PostgreSQL by changing
``DOCINTEL_DATABASE_URL``. Schema changes are applied by the small idempotent startup migration
in ``_migrate`` (production would use Alembic).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Engine,
    Index,
    Integer,
    String,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.domain.models import DEFAULT_WORKSPACE


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON}


def _workspace_column() -> Mapped[str]:
    return mapped_column(String(64), index=True, default=DEFAULT_WORKSPACE)


class DocumentRow(Base):
    __tablename__ = "documents"
    # the same file may be uploaded once per workspace
    __table_args__ = (
        Index("uq_documents_workspace_sha256", "workspace_id", "sha256", unique=True),
    )
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = _workspace_column()
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    document_type: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]]


class DocumentTextRow(Base):
    __tablename__ = "document_texts"
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]]


class ExtractionRow(Base):
    __tablename__ = "extractions"
    extraction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]]


class WorkflowRow(Base):
    __tablename__ = "workflows"
    workflow_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]]


class ReviewRow(Base):
    __tablename__ = "reviews"
    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = _workspace_column()
    document_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    target_type: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]]


class AuditRow(Base):
    __tablename__ = "audit_events"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True)
    document_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]]


class InvocationRow(Base):
    __tablename__ = "model_invocations"
    invocation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]]


class AnswerRow(Base):
    __tablename__ = "answers"
    answer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = _workspace_column()
    document_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]]


class SchemaMetaRow(Base):
    __tablename__ = "schema_meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256))


class EvaluationRow(Base):
    __tablename__ = "evaluations"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]]


def create_db_engine(url: str) -> Engine:
    if url.startswith("sqlite:///"):
        db_path = Path(url.removeprefix("sqlite:///"))
        if str(db_path) != ":memory:":
            db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    else:
        engine = create_engine(url, pool_pre_ping=True, future=True)
    Base.metadata.create_all(engine)
    _migrate(engine)
    return engine


_WORKSPACE_TABLES = ("documents", "reviews", "answers")
# 1: initial schema; 2: workspace_id + per-workspace document de-duplication
SCHEMA_VERSION = 2


def _migrate(engine: Engine) -> None:
    """Bring databases created before workspaces existed up to date (idempotent).

    ``create_all`` never alters existing tables, so columns added later are applied here.
    """
    insp = inspect(engine)
    pending = [
        t
        for t in _WORKSPACE_TABLES
        if "workspace_id" not in {c["name"] for c in insp.get_columns(t)}
    ]
    with engine.begin() as conn:
        for table in pending:
            conn.execute(
                text(
                    f"ALTER TABLE {table} ADD COLUMN workspace_id VARCHAR(64) "
                    f"NOT NULL DEFAULT '{DEFAULT_WORKSPACE}'"
                )
            )
            conn.execute(text(f"CREATE INDEX ix_{table}_workspace_id ON {table} (workspace_id)"))
        if "documents" in pending:
            # sha256 was globally unique; it becomes unique per workspace
            conn.execute(text("DROP INDEX ix_documents_sha256"))
            conn.execute(text("CREATE INDEX ix_documents_sha256 ON documents (sha256)"))
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX uq_documents_workspace_sha256 "
                    "ON documents (workspace_id, sha256)"
                )
            )
        if conn.execute(text("SELECT 1 FROM schema_meta WHERE key = 'schema_version'")).first():
            conn.execute(
                text("UPDATE schema_meta SET value = :v WHERE key = 'schema_version'"),
                {"v": str(SCHEMA_VERSION)},
            )
        else:
            conn.execute(
                text("INSERT INTO schema_meta (key, value) VALUES ('schema_version', :v)"),
                {"v": str(SCHEMA_VERSION)},
            )


def make_session_factory(engine: Engine) -> sessionmaker[Any]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
