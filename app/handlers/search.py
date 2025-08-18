"""
Semantic search backed by BigQuery.

Workflow
--------
1) Compute an embedding for the incoming query string using
   sentence-transformers (all-MiniLM-L6-v2), normalized to unit length.

2) In BigQuery, perform a *brute-force* similarity search across the `items`
   table by ordering on COSINE_DISTANCE between each stored embedding and
   the query vector. We then convert distance to a similarity score:

      similarity = 1 - COSINE_DISTANCE(embedding, query_vector)

   Because both vectors are normalized, this equals the cosine similarity
   (i.e., the dot product), in the range [-1, 1].

Notes
-----
* This approach is simple and good for demos or small corpora. For larger
  datasets you’d typically:
    - materialize approximate indexes (e.g., a vector index in BigQuery),
    - pre-filter by collection/topic/date to reduce the search space, or
    - combine lexical + vector signals.

* All BigQuery calls are fully parameterized to avoid SQL injection.
"""

from __future__ import annotations

from typing import Any, Dict, List

from google.cloud import bigquery
from sentence_transformers import SentenceTransformer

from app.db import bq, fq  # bq() -> BigQuery client; fq("items") -> fully-qualified table name
from app.models import EMBED_DIM  # kept for schema parity (embedding dimensionality)

# ---------------------------------------------------------------------------
# Model: load once per process and reuse
# ---------------------------------------------------------------------------

# Small, fast model suitable for CPU in Cloud Run; normalizes embeddings.
_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


def _embed_one(q: str) -> List[float]:
    """
    Embed a single query string and return a normalized vector
    as a plain Python list of float64 (for BigQuery ARRAY<FLOAT64>).

    Returns
    -------
    list[float]
        A unit-length embedding vector. Length should match EMBED_DIM.
    """
    v = _model.encode([q], normalize_embeddings=True)[0]
    # Convert to native Python floats so BigQuery sees FLOAT64 values.
    return [float(x) for x in v]


def search(cid: str, body: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    POST /collections/{cid}/search

    Parameters
    ----------
    cid : str
        Collection identifier. Accepts either the *name* or the numeric *id* as string.
    body : dict
        Expected keys:
          - "query": str (required)  → the natural-language query
          - "top_k": int (optional)  → number of hits to return (default: 5)

    Returns
    -------
    dict
        {
          "results": [
            { "id": <str>, "text": <str>, "metadata": <JSON>, "score": <float> },
            ...
          ]
        }

        `score` is cosine similarity in [-1, 1]; higher is better.
    """
    # Read parameters with a simple default for top_k.
    top_k = int(body.get("top_k", 5))
    top_k = max(1, min(int(body.get("top_k", 5)), 50))

    # Compute normalized query embedding (unit vector).
    qv = _embed_one(body["query"])

    # BigQuery SQL:
    #  - Join items to collections to restrict by collection.
    #  - ORDER BY COSINE_DISTANCE so closest (smallest distance) come first.
    #  - Return a similarity score for UI convenience.
    sql = f"""
      SELECT
        i.id,
        i.text,
        i.metadata,
        1 - COSINE_DISTANCE(i.embedding, @qv) AS similarity
      FROM `{fq('items')}` AS i
      JOIN `{fq('collections')}` AS c
        ON c.id = i.collection_id
      WHERE c.name = @cid OR CAST(c.id AS STRING) = @cid
      ORDER BY COSINE_DISTANCE(i.embedding, @qv)
      LIMIT @k
    """

    # Parameterized query args:
    #  - @qv : ARRAY<FLOAT64> query embedding
    #  - @cid: STRING (either collection name or id-as-string)
    #  - @k  : INT64 result cap
    params = [
        bigquery.ArrayQueryParameter("qv", "FLOAT64", qv),
        bigquery.ScalarQueryParameter("cid", "STRING", str(cid)),
        bigquery.ScalarQueryParameter("k", "INT64", top_k),
    ]

    # Execute and materialize rows (demo-scale; streaming into a list is fine).
    rows = list(
        bq().query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
    )

    # Shape the payload the frontend expects.
    return {
        "results": [
            {
                "id": r["id"],
                "text": r["text"],
                "metadata": r["metadata"],
                "score": float(r["similarity"]),  # cosine similarity; higher = more similar
            }
            for r in rows
        ]
    }
