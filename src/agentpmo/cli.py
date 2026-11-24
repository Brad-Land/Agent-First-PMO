"""Command line interface: pmo <command>."""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap

from agentpmo.extraction import HeuristicExtractor, LLMExtractor
from agentpmo.graph import GraphStore
from agentpmo.llm import client_from_env
from agentpmo.pipeline import ingest
from agentpmo.retention import purge_transcripts
from agentpmo.review import ReviewError, accept, metrics, pending, reject, trace
from agentpmo.speakers import Roster
from agentpmo.sync import AzureDevOpsExporter, JiraExporter, export


def _extractor(kind: str):
    if kind == "heuristic":
        return HeuristicExtractor()
    return LLMExtractor(client_from_env(kind))


def _wrap(text: str, indent: str = "    ") -> str:
    return textwrap.fill(text, width=88, initial_indent=indent, subsequent_indent=indent)


def cmd_ingest(store: GraphStore, a: argparse.Namespace) -> int:
    roster = Roster.load(a.roster) if a.roster else None
    extractor = _extractor(a.extractor)
    rep = ingest(store, a.transcript, extractor, roster, a.title, a.date, a.force)
    if rep.skipped:
        print(f"Already ingested as {rep.meeting_id}. Use --force to replace its drafts.")
        return 0
    print(f"Meeting {rep.meeting_id}: {rep.segments} segments, {rep.drafts} drafts ({extractor.name})")
    for label, pid in rep.resolved.items():
        print(f"  speaker '{label}' -> {pid}")
    for label in rep.unresolved:
        print(f"  speaker '{label}' -> UNRESOLVED (add to the roster or an override)")
    for w in getattr(extractor, "warnings", []):
        print(f"  warning: {w}")
    return 0


def cmd_drafts(store: GraphStore, a: argparse.Namespace) -> int:
    drafts = pending(store) if a.status == "pending" else store.find_nodes("Draft", **(
        {} if a.status == "all" else {"status": a.status}))
    if not drafts:
        print("No drafts.")
        return 0
    for d in drafts:
        p = d["props"]
        who = ", ".join(x["props"]["name"] for x in store.out(d["id"], "RAISED_BY"))
        print(f"{d['id']}  [{p['kind']}] conf={p['confidence']:.2f} status={p['status']}  raised by {who}")
        print(_wrap(p.get("final_text") or p["text"]))
    return 0


def cmd_accept(store: GraphStore, a: argparse.Namespace) -> int:
    wi = accept(store, a.draft_id, a.text, a.reviewer)
    print(f"Accepted {a.draft_id}" + (f" -> work item {wi}" if wi else " (recorded; decisions make no work item)"))
    return 0


def cmd_reject(store: GraphStore, a: argparse.Namespace) -> int:
    reject(store, a.draft_id, a.reason, a.reviewer)
    print(f"Rejected {a.draft_id}")
    return 0


def cmd_metrics(store: GraphStore, a: argparse.Namespace) -> int:
    m = metrics(store, a.meeting)
    if a.json:
        print(json.dumps(m, indent=2))
        return 0
    rate = "n/a" if m["acceptance_rate"] is None else f"{m['acceptance_rate']:.0%}"
    print(f"Reviewed {m['reviewed']}: {m['accepted_as_is']} accepted, {m['accepted_with_edits']} accepted with edits, "
          f"{m['rejected']} rejected; {m['pending']} pending")
    verdict = "meets" if m["meets_target"] else "below"
    print(f"Acceptance rate {rate} ({verdict} the {m['target']:.0%} pilot target)" if m["reviewed"] else
          f"No reviews yet (pilot target {m['target']:.0%})")
    return 0


def cmd_trace(store: GraphStore, a: argparse.Namespace) -> int:
    t = trace(store, a.node_id)
    d = t["draft"]["props"]
    if t["work_item"]:
        wi = t["work_item"]["props"]
        print(f"{a.node_id}: {wi['type']} '{wi['title']}'")
    print(f"From draft {t['draft']['id']} [{d['kind']}], status {d['status']}")
    if t["meeting"]:
        m = t["meeting"]["props"]
        print(f"Meeting: {m['title']} ({m.get('held_on') or 'date not set'})")
    print("Raised by: " + (", ".join(t["raised_by"]) or "unknown"))
    for ev in t["evidence"]:
        print(f"  [{ev['time'] or '-'}] {ev['speaker']}: {ev['text']}")
    return 0


def cmd_export(store: GraphStore, a: argparse.Namespace) -> int:
    if a.target == "ado":
        if not (a.org and a.project):
            raise ReviewError("--org and --project are required for Azure DevOps")
        exporter = AzureDevOpsExporter(a.org, a.project)
    else:
        if not a.project:
            raise ReviewError("--project (the Jira project key) is required for Jira")
        exporter = JiraExporter(a.project)
    out = a.out or f"exports/{a.target}-payloads.json"
    n = export(store, exporter, out, a.all)
    print(f"Wrote {n} {a.target} request(s) to {out} (dry run: nothing was sent)")
    return 0


def cmd_purge(store: GraphStore, a: argparse.Namespace) -> int:
    n = purge_transcripts(store, a.older_than_days)
    print(f"Purged text from {n} segment(s)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pmo", description="Agent-first PMO: transcripts in, reviewed work items out")
    p.add_argument("--db", default=os.environ.get("PMO_DB", "pmo.db"), help="SQLite graph file (default: pmo.db)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("ingest", help="parse a transcript, resolve speakers and draft artifacts")
    s.add_argument("transcript")
    s.add_argument("--roster", help="JSON roster of known people, aliases and overrides")
    s.add_argument("--title")
    s.add_argument("--date", help="meeting date, e.g. 2026-11-20")
    s.add_argument("--extractor", choices=["heuristic", "bedrock", "openai"],
                   default=os.environ.get("PMO_EXTRACTOR", "heuristic"))
    s.add_argument("--force", action="store_true", help="re-ingest and replace this meeting's drafts")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("drafts", help="list drafts")
    s.add_argument("--status", choices=["pending", "accepted", "rejected", "all"], default="pending")
    s.set_defaults(fn=cmd_drafts)

    s = sub.add_parser("accept", help="accept a draft, optionally with edited text")
    s.add_argument("draft_id")
    s.add_argument("--text", help="edited wording to accept instead")
    s.add_argument("--reviewer")
    s.set_defaults(fn=cmd_accept)

    s = sub.add_parser("reject", help="reject a draft")
    s.add_argument("draft_id")
    s.add_argument("--reason")
    s.add_argument("--reviewer")
    s.set_defaults(fn=cmd_reject)

    s = sub.add_parser("metrics", help="acceptance rate against the pilot target")
    s.add_argument("--meeting")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_metrics)

    s = sub.add_parser("trace", help="show where a work item or draft came from")
    s.add_argument("node_id")
    s.set_defaults(fn=cmd_trace)

    s = sub.add_parser("export", help="write tracker request bodies for accepted work items (dry run)")
    s.add_argument("--target", choices=["ado", "jira"], required=True)
    s.add_argument("--org", help="Azure DevOps organization")
    s.add_argument("--project", help="Azure DevOps project, or Jira project key")
    s.add_argument("--out")
    s.add_argument("--all", action="store_true", help="include items already exported")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("purge", help="drop transcript text older than N days")
    s.add_argument("--older-than-days", type=int, required=True)
    s.set_defaults(fn=cmd_purge)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = GraphStore(args.db)
    try:
        return args.fn(store, args)
    except (ReviewError, RuntimeError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
