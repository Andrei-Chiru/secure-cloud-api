"""
App bootstrap:
- Initializes the database (creates extension/tables/index).
- Loads the OpenAPI spec and hooks Python handlers with Connexion.
- Serves a tiny static frontend at "/" and "/collections.html".
"""

import connexion
from app.db import init_db

def create_app():
    """
    Build the Connexion application, perform DB init, and attach the API spec.
    """
    # Create tables/indices once at startup; safe to re-run (idempotent).
    init_db()

    # Connexion wraps a Flask app; specification_dir=".." points to repo root.
    app = connexion.App(__name__, specification_dir="..", options={"swagger_ui": True})

    # Load and validate the OpenAPI specification, wiring handlers by operationId.
    app.add_api("openapi.yaml", strict_validation=True, validate_responses=False)
    return app

# Flask WSGI app exposed to Gunicorn (gunicorn loads "app.main:app").
app = create_app().app

# Serve the dark-mode search UI at "/"
@app.get("/")
def _index():
    # Flask automatically serves from app/static; we return index.html.
    return app.send_static_file("index.html")

# Serve the dark-mode management UI at "/collections.html"
@app.get("/collections.html")
def _collections_page():
    return app.send_static_file("collections.html")

if __name__ == "__main__":
    # Dev server (use Gunicorn in containers)
    create_app().run(port=8000)
