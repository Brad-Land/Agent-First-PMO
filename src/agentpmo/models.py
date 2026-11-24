"""Plain data types shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

DRAFT_KINDS = ("requirement", "decision", "action_item", "open_question")

# Which accepted drafts become work items, and what type they get in a tracker.
WORK_ITEM_TYPES = {
    "requirement": "User Story",
    "action_item": "Task",
    "open_question": "Issue",
}


@dataclass
class Segment:
    """One stretch of a transcript spoken by one speaker."""

    index: int
    speaker_label: str
    text: str
    start: str | None = None
    end: str | None = None


@dataclass
class Person:
    id: str
    name: str
    email: str | None = None
    aliases: list[str] = field(default_factory=list)


@dataclass
class DraftCandidate:
    """What an extractor proposes. Becomes a Draft node once stored."""

    kind: str
    text: str
    segment_indexes: list[int]
    confidence: float
    rationale: str = ""
