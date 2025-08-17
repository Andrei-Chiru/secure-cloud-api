"""
Semantic search backed by BigQuery:
- Compute query embedding.
- Brute-force ORDER BY COSINE_DISTANCE on ARRAY<FLOAT64> embedding column.
  (Good enough for the demo; you can add a VECTOR index later.)
"""

from google.cloud import bigquery
from app.db import bq, fq
from app.models import EMBED_DIM
from sentence_transformers import SentenceTransformer

_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def _embed_one(q: str) -> list[float]:
    v = _model.encode([q], normalize_embeddings=True)[0]
    return [float(x) for x in v]  # ARRAY<FLOAT64>

def search(cid, body):
    top_k = int(body.get("top_k", 5))
    qv = _embed_one(body["query"])

    sql = f"""
      SELECT i.id, i.text, i.metadata,
             1 - COSINE_DISTANCE(i.embedding, @qv) AS similarity
      FROM `{fq('items')}` AS i
      JOIN `{fq('collections')}` AS c
        ON c.id = i.collection_id
      WHERE c.name = @cid OR CAST(c.id AS STRING) = @cid
      ORDER BY COSINE_DISTANCE(i.embedding, @qv)
      LIMIT @k
    """
    params = [
        bigquery.ArrayQueryParameter("qv", "FLOAT64", qv),
        bigquery.ScalarQueryParameter("cid", "STRING", str(cid)),
        bigquery.ScalarQueryParameter("k", "INT64", top_k),
    ]
    rows = list(bq().query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
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
