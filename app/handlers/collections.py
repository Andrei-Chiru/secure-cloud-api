"""
Collections & items handlers backed by BigQuery.
"""

import json
from connexion.exceptions import ProblemException
from google.cloud import bigquery
from app.db import bq, fq
from sentence_transformers import SentenceTransformer

# Embedding model loaded once per process.
_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def _embed(texts: list[str]) -> list[list[float]]:
    vecs = _model.encode(texts, normalize_embeddings=True)
    # Convert to Python float (float64) for BigQuery ARRAY<FLOAT64>
    return [list(map(float, v)) for v in vecs]

def healthz():
    return {"ok": True}

# ---------- helpers ----------

def _get_collection_row(client: bigquery.Client, cid: str):
    q = f"""
      SELECT id, name, description
      FROM `{fq("collections")}`
      WHERE name = @cid OR CAST(id AS STRING) = @cid
      LIMIT 1
    """
    job = client.query(
        q,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("cid", "STRING", str(cid))]
        ),
    )
    rows = list(job.result())
    return rows[0] if rows else None

def _get_next_collection_id(client: bigquery.Client) -> int:
    q = f"SELECT COALESCE(MAX(id), 0) + 1 AS nid FROM `{fq('collections')}`"
    rows = list(client.query(q).result())
    return int(rows[0]["nid"]) if rows else 1

# ---------- collections ----------

def list_collections():
    client = bq()
    q = f"SELECT id, name, description FROM `{fq('collections')}` ORDER BY id"
    rows = list(client.query(q).result())
    return [{"id": r["id"], "name": r["name"], "description": r["description"]} for r in rows]

def get_collection(cid):
    client = bq()
    row = _get_collection_row(client, cid)
    if not row:
        raise ProblemException(404, "Not Found", f"Collection {cid} not found")
    return {"id": row["id"], "name": row["name"], "description": row["description"]}

def create_collection(body):
    client = bq()
    name = body["name"].strip().lower().replace(" ", "-")
    desc = body.get("description")

    # Uniqueness check on name
    existing = _get_collection_row(client, name)
    if existing:
        raise ProblemException(409, "Conflict", "Collection exists")

    nid = _get_next_collection_id(client)
    q = f"""
      INSERT INTO `{fq('collections')}` (id, name, description)
      VALUES (@id, @name, @desc)
    """
    params = [
        bigquery.ScalarQueryParameter("id", "INT64", nid),
        bigquery.ScalarQueryParameter("name", "STRING", name),
        bigquery.ScalarQueryParameter("desc", "STRING", desc),
    ]
    client.query(q, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
    return {"id": nid, "name": name}, 201

def delete_collection(cid):
    client = bq()
    row = _get_collection_row(client, cid)
    if not row:
        raise ProblemException(404, "Not Found", f"Collection {cid} not found")
    coll_id = int(row["id"])

    # Delete items first, then collection
    client.query(
        f"DELETE FROM `{fq('items')}` WHERE collection_id = @cid",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("cid", "INT64", coll_id)]
        ),
    ).result()
    client.query(
        f"DELETE FROM `{fq('collections')}` WHERE id = @cid",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("cid", "INT64", coll_id)]
        ),
    ).result()
    return "", 204

# ---------- items ----------

def list_items(cid, limit=50, offset=0):
    client = bq()
    row = _get_collection_row(client, cid)
    if not row:
        raise ProblemException(404, "Not Found", f"Collection {cid} not found")
    coll_id = int(row["id"])

    q = f"""
      SELECT id, text, metadata
      FROM `{fq('items')}`
      WHERE collection_id = @cid
      ORDER BY id
      LIMIT @lim OFFSET @off
    """
    params = [
        bigquery.ScalarQueryParameter("cid", "INT64", coll_id),
        bigquery.ScalarQueryParameter("lim", "INT64", int(max(1, min(int(limit), 500)))),
        bigquery.ScalarQueryParameter("off", "INT64", int(max(0, int(offset)))),
    ]
    rows = list(bq().query(q, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
    return {
        "collection": {"id": coll_id, "name": row["name"]},
        "items": [{"id": r["id"], "text": r["text"], "metadata": r["metadata"]} for r in rows],
        "limit": int(limit),
        "offset": int(offset),
    }

def delete_item(cid, item_id):
    client = bq()
    row = _get_collection_row(client, cid)
    if not row:
        raise ProblemException(404, "Not Found", f"Collection {cid} not found")
    coll_id = int(row["id"])

    q = f"DELETE FROM `{fq('items')}` WHERE id = @id AND collection_id = @cid"
    params = [
        bigquery.ScalarQueryParameter("id", "STRING", item_id),
        bigquery.ScalarQueryParameter("cid", "INT64", coll_id),
    ]
    job = client.query(q, job_config=bigquery.QueryJobConfig(query_parameters=params))
    result = job.result()
    # If nothing deleted, treat as 404
    if getattr(result, "num_dml_affected_rows", None) in (0, None):
        raise ProblemException(404, "Not Found", f"Item {item_id} not found in collection {cid}")
    return "", 204

# ---------- indexing ----------

def upsert_items(cid, body):
    client = bq()
    coll = _get_collection_row(client, cid)
    if not coll:
        raise ProblemException(404, "Not Found", f"Collection {cid} not found")
    coll_id = int(coll["id"])

    items = body["items"]
    texts = [it["text"] for it in items]
    vecs = _embed(texts)

    # Upsert one-by-one using MERGE (simple & clear for demo sizes)
    merge_sql = f"""
      MERGE `{fq('items')}` AS T
      USING (
        SELECT @id AS id,
               @cid AS collection_id,
               @text AS text,
               @meta AS metadata,
               @emb AS embedding
      ) AS S
      ON T.id = S.id
      WHEN MATCHED THEN
        UPDATE SET
          collection_id = S.collection_id,
          text          = S.text,
          metadata      = S.metadata,
          embedding     = S.embedding
      WHEN NOT MATCHED THEN
        INSERT (id, collection_id, text, metadata, embedding)
        VALUES (S.id, S.collection_id, S.text, S.metadata, S.embedding)
    """

    for it, emb in zip(items, vecs):
        params = [
            bigquery.ScalarQueryParameter("id", "STRING", it["id"]),
            bigquery.ScalarQueryParameter("cid", "INT64", coll_id),
            bigquery.ScalarQueryParameter("text", "STRING", it["text"]),
            # JSON param: pass a JSON string
            bigquery.ScalarQueryParameter("meta", "JSON", json.dumps(it.get("metadata")) if it.get("metadata") is not None else "null"),
            # ARRAY<FLOAT64>
            bigquery.ArrayQueryParameter("emb", "FLOAT64", emb),
        ]
        client.query(merge_sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()

    return {"count": len(items)}
