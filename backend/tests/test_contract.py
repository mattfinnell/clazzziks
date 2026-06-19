"""Contract tests: the backend must conform to the shared ``openapi.json``.

``clazzziks/openapi.json`` is the single source of truth for the ``/api`` surface
shared with the React frontend. These tests fail if the backend drifts from it,
keeping both sides honest. Validation uses the schemas declared in the contract
itself, so changing the contract automatically changes what's enforced here.
"""

# pylint: disable=missing-function-docstring,redefined-outer-name,wrong-import-position

import pytest

jsonschema = pytest.importorskip("jsonschema")

from clazzziks.contract import load_contract
from clazzziks.formats import SUPPORTED_FORMATS, AudioFormat, DEFAULT_MP3_BITRATE

# The ``client`` fixture (FastAPI TestClient) lives in conftest.py.


def _validate(instance, schema_name):
    """Validate ``instance`` against a named component schema in the contract.

    The whole contract is used as the validation root so ``$ref`` pointers
    (e.g. AudioFormat referenced inside FormatsConfig) resolve correctly.
    """
    contract = load_contract()
    schema = {**contract, "$ref": f"#/components/schemas/{schema_name}"}
    jsonschema.Draft202012Validator(schema).validate(instance)


# --- the contract document itself ------------------------------------------

def test_contract_is_a_valid_openapi_document():
    contract = load_contract()
    # Well-formed enough for our purposes: version, paths, and the schemas we use.
    assert contract["openapi"].startswith("3.")
    assert "/formats" in contract["paths"]
    assert "/download" in contract["paths"]
    for name in ("FormatsConfig", "Error", "Health", "AudioFormat"):
        assert name in contract["components"]["schemas"]


def test_contract_schemas_are_themselves_valid_json_schema():
    # Catch typos in the hand-written contract (bad keywords, etc.).
    for _, schema in load_contract()["components"]["schemas"].items():
        jsonschema.Draft202012Validator.check_schema(schema)


def test_contract_served_matches_packaged_document(client):
    resp = client.get("/api/openapi.json")
    assert resp.status_code == 200
    assert resp.json() == load_contract()


# --- contract <-> code alignment -------------------------------------------

def test_contract_formats_enum_matches_code():
    enum = load_contract()["components"]["schemas"]["AudioFormat"]["enum"]
    assert enum == SUPPORTED_FORMATS == [f.value for f in AudioFormat]


# --- live responses conform to the contract --------------------------------

def test_health_response_conforms(client):
    _validate(client.get("/api/health").json(), "Health")


def test_formats_response_conforms(client):
    resp = client.get("/api/formats")
    _validate(resp.json(), "FormatsConfig")


def test_formats_defaults_are_consistent_with_code(client):
    data = client.get("/api/formats").json()
    assert data["default_format"] == AudioFormat.MP3.value
    assert data["default_bitrate"] == DEFAULT_MP3_BITRATE
    assert data["default_format"] in data["formats"]


@pytest.mark.parametrize(
    "payload",
    [{"links": ""}, {"links": "not a url"}, {"links": "https://youtu.be/x", "format": "ogg"}],
)
def test_error_responses_conform(client, payload):
    resp = client.post("/api/download", data=payload)
    assert resp.status_code == 400
    _validate(resp.json(), "Error")
