"""
Application entrypoint (Connexion + Flask).

What this file does
-------------------
1) Runs one-time, idempotent BigQuery bootstrap via `init_db()` so the
   dataset and tables exist before the first request.
2) Creates a Connexion app from the OpenAPI spec (`openapi.yaml`), enabling
   Swagger UI under `/ui`.
3) Exposes the underlying Flask WSGI app as the module-level `app` so
   process managers like gunicorn can use the dotted path `app.main:app`.
4) Serves two simple static pages (`/` and `/collections.html`) from Flask's
   static folder (used for the minimal frontend).

Notes
-----
- Connexion loads operation handlers based on `operationId` values in
  `openapi.yaml` (e.g., `app.handlers.collections.list_collections`).
- `init_db()` is safe to call multiple times; it only creates missing
  datasets/tables.
- In production (Cloud Run / gunicorn), the WSGI server imports `app`
  and serves it; the `if __name__ == "__main__"` block is for local dev.
"""

from __future__ import annotations

import connexion
from connexion import App as ConnexionApp  # just for type hints
from flask import Flask
from app.db import init_db


def create_app() -> ConnexionApp:
    """
    Build and configure the Connexion application.

    Returns
    -------
    connexion.App
        Connexion wrapper that contains the underlying Flask app at `.app`.
    """
    # Ensure BigQuery dataset and tables are present before routing starts.
    # Idempotent: safe to call on every cold start.
    init_db()

    # Create Connexion app; `specification_dir=".."` means `openapi.yaml`
    # is located one level above this file (adjust if you move files).
    cx = connexion.App(
        __name__,
        specification_dir="..",
        options={"swagger_ui": True},  # serve interactive docs at /ui
    )

    # Register API from the OpenAPI document. Connexion wires routes to
    # Python callables based on `operationId`.
    # - strict_validation=True → reject requests that don't match the schema.
    # - validate_responses=False → keep response validation off (faster, simpler).
    cx.add_api("openapi.yaml", strict_validation=True, validate_responses=False)

    return cx


# Expose the underlying Flask WSGI app at module level.
# Gunicorn entrypoint example: `gunicorn -w 2 -b :8000 app.main:app`
app: Flask = create_app().app


# ------------------------------
# Simple static routes for the UI
# ------------------------------

@app.get("/")
def _index():
    """
    Serve the main search UI (index.html) from Flask's static folder.

    Flask determines the static folder from the Connexion/Flask app configuration.
    """
    return app.send_static_file("index.html")


@app.get("/collections.html")
def _collections_page():
    """
    Serve the collections management UI (collections.html) from the static folder.
    """
    return app.send_static_file("collections.html")


# ------------------------------
# Local development entrypoint
# ------------------------------

if __name__ == "__main__":
    # Running this file directly starts Flask's built-in dev server.
    # In production, prefer a WSGI server (e.g., gunicorn) and import `app`.
    create_app().run(port=8000, debug=True)
