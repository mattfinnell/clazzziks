"""Small helpers for driving the GraphQL API from tests.

Queries/mutations go over ``POST /graphql`` (HTTP 200 with a ``data``/``errors``
body — GraphQL doesn't use HTTP status codes for resolver failures).

The download flow is a background **job**: the ``download`` mutation returns a
``job_id`` and the ``progress(job_id)`` subscription streams per-track events. The
subscription is driven here at the **schema level** (``schema.subscribe``) rather
than over a real WebSocket — deterministic and transport-independent — while the
final ``/files/{token}`` byte stream is still fetched over HTTP through the app.
"""

# pylint: disable=missing-function-docstring

import asyncio
from types import SimpleNamespace

from starlette.datastructures import Headers

from clazzziks.schema import schema

_DOWNLOAD = "mutation ($l: String!) { download(links: $l) { job_id count } }"
_PROGRESS = (
    "subscription ($j: String!) { progress(job_id: $j) { __typename "
    "... on TrackProgress { url title index total state pct error } "
    "... on DownloadComplete { token filename warnings failures } } }"
)


# --- HTTP query/mutation helpers -------------------------------------------

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


# --- download job helpers (schema-level subscription) ----------------------

class _FakeRequest:
    """Minimal stand-in for the Starlette Request the auth permissions read."""

    def __init__(self, headers=None):
        self.headers = Headers(headers or {})
        self.url = SimpleNamespace(path="/graphql")
        self.state = SimpleNamespace(request_id="test")


async def _arun(links, headers):
    """Start a download job and drain its progress subscription to completion.

    Returns ``(events, error)`` — ``events`` is every progress event ending with
    the terminal DownloadComplete; ``error`` is set instead if the mutation failed.
    """
    ctx = {"request": _FakeRequest(headers)}
    start = await schema.execute(_DOWNLOAD, variable_values={"l": links}, context_value=ctx)
    if start.errors:
        return None, str(start.errors[0].message)

    job_id = start.data["download"]["job_id"]
    sub = await schema.subscribe(_PROGRESS, variable_values={"j": job_id}, context_value=ctx)
    if hasattr(sub, "errors"):  # immediate validation error, not a stream
        return None, str(sub.errors[0].message)

    events = []
    async for res in sub:
        event = res.data["progress"]
        events.append(event)
        if event["__typename"] == "DownloadComplete":
            break
    return events, None


def run_download(links, headers=None):
    """Run a download job to completion; return the list of progress events."""
    events, error = asyncio.run(_arun(links, headers))
    assert error is None, error
    return events


def download_error(links, headers=None):
    """Run the download mutation expecting it to fail; return the error message."""
    events, error = asyncio.run(_arun(links, headers))
    assert error is not None, f"expected an error, got events {events}"
    return error


def do_download(client, links, headers=None):
    """Run a download job, then stream the produced file over HTTP.

    Returns ``(files_response, complete_event, events)`` — audio/zip bytes are on
    ``files_response.content``; warnings/failures/token are on ``complete_event``.
    """
    events = run_download(links, headers)
    complete = events[-1]
    assert complete["__typename"] == "DownloadComplete", complete
    token = complete["token"]
    resp = client.get(f"/files/{token}", headers=headers or {}) if token else None
    return resp, complete, events
