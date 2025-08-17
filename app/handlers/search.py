"""
Search handler:
- Encodes the query.
- Runs ANN search in Postgres using pgvector with cosine distance.
- Returns top_k results with similarity scores (1 - distance).
"""

from sqlalchemy import text, bindparam, String, Integer
from app.db import session_scope
from app.models import EMBED_DIM
from sentence_transformers import SentenceTransformer
from pgvector.sqlalchemy import Vector

# Model loaded once per process.
_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def _embed_one(q: str) -> list[float]:
    """
    Encode a single query string as a normalized embedding (list of float32).
    """
    v = _model.encode([q], normalize_embeddings=True)[0]
    return v.astype("float32").tolist()

def search(cid, body):
    """
    POST /collections/{cid}/search
    Body: { "query": "...", "top_k": 5 }
    Strategy:
      - Compute query embedding (normalized).
      - Use pgvector "<->" operator for cosine distance (with normalized vectors).
      - Order by distance ascending; convert to similarity = 1 - distance.
    """
    top_k = int(body.get("top_k", 5))
    qv = _embed_one(body["query"])

    # Parameterized SQL prevents injection and ensures proper typing.
    # c.id::text comparison lets callers pass numeric id OR collection name in the same ":cid" parameter.
    sql = text("""
        SELECT i.id, i.text, i.metadata,
               (1 - (i.embedding <-> :qv)) AS similarity
        FROM items i
        JOIN collections c ON c.id = i.collection_id
        WHERE c.id::text = :cid OR c.name = :cid
        ORDER BY i.embedding <-> :qv
        LIMIT :k
    """).bindparams(
        bindparam("qv", type_=Vector(EMBED_DIM)),
        bindparam("cid", type_=String()),
        bindparam("k", type_=Integer()),
    )

    with session_scope() as s:
        rows = s.execute(sql, {"qv": qv, "cid": str(cid), "k": top_k}).mappings().all()
        return {
            "results": [
                {
                    "id": r["id"],
                    "text": r["text"],
                    "metadata": r["metadata"],
                    "score": float(r["similarity"]),
                }
                for r in rows
            ]
        }
