"""
Very simple header-based API key auth for demos:
- Clients send:  X-API-Key: <value>
- We compare against env var API_KEY (default "dev-key").
"""

import os
from connexion.exceptions import Unauthorized

API_KEY = os.getenv("API_KEY", "dev-key")

def check_api_key(token, required_scopes=None):
    """
    Connexion hook defined in openapi.yaml under components.securitySchemes.
    Raises 401 if token mismatches.
    """
    if token != API_KEY:
        raise Unauthorized("Invalid API key")
    # Return a "principal" dict if you need per-user info downstream.
    return {"sub": "demo"}
