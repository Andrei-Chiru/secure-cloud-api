"""
ORM models:
- Collection: groups items (e.g., a document set).
- Item: text + JSON metadata + embedding vector (pgvector).
"""

from sqlalchemy import String, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from app.db import Base

# Embedding dimension for "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384

class Collection(Base):
    __tablename__ = "collections"

    # Autoincrementing integer primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Human-friendly unique name (e.g., "kb-ml")
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    # Optional text description
    description: Mapped[str | None]
    # Backref to items; cascade ensures items are deleted with the collection
    items: Mapped[list["Item"]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan"
    )

class Item(Base):
    __tablename__ = "items"

    # Caller-provided stable string id (lets you upsert by id)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)

    # FK to Collection
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"),
        index=True
    )

    # Raw content we embed
    text: Mapped[str] = mapped_column()

    # "metadata" is a reserved attribute in SQLAlchemy; use "meta" python attr but keep column name "metadata"
    meta: Mapped[dict | None] = mapped_column("metadata", JSON)

    # Vector column (pgvector) stores the embedding for fast ANN search
    embedding = mapped_column(Vector(EMBED_DIM))

    # Backref to Collection
    collection: Mapped[Collection] = relationship(back_populates="items")
