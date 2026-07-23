"""Tests for the background download job + progress subscription (clazzziks.jobs).

Driven at the schema level: start a job via the ``download`` mutation, then drain
its ``progress`` subscription. Downloads are mocked (the fake fires yt-dlp-style
progress-hook dicts), so nothing hits the network. The ``isolated_db`` autouse
fixture (conftest) provides fresh Postgres tables.
"""

# pylint: disable=missing-function-docstring,redefined-outer-name

import asyncio

from clazzziks.downloader import DownloadResult
from clazzziks.schema import schema

from .gql import _FakeRequest, _DOWNLOAD, _PROGRESS


def _fake(tmp_path):
    def dl(url, *, fmt, outdir, bitrate, progress_hook=None):
        if progress_hook:
            progress_hook({"status": "downloading", "downloaded_bytes": 30, "total_bytes": 100})
            progress_hook({"status": "downloading", "downloaded_bytes": 100, "total_bytes": 100})
            progress_hook({"status": "finished"})
        path = tmp_path / (url.rsplit("/", 1)[-1] + ".mp3")
        path.write_bytes(b"x")
        return DownloadResult(path=path, title="T" + url[-2:], source="youtube", fmt=fmt, url=url)
    return dl


async def _start(links):
    ctx = {"request": _FakeRequest()}
    start = await schema.execute(_DOWNLOAD, variable_values={"l": links}, context_value=ctx)
    assert not start.errors, start.errors
    return start.data["download"]["job_id"], ctx


async def _drain(job_id, ctx):
    events = []
    async for res in await schema.subscribe(_PROGRESS, variable_values={"j": job_id}, context_value=ctx):
        events.append(res.data["progress"])
        if res.data["progress"]["__typename"] == "DownloadComplete":
            break
    return events


def test_parallel_all_tracks_complete_with_progress(tmp_path, monkeypatch):
    monkeypatch.setattr("clazzziks.jobs.download_audio", _fake(tmp_path))

    async def scenario():
        job_id, ctx = await _start("https://youtu.be/a1\nhttps://youtu.be/b2\nhttps://youtu.be/c3")
        return await _drain(job_id, ctx)

    events = asyncio.run(scenario())

    # Every one of the three tracks appears and reaches "done".
    indices = {e["index"] for e in events if e["__typename"] == "TrackProgress"}
    assert indices == {0, 1, 2}
    done = {e["index"] for e in events if e.get("state") == "done"}
    assert done == {0, 1, 2}
    # A byte-level percentage surfaced while downloading.
    assert any(
        e["__typename"] == "TrackProgress" and e["state"] == "downloading" and e["pct"] is not None
        for e in events
    )
    # Terminal event carries a token for the zipped bundle.
    assert events[-1]["__typename"] == "DownloadComplete"
    assert events[-1]["token"]


def test_reconnect_replays_full_history(tmp_path, monkeypatch):
    monkeypatch.setattr("clazzziks.jobs.download_audio", _fake(tmp_path))

    async def scenario():
        job_id, ctx = await _start("https://youtu.be/a1\nhttps://youtu.be/b2")
        await _drain(job_id, ctx)            # run to completion
        return await _drain(job_id, ctx)     # re-subscribe after it's done

    replayed = asyncio.run(scenario())
    # A late subscriber still sees the whole story, ending with the terminal event.
    assert any(e.get("state") == "done" for e in replayed)
    assert replayed[-1]["__typename"] == "DownloadComplete"
    assert replayed[-1]["token"]


def test_unknown_job_id_yields_empty_stream():
    async def scenario():
        ctx = {"request": _FakeRequest()}
        events = []
        async for res in await schema.subscribe(_PROGRESS, variable_values={"j": "nope"}, context_value=ctx):
            events.append(res.data["progress"])
        return events

    assert asyncio.run(scenario()) == []
