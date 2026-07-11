"""Small helpers for driving the GraphQL API from tests.

Every operation is a ``POST /graphql`` that returns HTTP 200 with a ``data``
and/or ``errors`` body (GraphQL doesn't use HTTP status codes for resolver
failures). ``do_download`` covers the two-phase download: run the mutation to get
a token, then stream the bytes from ``GET /files/{token}``.
"""

# pylint: disable=missing-function-docstring

DOWNLOAD = "mutation ($l: String!) { download(links: $l) { token filename warnings failures } }"


def gql(client, query, variables=None, headers=None):
    resp = client.post(
        "/graphql",
        json={"query": query, "variables": variables or {}},
        headers=headers or {},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def gql_data(client, query, variables=None, headers=None):
    body = gql(client, query, variables, headers)
    assert "errors" not in body, body["errors"]
    return body["data"]


def gql_error(client, query, variables=None, headers=None):
    body = gql(client, query, variables, headers)
    assert body.get("errors"), f"expected a GraphQL error, got {body}"
    return body["errors"][0]["message"]


def do_download(client, links, headers=None):
    """Run the download mutation and fetch the produced file.

    Returns ``(files_response, download_payload)`` — the audio/zip bytes are on
    ``files_response.content``; warnings/failures are on the payload dict.
    """
    payload = gql_data(client, DOWNLOAD, {"l": links}, headers)["download"]
    resp = client.get(f"/files/{payload['token']}", headers=headers or {})
    return resp, payload


def download_error(client, links, headers=None):
    """Run the download mutation expecting it to fail; return the error message."""
    return gql_error(client, DOWNLOAD, {"l": links}, headers)
