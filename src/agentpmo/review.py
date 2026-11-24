"""The human review gate and the acceptance metric.

Nothing becomes a work item until a person accepts it. Every decision is
recorded, so the pilot target (at least 70% of reviewed drafts accepted,
with or without edits) is measured, not estimated.
"""

from __future__ import annotations

from agentpmo.graph import GraphStore, now
from agentpmo.models import WORK_ITEM_TYPES

PILOT_TARGET = 0.70


class ReviewError(ValueError):
    pass


def pending(store: GraphStore) -> list[dict]:
    return store.find_nodes("Draft", status="pending")


def _draft(store: GraphStore, draft_id: str) -> dict:
    node = store.get_node(draft_id)
    if not node or node["label"] != "Draft":
        raise ReviewError(f"No draft with id {draft_id}")
    if node["props"].get("status") != "pending":
        raise ReviewError(f"{draft_id} was already {node['props'].get('status')}")
    return node


def _next_work_item_id(store: GraphStore) -> str:
    row = store.conn.execute("SELECT COUNT(*) FROM nodes WHERE label = 'WorkItem'").fetchone()
    return f"wi-{row[0] + 1:04d}"


def accept(store: GraphStore, draft_id: str, edited_text: str | None = None, reviewer: str | None = None) -> str | None:
    """Accept a draft, optionally with edits. Returns the new work item id, if the kind makes one."""
    node = _draft(store, draft_id)
    original = node["props"]["text"]
    final = (edited_text or "").strip() or original
    decision = "edited" if final != original else "accepted"
    work_item_id = None
    with store:
        store.upsert_node(draft_id, "Draft", status="accepted", final_text=final, reviewed_at=now())
        store.conn.execute(
            "INSERT INTO reviews(draft_id, decision, reviewer, original_text, final_text, at) VALUES (?,?,?,?,?,?)",
            (draft_id, decision, reviewer, original, final, now()),
        )
        kind = node["props"]["kind"]
        if kind in WORK_ITEM_TYPES:
            work_item_id = _next_work_item_id(store)
            store.upsert_node(work_item_id, "WorkItem", title=final, type=WORK_ITEM_TYPES[kind],
                              state="New", source_draft=draft_id, exported_to=[])
            store.add_edge(draft_id, "BECAME", work_item_id)
    return work_item_id


def reject(store: GraphStore, draft_id: str, reason: str | None = None, reviewer: str | None = None) -> None:
    node = _draft(store, draft_id)
    with store:
        store.upsert_node(draft_id, "Draft", status="rejected", reviewed_at=now(), reject_reason=reason)
        store.conn.execute(
            "INSERT INTO reviews(draft_id, decision, reviewer, reason, original_text, at) VALUES (?,?,?,?,?,?)",
            (draft_id, "rejected", reviewer, reason, node["props"]["text"], now()),
        )


def metrics(store: GraphStore, meeting_id: str | None = None) -> dict:
    sql = "SELECT r.decision, COUNT(*) FROM reviews r"
    args: list[str] = []
    if meeting_id:
        sql += " JOIN edges e ON e.src = r.draft_id AND e.rel = 'FROM_MEETING' WHERE e.dst = ?"
        args.append(meeting_id)
    sql += " GROUP BY r.decision"
    counts = {"accepted": 0, "edited": 0, "rejected": 0}
    counts.update({row[0]: row[1] for row in store.conn.execute(sql, args)})
    reviewed = sum(counts.values())
    if meeting_id:
        waiting = len([d for d in store.inbound(meeting_id, "FROM_MEETING") if d["props"].get("status") == "pending"])
    else:
        waiting = len(pending(store))
    rate = (counts["accepted"] + counts["edited"]) / reviewed if reviewed else None
    return {
        "reviewed": reviewed,
        "accepted_as_is": counts["accepted"],
        "accepted_with_edits": counts["edited"],
        "rejected": counts["rejected"],
        "pending": waiting,
        "acceptance_rate": rate,
        "target": PILOT_TARGET,
        "meets_target": rate is not None and rate >= PILOT_TARGET,
    }


def trace(store: GraphStore, node_id: str) -> dict:
    """Walk from a work item (or draft) back to the meeting, segments and people it came from."""
    node = store.get_node(node_id)
    if not node:
        raise ReviewError(f"Nothing with id {node_id}")
    draft = node
    if node["label"] == "WorkItem":
        sources = store.inbound(node_id, "BECAME")
        if not sources:
            raise ReviewError(f"{node_id} has no source draft")
        draft = sources[0]
    elif node["label"] != "Draft":
        raise ReviewError(f"{node_id} is a {node['label']}, not a work item or draft")
    meetings = store.out(draft["id"], "FROM_MEETING")
    evidence = []
    for seg in store.out(draft["id"], "DERIVED_FROM"):
        speaker = store.out(seg["id"], "SPOKEN_BY")
        evidence.append({
            "segment": seg["id"],
            "time": seg["props"].get("start"),
            "speaker": speaker[0]["props"]["name"] if speaker else None,
            "text": seg["props"].get("text"),
        })
    return {
        "work_item": node if node["label"] == "WorkItem" else None,
        "draft": draft,
        "meeting": meetings[0] if meetings else None,
        "raised_by": [p["props"]["name"] for p in store.out(draft["id"], "RAISED_BY")],
        "evidence": evidence,
    }
