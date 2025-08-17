# Embed & Search API (Connexion + Postgres/pgvector)

A tiny **OpenAPI-first** service that:
- creates **collections** of short texts,
- computes **sentence embeddings** (`all-MiniLM-L6-v2`),
- stores them in **Postgres** with **pgvector**,
- serves **semantic search** with a simple REST API,
- ships with a **dark-mode frontend** and **Swagger UI**.

---

## Features

- **Connexion/Flask** with OpenAPI 3 spec (`openapi.yaml`)
- **Auth**: header-based API key (`X-API-Key`, default `dev-key`)
- **DB**: PostgreSQL + `pgvector` (IVFFLAT cosine index)
- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2`
- **CRUD**: list/get/create/delete collections; list/delete items
- **Search**: cosine ANN via pgvector `<->` operator
- **UI**: `/` (search), `/collections.html` (manage), `/ui` (Swagger)

---

## Quickstart (Docker)

```bash
# Build with logs (first time may take a bit to download the model)
docker compose build --no-cache --progress=plain

# Start DB + API (detached)
docker compose up -d

# Watch logs (Ctrl-C to stop tailing; containers keep running)
docker compose logs -f api db
