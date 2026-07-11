"""Contract tests: the committed GraphQL SDL is the single source of truth.

``clazzziks/schema.graphql`` is the shared contract with the React frontend
(``frontend/src/api.ts`` builds against these exact types/fields). These tests
fail if the code-first schema drifts from the committed SDL, keeping both sides
honest — the GraphQL replacement for the old hand-authored ``openapi.json``.

Regenerate the SDL after an intentional schema change with::

    uv run python -c "from clazzziks.schema import schema; \
        open('clazzziks/schema.graphql','w').write(schema.as_str()+'\\n')"
"""

# pylint: disable=missing-function-docstring,redefined-outer-name

from pathlib import Path

from clazzziks.schema import schema
from clazzziks.formats import AudioFormat

from .gql import gql_data

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "clazzziks" / "schema.graphql"


def test_emitted_sdl_matches_committed_contract():
    committed = CONTRACT_PATH.read_text(encoding="utf-8").strip()
    current = schema.as_str().strip()
    assert current == committed, (
        "GraphQL schema drifted from clazzziks/schema.graphql — regenerate it "
        "(see this module's docstring)."
    )


def test_contract_declares_core_operations():
    sdl = CONTRACT_PATH.read_text(encoding="utf-8")
    for op in (
        "config", "me", "vips", "users",
        "download", "add_vip", "update_vip", "remove_vip", "sync_users",
    ):
        assert op in sdl, f"operation {op!r} missing from the contract SDL"


def test_config_reports_mp3_only(client):
    cfg = gql_data(client, "{ config { formats default_format bundle_format } }")["config"]
    assert cfg["default_format"] == AudioFormat.MP3.value
    assert cfg["default_format"] in cfg["formats"]
    assert cfg["bundle_format"] == AudioFormat.MP3.value
