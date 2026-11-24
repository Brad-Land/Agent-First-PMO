"""Ingest: transcript file -> segments -> resolved speakers -> drafts in the graph."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from agentpmo.extraction import Extractor
from agentpmo.graph import GraphStore, now
from agentpmo.speakers import Roster
from agentpmo.transcript import parse_file


@dataclass
class IngestReport:
    meeting_id: str
    segments: int = 0
    drafts: int = 0
    resolved: dict[str, str] = field(default_factory=dict)  # label -> person id
    unresolved: list[str] = field(default_factory=list)
    skipped: bool = False


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "meeting"


def _unknown_id(label: str) -> str:
    return f"unknown-{_slug(label)}"


def ingest(
    store: GraphStore,
    transcript_path: str | Path,
    extractor: Extractor,
    roster: Roster | None = None,
    title: str | None = None,
    held_on: str | None = None,
    force: bool = False,
) -> IngestReport:
    path = Path(transcript_path)
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()[:10]
    title = title or path.stem.replace("_", " ").replace("-", " ").title()
    meeting_id = f"mtg-{_slug(title)}-{digest}"
    report = IngestReport(meeting_id)

    if store.get_node(meeting_id):
        if not force:
            report.skipped = True
            return report
        with store:  # re-ingest replaces this meeting's segments and drafts
            for node in store.inbound(meeting_id, "FROM_MEETING") + store.inbound(meeting_id, "PART_OF"):
                store.delete_node(node["id"])
            store.delete_node(meeting_id)

    roster = roster or Roster.empty()
    segments = parse_file(path)
    report.segments = len(segments)

    with store:
        store.upsert_node(
            meeting_id, "Meeting", title=title, held_on=held_on, source_file=path.name,
            sha256_prefix=digest, ingested_at=now(), extractor=extractor.name,
        )

        # 1. resolve every distinct speaker before extraction
        person_for_label: dict[str, str] = {}
        for label in dict.fromkeys(s.speaker_label for s in segments):
            res = roster.resolve(label)
            if res.person_id:
                p = roster.people[res.person_id]
                store.upsert_node(p.id, "Person", name=p.name, email=p.email)
                person_for_label[label] = p.id
                report.resolved[label] = p.id
            else:
                pid = _unknown_id(label)
                store.upsert_node(pid, "Person", name=label, unresolved=True)
                person_for_label[label] = pid
                report.unresolved.append(label)
            store.add_edge(person_for_label[label], "ATTENDED", meeting_id, resolved_by=res.method, score=res.score)

        # 2. store segments with who said them
        seg_ids: dict[int, str] = {}
        for s in segments:
            sid = f"{meeting_id}:seg-{s.index:04d}"
            seg_ids[s.index] = sid
            store.upsert_node(sid, "Segment", index=s.index, text=s.text, start=s.start, end=s.end,
                              speaker_label=s.speaker_label)
            store.add_edge(sid, "PART_OF", meeting_id)
            store.add_edge(sid, "SPOKEN_BY", person_for_label[s.speaker_label])

        # 3. extract drafts, each linked to its evidence
        names = {label: (store.get_node(pid) or {}).get("props", {}).get("name", label)
                 for label, pid in person_for_label.items()}
        for n, cand in enumerate(extractor.extract(segments, names)):
            did = f"drf-{digest}-{n:03d}"
            store.upsert_node(did, "Draft", kind=cand.kind, text=cand.text, confidence=cand.confidence,
                              rationale=cand.rationale, status="pending", extractor=extractor.name)
            store.add_edge(did, "FROM_MEETING", meeting_id)
            raisers: list[str] = []
            for idx in cand.segment_indexes:
                if idx in seg_ids:
                    store.add_edge(did, "DERIVED_FROM", seg_ids[idx])
                    raisers.append(person_for_label[segments[idx].speaker_label])
            for pid in dict.fromkeys(raisers):
                store.add_edge(did, "RAISED_BY", pid)
            report.drafts += 1
    return report
