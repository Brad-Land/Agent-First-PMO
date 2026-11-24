"""Proof-of-concept retention: drop transcript text after N days.

Drafts, review decisions and work items stay; the raw meeting text is
replaced with a marker, so traceability shows *that* a segment existed
without keeping what was said.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agentpmo.graph import GraphStore

PURGED = "[purged by retention policy]"


def purge_transcripts(store: GraphStore, older_than_days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    purged = 0
    with store:
        for meeting in store.find_nodes("Meeting"):
            ingested = meeting["props"].get("ingested_at")
            if not ingested or datetime.fromisoformat(ingested) > cutoff:
                continue
            for seg in store.inbound(meeting["id"], "PART_OF"):
                if seg["props"].get("text") != PURGED:
                    store.upsert_node(seg["id"], "Segment", text=PURGED)
                    purged += 1
            store.upsert_node(meeting["id"], "Meeting", transcript_purged=True)
    return purged
