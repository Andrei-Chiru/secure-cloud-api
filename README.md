# Secure Cloud API — Vector Search (Connexion + BigQuery)

A minimal API service that:
- **Creates collections** and **indexes text items** (each text is embedded and stored with metadata).
- **Searches** with semantic similarity.
- Serves a tiny **dark-mode UI** for manual demos + **seed** buttons for quick data.

## Architecture
- **Framework:** Python + Flask via **Connexion** (OpenAPI-first).
- **Storage:** **BigQuery** (tables: `collections`, `items`).
- **Embeddings:** `sentence-transformers` (CPU, PyTorch).
- **Auth:** static API key in header `X-API-Key` (stored in Secret Manager on Cloud Run).

## Endpoints (excerpt)
- `POST /collections` → create a collection  
  body: `{ "name": "demo", "description": "…" }`
- `GET /collections` → list collections
- `DELETE /collections/{cid}` → delete a collection by id or name
- `POST /collections/{cid}/index` → add **one or many** items  
  body: `{ "items": [ { "id": "1", "text": "…", "metadata": {…} } ] }`
- `POST /collections/{cid}/search` → semantic search  
  body: `{ "query": "…", "top_k": 5 }`

> See `/ui` (Swagger UI) for the full contract. The `/healthz` route was removed.

## Manual demo (UI)
1. Open the app root (e.g. `http://localhost:8000/` or your Cloud Run URL).
2. Type a **collection** name and click **Create collection**.
3. Use **Add item (manual)** to add one item at a time (ID, Text, optional JSON metadata).
4. Or use **Seed demo / Seed bigger demo** for quick fixtures.
5. Run **Search** with a natural-language query.

## cURL equivalents
```bash
# create collection
curl -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"name":"demo","description":"manual"}' \
  $API/collections

# add one item
curl -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"items":[{"id":"1","text":"Paris is the capital of France","metadata":{"tag":"geo"}}]}' \
  $API/collections/demo/index

# search
curl -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"query":"French capital city","top_k":3}' \
  $API/collections/demo/search
