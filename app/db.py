"""
BigQuery bootstrap utilities.

Responsibilities
----------------
1) Provide a ready-to-use BigQuery client via Application Default Credentials (ADC).
2) Build fully-qualified table IDs for the current project/dataset.
3) Idempotently create (if missing) the dataset and two tables:

   - collections(
       id           INT64      REQUIRED   -- numeric, incremental id we assign
       name         STRING     REQUIRED   -- slugified unique name (enforced in handlers)
       description  STRING                -- optional human-readable description
     )

   - items(
       id            STRING     REQUIRED  -- caller-supplied item id (stable key)
       collection_id INT64      REQUIRED  -- FK-like link to collections.id
       text          STRING     REQUIRED  -- the original document/text
       metadata      JSON                  -- arbitrary JSON blob
       embedding     ARRAY<FLOAT64>        -- normalized vector; used with COSINE_DISTANCE
     )

Notes
-----
- We use ARRAY<FLOAT64> for embeddings, which works with BigQuery's
  COSINE_DISTANCE() for a simple brute-force ANN baseline.
- In production you might add partitioning/clustering or a vector index
  to speed up queries, but for this demo we keep it minimal and explicit.
- ADC must be configured (locally via `gcloud auth application-default login`,
  on Cloud Run it's automatic when using a service account).
"""

import os
from google.cloud import bigquery
from google.api_core.exceptions import NotFound

# --- Configuration via environment variables ---
# GOOGLE_CLOUD_PROJECT is required to scope the client.
PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
# Dataset name is configurable; defaults are fine for demos.
DATASET = os.getenv("BQ_DATASET", "demo_vectors")
# Location determines where the dataset lives (e.g., "US" or "EU").
LOCATION = os.getenv("BQ_LOCATION", "US")  # e.g., US or EU


def bq() -> bigquery.Client:
    """
    Return an authenticated BigQuery client scoped to `PROJECT`.

    Uses Application Default Credentials (ADC):
      - Locally, run: `gcloud auth application-default login`
      - On Cloud Run, the runtime service account provides credentials.

    Raises
    ------
    RuntimeError
        If GOOGLE_CLOUD_PROJECT is not set.
    """
    if not PROJECT:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT env var is required")
    return bigquery.Client(project=PROJECT)


def fq(table: str) -> str:
    """
    Build a fully-qualified table id: 'project.dataset.table'.

    Examples
    --------
    fq("items") -> "my-proj.demo_vectors.items"
    """
    return f"{PROJECT}.{DATASET}.{table}"


def _ensure_dataset(client: bigquery.Client) -> None:
    """
    Create the dataset if it does not exist (idempotent).

    We set the dataset's location to LOCATION so all tables/queries live
    in the same region/multi-region (important for performance and egress).
    """
    ds_id = f"{PROJECT}.{DATASET}"
    try:
        client.get_dataset(ds_id)  # fast "exists" check
    except NotFound:
        ds = bigquery.Dataset(ds_id)
        ds.location = LOCATION
        client.create_dataset(ds)
        print(f"[init_db] created dataset {ds_id} in {LOCATION}")


def _ensure_table_collections(client: bigquery.Client) -> None:
    """
    Create the 'collections' table if it does not exist (idempotent).

    Simple schema: numeric id, unique slugged name (uniqueness enforced
    at the handler level), and an optional description.
    """
    table_id = fq("collections")
    try:
        client.get_table(table_id)
        return  # already exists
    except NotFound:
        schema = [
            bigquery.SchemaField("id", "INT64", mode="REQUIRED"),
            bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("description", "STRING"),
        ]
        table = bigquery.Table(table_id, schema=schema)
        client.create_table(table)
        print(f"[init_db] created table {table_id}")


def _ensure_table_items(client: bigquery.Client) -> None:
    """
    Create the 'items' table if it does not exist (idempotent).

    We store embeddings as ARRAY<FLOAT64>; combined with normalized vectors,
    this works with BigQuery's COSINE_DISTANCE() for a brute-force ranking.

    In larger deployments, consider:
      - clustering by collection_id to improve locality,
      - adding a vector index (when available) for ANN acceleration,
      - or pre-filtering candidates prior to similarity scoring.
    """
    table_id = fq("items")
    try:
        client.get_table(table_id)
        return  # already exists
    except NotFound:
        schema = [
            bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("collection_id", "INT64", mode="REQUIRED"),
            bigquery.SchemaField("text", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("metadata", "JSON"),
            # Using ARRAY<FLOAT64> for embeddings (compatible with COSINE_DISTANCE).
            bigquery.SchemaField("embedding", "FLOAT64", mode="REPEATED"),
        ]
        table = bigquery.Table(table_id, schema=schema)
        client.create_table(table)
        print(f"[init_db] created table {table_id}")


def init_db() -> None:
    """
    Idempotently ensure the dataset and required tables exist.

    Call this during application startup (e.g., in `create_app()`), so the
    first request doesn't pay the initialization cost. Safe to run multiple
    times: existence checks avoid re-creating resources.
    """
    client = bq()
    _ensure_dataset(client)
    _ensure_table_collections(client)
    _ensure_table_items(client)
