"""One-way export of accepted work items to a tracker.

This version builds the exact request bodies for Azure DevOps and Jira and
writes them to a file (dry run). It makes no network calls. The team's
tracker stays the system of record; nothing is ever read back.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Protocol

from agentpmo.graph import GraphStore, now
from agentpmo.review import trace


class Exporter(Protocol):
    target: str

    def payload(self, item: dict, context: dict) -> dict: ...


def _description(item: dict, context: dict) -> str:
    lines = [item["props"]["title"], ""]
    if context.get("meeting"):
        m = context["meeting"]["props"]
        lines.append(f"Source: {m.get('title')} ({m.get('held_on') or 'date not set'})")
    if context.get("raised_by"):
        lines.append("Raised by: " + ", ".join(context["raised_by"]))
    for ev in context.get("evidence", []):
        lines.append(f'> {ev["speaker"]}: "{ev["text"]}"')
    lines.append(f"Drafted by agentpmo, accepted in review ({item['id']}).")
    return "\n".join(lines)


class AzureDevOpsExporter:
    target = "ado"

    def __init__(self, organization: str, project: str, api_version: str = "7.1"):
        self.organization = organization
        self.project = project
        self.api_version = api_version

    def payload(self, item: dict, context: dict) -> dict:
        wi_type = item["props"]["type"]
        return {
            "method": "POST",
            "url": (f"https://dev.azure.com/{self.organization}/{self.project}"
                    f"/_apis/wit/workitems/${wi_type.replace(' ', '%20')}?api-version={self.api_version}"),
            "content_type": "application/json-patch+json",
            "body": [
                {"op": "add", "path": "/fields/System.Title", "value": item["props"]["title"][:255]},
                {"op": "add", "path": "/fields/System.Description",
                 "value": "<br>".join(html.escape(ln) for ln in _description(item, context).split("\n"))},
                {"op": "add", "path": "/fields/System.Tags", "value": "agentpmo"},
            ],
        }


class JiraExporter:
    target = "jira"
    ISSUE_TYPES = {"User Story": "Story", "Task": "Task", "Issue": "Task"}

    def __init__(self, project_key: str):
        self.project_key = project_key

    def payload(self, item: dict, context: dict) -> dict:
        return {
            "method": "POST",
            "url": "/rest/api/2/issue",
            "content_type": "application/json",
            "body": {"fields": {
                "project": {"key": self.project_key},
                "summary": item["props"]["title"][:255],
                "description": _description(item, context),
                "issuetype": {"name": self.ISSUE_TYPES.get(item["props"]["type"], "Task")},
                "labels": ["agentpmo"],
            }},
        }


def export(store: GraphStore, exporter: Exporter, out_path: str | Path, include_exported: bool = False) -> int:
    items = [
        wi for wi in store.find_nodes("WorkItem")
        if include_exported or exporter.target not in wi["props"].get("exported_to", [])
    ]
    payloads = [{"work_item": wi["id"], **exporter.payload(wi, trace(store, wi["id"]))} for wi in items]
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payloads, indent=2), encoding="utf-8")
    with store:
        for wi in items:
            targets = sorted(set(wi["props"].get("exported_to", [])) | {exporter.target})
            store.upsert_node(wi["id"], "WorkItem", exported_to=targets, last_exported_at=now())
    return len(payloads)
