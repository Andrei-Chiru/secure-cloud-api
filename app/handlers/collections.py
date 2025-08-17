"""
Handlers for:
- Healthcheck
- Collections CRUD: list/get/create/delete
- Items list/delete
- Index/upsert items (computes embeddings)
"""

from sqlalchemy import select
from connexion.exceptions import ProblemException
from app.db import session_scope
from app.models import Collection, Item
from sentence_transformers import SentenceTransformer

# Load the embedding model once per process.
# all-MiniLM-L6-v2 is fast (384-dim); normalize for cosine similarity.
_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def _embed(texts: list[str]) -> list[list[float]]:
    """
    Encodes an array of strings into normalized embeddings (lists of float32).
    Normalization makes cosine distance equivalent to dot-product ordering.
    """
    v = _model.encode(texts, normalize_embeddings=True)
    return [row.astype("float32").tolist() for row in v]

def healthz():
    """ GET /healthz -> simple OK payload """
    return {"ok": True}

# ---------- helpers ----------

def _get_collection(s, cid: str) -> Collection | None:
    """
    Resolve collection by id (numeric string) OR by name (string).
    """
    if str(cid).isdigit():
        coll = s.get(Collection, int(cid))
        if coll:
            return coll
    return s.scalar(select(Collection).where(Collection.name == str(cid)))

# ---------- collections ----------

def list_collections():
    """ GET /collections -> list all collections """
    with session_scope() as s:
        rows = s.scalars(select(Collection).order_by(Collection.id)).all()
        return [{"id": c.id, "name": c.name, "description": c.description} for c in rows]

def get_collection(cid):
    """ GET /collections/{cid} -> fetch one collection """
    with session_scope() as s:
        coll = _get_collection(s, cid)
        if not coll:
            raise ProblemException(404, "Not Found", f"Collection {cid} not found")
        return {"id": coll.id, "name": coll.name, "description": coll.description}

def create_collection(body):
    """ POST /collections -> create a collection by name """
    name = body["name"].strip().lower().replace(" ", "-")
    desc = body.get("description")
    with session_scope() as s:
        exists = s.scalar(select(Collection).where(Collection.name == name))
        if exists:
            raise ProblemException(409, "Conflict", "Collection exists")
        c = Collection(name=name, description=desc)
        s.add(c)
        s.flush()  # ensure c.id is populated
        return {"id": c.id, "name": c.name}, 201

def delete_collection(cid):
    """ DELETE /collections/{cid} -> delete a collection and all its items """
    with session_scope() as s:
        coll = _get_collection(s, cid)
        if not coll:
            raise ProblemException(404, "Not Found", f"Collection {cid} not found")
        s.delete(coll)  # cascades to items
        return "", 204

# ---------- items ----------

def list_items(cid, limit=50, offset=0):
    """ GET /collections/{cid}/items -> list items in a collection (paginated) """
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    with session_scope() as s:
        coll = _get_collection(s, cid)
        if not coll:
            raise ProblemException(404, "Not Found", f"Collection {cid} not found")
        q = (
            select(Item)
            .where(Item.collection_id == coll.id)
            .order_by(Item.id)
            .limit(limit)
            .offset(offset)
        )
        rows = s.scalars(q).all()
        return {
            "collection": {"id": coll.id, "name": coll.name},
            "items": [{"id": it.id, "text": it.text, "metadata": it.meta} for it in rows],
            "limit": limit,
            "offset": offset,
        }

def delete_item(cid, item_id):
    """ DELETE /collections/{cid}/items/{item_id} -> delete a single item """
    with session_scope() as s:
        coll = _get_collection(s, cid)
        if not coll:
            raise ProblemException(404, "Not Found", f"Collection {cid} not found")
        row = s.get(Item, item_id)
        if not row or row.collection_id != coll.id:
            raise ProblemException(404, "Not Found", f"Item {item_id} not found in collection {cid}")
        s.delete(row)
        return "", 204

# ---------- indexing ----------

def upsert_items(cid, body):
    """
    POST /collections/{cid}/index
    Upsert an array of items and compute fresh embeddings.
    - If an item id already exists, we update its text/metadata/embedding.
    - Otherwise we insert a new row.
    """
    items = body["items"]
    texts = [it["text"] for it in items]
    vecs = _embed(texts)

    with session_scope() as s:
        coll = _get_collection(s, cid)
        if not coll:
            raise ProblemException(404, "Not Found", f"Collection {cid} not found")

        for it, vec in zip(items, vecs):
            row = s.get(Item, it["id"])
            if row:
                # Update existing item
                row.text = it["text"]
                row.meta = it.get("metadata")
                row.embedding = vec
                row.collection_id = coll.id
            else:
                # Insert new item
                s.add(
                    Item(
                        id=it["id"],
                        collection_id=coll.id,
                        text=it["text"],
                        meta=it.get("metadata"),
                        embedding=vec,
                    )
                )

    return {"count": len(items)}
