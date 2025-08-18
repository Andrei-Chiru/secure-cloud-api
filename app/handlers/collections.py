"""
Collections & items handlers backed by BigQuery.

This module implements a small CRUD + indexing + search surface for
"collections" of text "items", using:

- Connexion (OpenAPI) to route requests into these handlers
- BigQuery as the backing store (tables: `collections`, `items`)
- sentence-transformers to create embeddings for text items

Design notes
------------
* We load the embedding model once per process and reuse it.
* We keep helper functions private (prefixed with `_`) to make the
  public HTTP handlers easy to skim.
* We use parameterized queries everywhere for safety.
* For upserts we use a simple `MERGE` per item (fine for demo sizes).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from connexion.exceptions import ProblemException
from google.cloud import bigquery
from sentence_transformers import SentenceTransformer

from app.db import bq, fq  # `bq()` returns a BigQuery client; `fq(table)` gives fully-qualified table name


# ---------------------------------------------------------------------------
# Embedding model: load once and reuse
# ---------------------------------------------------------------------------

# Small, fast, and widely used model. Suitable for CPU inference in demos.
# NOTE: Cloud Run caches the model in memory per instance. Cold starts will
# load it once; subsequent requests reuse it.
_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


def _embed(texts: List[str]) -> List[List[float]]:
    """
    Turn a list of strings into a list of normalized embedding vectors.

    We normalize embeddings to unit length so a simple dot product is
    equivalent to cosine similarity (useful if you later change the search).

    Returns a plain Python list of lists with float64 values, which maps
    neatly to BigQuery's `ARRAY<FLOAT64>` type.
    """
    vecs = _model.encode(texts, normalize_embeddings=True)
    # Ensure native Python float (float64) for BigQuery ARRAY<FLOAT64>
    return [list(map(float, v)) for v in vecs]

# ---------------------------------------------------------------------------
# Helper queries (internal)
# ---------------------------------------------------------------------------

def _get_collection_row(client: bigquery.Client, cid: str) -> Optional[bigquery.table.Row]:
    """
    Fetch a single collection row by *name* or *id-as-string*.

    We accept either:
      - the collection *name*, or
      - the numeric id in string form

    Returns the first matching row or None.
    """
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
    """
    Compute the next collection id as (max(id) + 1).

    This is a simple demo-friendly approach. In production you might prefer:
    - a separate sequence table,
    - or let the database assign ids (e.g., using UUIDs).
    """
    q = f"SELECT COALESCE(MAX(id), 0) + 1 AS nid FROM `{fq('collections')}`"
    rows = list(client.query(q).result())
    return int(rows[0]["nid"]) if rows else 1


# ---------------------------------------------------------------------------
# Collections (HTTP handlers)
# ---------------------------------------------------------------------------

def list_collections() -> List[Dict[str, Any]]:
    """
    GET /collections
    List available collections in id order.
    """
    client = bq()
    q = f"SELECT id, name, description FROM `{fq('collections')}` ORDER BY id"
    rows = list(client.query(q).result())
    return [{"id": r["id"], "name": r["name"], "description": r["description"]} for r in rows]


def get_collection(cid: str) -> Dict[str, Any]:
    """
    GET /collections/{cid}
    Fetch a collection by *name* or *id* (string).
    """
    client = bq()
    row = _get_collection_row(client, cid)
    if not row:
        raise ProblemException(404, "Not Found", f"Collection {cid} not found")
    return {"id": row["id"], "name": row["name"], "description": row["description"]}


def create_collection(body: Dict[str, Any]):
    """
    POST /collections
    Create a new collection with a unique, slugified `name`.

    Body:
      { "name": "my-collection", "description": "optional" }

    Returns (object, status_code):
      ({ "id": <int>, "name": <str> }, 201)
    """
    client = bq()

    # Normalize name: lowercased, spaces -> hyphens
    name = body["name"].strip().lower().replace(" ", "-")
    desc = body.get("description")

    # Enforce uniqueness on name
    existing = _get_collection_row(client, name)
    if existing:
        raise ProblemException(409, "Conflict", "Collection exists")

    # Assign next id
    nid = _get_next_collection_id(client)

    # Insert the new collection
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


def delete_collection(cid: str):
    """
    DELETE /collections/{cid}
    Delete a collection (by name or id) and all its items.
    """
    client = bq()
    row = _get_collection_row(client, cid)
    if not row:
        raise ProblemException(404, "Not Found", f"Collection {cid} not found")
    coll_id = int(row["id"])

    # Delete items first (FK-like manual cascade), then the collection.
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

    # Connexion interprets ("", 204) as an empty 204 No Content.
    return "", 204


# ---------------------------------------------------------------------------
# Items (HTTP handlers)
# ---------------------------------------------------------------------------

def list_items(cid: str, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """
    GET /collections/{cid}/items
    List items in a collection with basic pagination.

    Query params:
      - limit: 1..500
      - offset: >= 0
    """
    client = bq()
    row = _get_collection_row(client, cid)
    if not row:
        raise ProblemException(404, "Not Found", f"Collection {cid} not found")
    coll_id = int(row["id"])

    # Clamp pagination inputs to safe ranges
    lim = int(max(1, min(int(limit), 500)))
    off = int(max(0, int(offset)))

    q = f"""
      SELECT id, text, metadata
      FROM `{fq('items')}`
      WHERE collection_id = @cid
      ORDER BY id
      LIMIT @lim OFFSET @off
    """
    params = [
        bigquery.ScalarQueryParameter("cid", "INT64", coll_id),
        bigquery.ScalarQueryParameter("lim", "INT64", lim),
        bigquery.ScalarQueryParameter("off", "INT64", off),
    ]
    rows = list(
        client.query(q, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
    )

    return {
        "collection": {"id": coll_id, "name": row["name"]},
        "items": [{"id": r["id"], "text": r["text"], "metadata": r["metadata"]} for r in rows],
        "limit": lim,
        "offset": off,
    }


def delete_item(cid: str, item_id: str):
    """
    DELETE /collections/{cid}/items/{item_id}
    Remove a single item from a collection.
    """
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

    # If nothing was deleted, treat it as a 404. BigQuery exposes the number
    # of affected rows for DML; fall back to 404 if the info isn't present.
    if getattr(result, "num_dml_affected_rows", None) in (0, None):
        raise ProblemException(404, "Not Found", f"Item {item_id} not found in collection {cid}")

    return "", 204


# ---------------------------------------------------------------------------
# Indexing (HTTP handler)
# ---------------------------------------------------------------------------

def upsert_items(cid: str, body: Dict[str, Any]) -> Dict[str, int]:
    """
    POST /collections/{cid}/index
    Upsert (insert or update) one or more items in a collection.

    Body:
      {
        "items": [
          { "id": "doc-1", "text": "Some content...", "metadata": { ... } },
          ...
        ]
      }

    Behavior:
      - Computes embeddings for all items in one go (batch encode).
      - Upserts items *one-by-one* using a simple `MERGE`.
        This is easy to read and sufficient for small demos.
        For larger batches you can:
          * use a VALUES list with multiple rows,
          * stage into a temp table and MERGE once,
          * or use the Storage Write API.
    """
    client = bq()

    # Resolve collection (accepts name or id-as-string)
    coll = _get_collection_row(client, cid)
    if not coll:
        raise ProblemException(404, "Not Found", f"Collection {cid} not found")
    coll_id = int(coll["id"])

    items = body["items"]
    texts = [it["text"] for it in items]

    # Compute normalized embeddings in a single batch
    vecs = _embed(texts)

    # Parameterized MERGE template for a single item
    merge_sql = f"""
      MERGE `{fq('items')}` AS T
      USING (
        SELECT @id  AS id,
               @cid AS collection_id,
               @text AS text,
               @meta AS metadata,
               @emb  AS embedding
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

    # Execute one MERGE per item to keep logic simple and explicit.
    # NOTE on JSON: BigQuery "JSON" parameter expects a JSON *string*;
    # we pass "null" (string) when metadata is absent to write a JSON null.
    for it, emb in zip(items, vecs):
        params = [
            bigquery.ScalarQueryParameter("id", "STRING", it["id"]),
            bigquery.ScalarQueryParameter("cid", "INT64", coll_id),
            bigquery.ScalarQueryParameter("text", "STRING", it["text"]),
            bigquery.ScalarQueryParameter(
                "meta",
                "JSON",
                json.dumps(it.get("metadata")) if it.get("metadata") is not None else "null",
            ),
            bigquery.ArrayQueryParameter("emb", "FLOAT64", emb),
        ]
        client.query(merge_sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()

    # Minimal response with how many we processed
    return {"count": len(items)}
