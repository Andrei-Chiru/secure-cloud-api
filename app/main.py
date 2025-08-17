import connexion
from app.db import init_db

def create_app():
    init_db()  # now ensures BigQuery dataset/tables exist
    app = connexion.App(__name__, specification_dir="..", options={"swagger_ui": True})
    app.add_api("openapi.yaml", strict_validation=True, validate_responses=False)
    return app

app = create_app().app

@app.get("/")
def _index():
    return app.send_static_file("index.html")

@app.get("/collections.html")
def _collections_page():
    return app.send_static_file("collections.html")

if __name__ == "__main__":
    create_app().run(port=8000)
