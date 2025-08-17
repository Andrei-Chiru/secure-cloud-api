"""
BigQuery bootstrap utilities:
- Creates dataset (if missing).
- Creates tables (if missing):
    collections(id INT64, name STRING, description STRING)
    items(id STRING, collection_id INT64, text STRING, metadata JSON, embedding ARRAY<FLOAT64>)
- Provides helpers to get a client and fully-qualified table ids.
"""

import os
from google.cloud import bigquery
from google.api_core.exceptions import NotFound

PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
DATASET = os.getenv("BQ_DATASET", "demo_vectors")
LOCATION = os.getenv("BQ_LOCATION", "US")  # e.g., US or EU

def bq() -> bigquery.Client:
    """Return a BigQuery client (Application Default Credentials)."""
    if not PROJECT:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT env var is required")
    return bigquery.Client(project=PROJECT)

def fq(table: str) -> str:
    """Fully qualified table id like project.dataset.table"""
    return f"{PROJECT}.{DATASET}.{table}"

def _ensure_dataset(client: bigquery.Client):
    ds_id = f"{PROJECT}.{DATASET}"
    try:
        client.get_dataset(ds_id)
    except NotFound:
        ds = bigquery.Dataset(ds_id)
        ds.location = LOCATION
        client.create_dataset(ds)
        print(f"[init_db] created dataset {ds_id} in {LOCATION}")

def _ensure_table_collections(client: bigquery.Client):
    table_id = fq("collections")
    try:
        client.get_table(table_id)
        return
    except NotFound:
        schema = [
            bigquery.SchemaField("id", "INT64", mode="REQUIRED"),
            bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("description", "STRING"),
        ]
        table = bigquery.Table(table_id, schema=schema)
        client.create_table(table)
        print(f"[init_db] created table {table_id}")

def _ensure_table_items(client: bigquery.Client):
    table_id = fq("items")
    try:
        client.get_table(table_id)
        return
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

def init_db():
    """
    Idempotent initialization: dataset + tables.
    (You can add a VECTOR index later; for the demo we keep brute-force search.)
    """
    client = bq()
    _ensure_dataset(client)
    _ensure_table_collections(client)
    _ensure_table_items(client)
