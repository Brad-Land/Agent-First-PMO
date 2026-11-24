import json

import pytest

from agentpmo.extraction import HeuristicExtractor
from agentpmo.pipeline import ingest
from agentpmo.retention import PURGED, purge_transcripts
from agentpmo.review import ReviewError, accept, metrics, pending, reject, trace
from agentpmo.sync import AzureDevOpsExporter, JiraExporter, export


def _ingest(store, kickoff, roster, **kw):
    return ingest(store, kickoff, HeuristicExtractor(), roster, "Purchase portal kickoff", "2026-11-20", **kw)


def test_ingest_builds_graph(store, kickoff, roster):
    rep = _ingest(store, kickoff, roster)
    assert rep.unresolved == ["+1 555 0100"]
    assert rep.drafts == len(pending(store)) > 0
    attendees = {p["id"] for p in store.inbound(rep.meeting_id, "ATTENDED")}
    assert {"p-dana", "p-sam", "p-priya", "p-lee"} <= attendees
    for d in pending(store):
        assert store.out(d["id"], "DERIVED_FROM"), "every draft points at its evidence"
        assert store.out(d["id"], "RAISED_BY")


def test_ingest_is_idempotent_unless_forced(store, kickoff, roster):
    first = _ingest(store, kickoff, roster)
    assert _ingest(store, kickoff, roster).skipped
    accept(store, pending(store)[0]["id"])
    again = _ingest(store, kickoff, roster, force=True)
    assert not again.skipped and len(pending(store)) == first.drafts


def test_review_gate_and_metrics(store, kickoff, roster):
    _ingest(store, kickoff, roster)
    ids = [d["id"] for d in pending(store)]
    wi = accept(store, ids[0])
    assert wi == "wi-0001"
    accept(store, ids[1], edited_text="Route requests over $5,000 to finance.")
    reject(store, ids[2], reason="not needed")
    with pytest.raises(ReviewError):
        accept(store, ids[0])
    m = metrics(store)
    assert (m["reviewed"], m["accepted_as_is"], m["accepted_with_edits"], m["rejected"]) == (3, 1, 1, 1)
    assert m["acceptance_rate"] == pytest.approx(2 / 3)
    assert m["meets_target"] is False
    assert m["pending"] == len(ids) - 3


def test_decisions_are_recorded_without_work_items(store, kickoff, roster):
    _ingest(store, kickoff, roster)
    decision = next(d for d in pending(store) if d["props"]["kind"] == "decision")
    assert accept(store, decision["id"]) is None


def test_trace_back_to_speaker(store, kickoff, roster):
    _ingest(store, kickoff, roster)
    draft = next(d for d in pending(store) if "five thousand" in d["props"]["text"])
    wi = accept(store, draft["id"])
    t = trace(store, wi)
    assert t["raised_by"] == ["Sam Whitfield"]
    assert t["meeting"]["props"]["title"] == "Purchase portal kickoff"
    assert "five thousand" in t["evidence"][0]["text"]


def test_export_is_one_way_and_marks_items(store, kickoff, roster, tmp_path):
    _ingest(store, kickoff, roster)
    for d in pending(store)[:2]:
        accept(store, d["id"])
    out = tmp_path / "ado.json"
    assert export(store, AzureDevOpsExporter("contoso", "Purchasing"), out) == 2
    payloads = json.loads(out.read_text())
    assert payloads[0]["url"].startswith("https://dev.azure.com/contoso/Purchasing/_apis/wit/workitems/$User%20Story")
    assert payloads[0]["body"][0]["path"] == "/fields/System.Title"
    assert "&quot;" in payloads[0]["body"][1]["value"]  # description is HTML-escaped
    assert export(store, AzureDevOpsExporter("contoso", "Purchasing"), out) == 0  # already exported
    assert export(store, JiraExporter("PUR"), tmp_path / "jira.json") == 2  # separate target


def test_purge_keeps_trace_but_drops_text(store, kickoff, roster):
    _ingest(store, kickoff, roster)
    wi = accept(store, pending(store)[0]["id"])
    assert purge_transcripts(store, older_than_days=0) > 0
    t = trace(store, wi)
    assert t["evidence"][0]["text"] == PURGED
    assert t["work_item"]["props"]["title"]  # the accepted work item itself is kept
