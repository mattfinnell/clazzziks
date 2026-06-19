"""Access to the shared API contract (``openapi.json``).

``openapi.json`` is the single source of truth for the ``/api`` surface shared
by this backend and the React frontend. The backend serves it at
``GET /api/openapi.json`` and validates its own responses against it in
``tests/test_contract.py``; the frontend builds against the same shapes.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CONTRACT_PATH = Path(__file__).with_name("openapi.json")


@lru_cache(maxsize=1)
def load_contract() -> dict[str, Any]:
    """Return the parsed OpenAPI contract document."""
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def schema(name: str) -> dict[str, Any]:
    """Return a single named schema from ``components.schemas`` of the contract.

    The returned schema still uses ``$ref`` pointers into the contract, so
    validators must resolve refs against the full document (see
    :func:`load_contract`).
    """
    schemas = load_contract()["components"]["schemas"]
    try:
        return schemas[name]
    except KeyError as exc:  # pragma: no cover - misuse guard
        raise KeyError(
            f"No schema {name!r} in contract. Available: {sorted(schemas)}."
        ) from exc
