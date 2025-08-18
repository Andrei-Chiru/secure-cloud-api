"""
Simple API-key auth for Connexion.

- Validates the API key against env var `API_KEY` (from Secret Manager on Cloud Run).
- Connexion calls `verify_api_key(token, required_scopes)` for the header value.
- A small Flask `before_request` (in main.py) also promotes cookie/query → header
  so review links like `...?key=YOURKEY` “just work”.
"""

from __future__ import annotations
import os
from connexion.exceptions import OAuthProblem

_API_KEY = os.getenv("API_KEY")

def verify_api_key(token: str, required_scopes=None):
    """
    Connexion security handler for an apiKey scheme.
    Raises OAuthProblem if the key is missing/invalid.

    Returns an identity dict on success (shape is up to you).
    """
    if not _API_KEY:
        # Misconfiguration: you forgot to set the secret/environment
        raise OAuthProblem("Server missing API key configuration")

    if token and token == _API_KEY:
        # Returned dict becomes `request.context["user"]` if you need it
        return {"sub": "api-key", "scopes": required_scopes or []}

    raise OAuthProblem("Invalid API key")
