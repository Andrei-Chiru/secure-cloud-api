from __future__ import annotations

import connexion
from flask import Flask, request
from app.db import init_db

def create_app() -> connexion.App:
    init_db()
    cx = connexion.App(__name__, specification_dir="..", options={"swagger_ui": True})
    cx.add_api("openapi.yaml", strict_validation=True, validate_responses=False)
    app: Flask = cx.app  # underlying Flask

    @app.before_request
    def promote_key_to_header():
        """
        If the client put the API key in a cookie (x_api_key) or in the URL (?key=...),
        copy it into the X-API-Key header so Connexion's auth can see it.
        """
        environ = request.environ
        if "HTTP_X_API_KEY" in environ and environ["HTTP_X_API_KEY"]:
            return  # header already present

        key = request.cookies.get("x_api_key") or request.args.get("key")
        if key:
            # Connexion reads headers from WSGI environ keys like HTTP_<HEADER_NAME>
            environ["HTTP_X_API_KEY"] = key

    return cx

app = create_app().app

@app.get("/")
def _index():
    return app.send_static_file("index.html")

@app.get("/collections.html")
def _collections_page():
    return app.send_static_file("collections.html")

if __name__ == "__main__":
    create_app().run(port=8000, debug=True)
