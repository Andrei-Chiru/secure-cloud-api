"""
DB layer:
- Creates the SQLAlchemy engine/session.
- Provides init_db() to enable pgvector and create tables/indexes.
- Exposes session_scope() context manager for safe transactions.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.exc import SQLAlchemyError
from contextlib import contextmanager

# Connection string (overridable via env). Compose sets this for containers.
DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@db:5432/postgres",
)

# Engine with "pool_pre_ping" to avoid stale connection errors.
engine = create_engine(DB_URL, pool_pre_ping=True, future=True)

# Factory that gives us Session objects; expire_on_commit=False keeps attributes usable after commit.
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

class Base(DeclarativeBase):
    """Base class for ORM models (SQLAlchemy 2.x style)."""
    pass

def init_db():
    """
    Initialize database objects:
    - Ensure the "vector" extension exists (pgvector).
    - Create tables from ORM models.
    - Create a pgvector index for ANN search (IVFFLAT with cosine ops).
    Safe to call multiple times (IF NOT EXISTS).
    """
    # Import models so Base.metadata knows about our tables before create_all().
    from app import models  # noqa: F401

    # Try to install/ensure pgvector; ignore benign races/duplicates.
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    except SQLAlchemyError as e:
        # Not fatal; might be installed already or in read-only environments.
        print(f"[init_db] skip CREATE EXTENSION vector: {e}")

    # Create tables (no-op if already exist).
    Base.metadata.create_all(engine)

    # Create the ANN index (no-op if already exists).
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE INDEX IF NOT EXISTS ix_items_embedding
            ON items USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """)

@contextmanager
def session_scope():
    """
    Provide a transactional scope for a series of operations:
        with session_scope() as s:
            ... use s to query/insert ...
    Commits on success, rolls back on exception.
    """
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
