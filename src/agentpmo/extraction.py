"""Turn speaker segments into draft requirements, decisions, action items and questions.

Two extractors share one interface:
- HeuristicExtractor: offline, deterministic, no model needed. Used for
  tests, demos and as a baseline to beat.
- LLMExtractor: prompts any LLMClient for structured JSON and validates it.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from agentpmo.llm import LLMClient
from agentpmo.models import DRAFT_KINDS, DraftCandidate, Segment


class Extractor(Protocol):
    name: str

    def extract(self, segments: list[Segment], speaker_names: dict[str, str]) -> list[DraftCandidate]: ...


_SENTENCE = re.compile(r"(?<=[.!?])\s+")

# Ordered: the first rule that matches a sentence wins.
_RULES: list[tuple[str, re.Pattern[str], float]] = [
    ("decision", re.compile(r"\b(we('ve| have)? decided|decision is|let's go with|we'll go with|agreed (to|that|on)|final answer)\b", re.I), 0.7),
    ("action_item", re.compile(r"\b(I'll|I will|can you|could you|please (send|share|set up|update|draft)|action item|by (monday|tuesday|wednesday|thursday|friday|end of (day|week)))\b", re.I), 0.65),
    ("requirement", re.compile(r"\b(we need|needs? to|must|has to|have to|should (be able|support|capture|allow|show)|requirement|it has to)\b", re.I), 0.6),
    ("open_question", re.compile(r"\?\s*$"), 0.5),
]

_FILLER = re.compile(r"^(so|ok(ay)?|um+|uh+|yeah|right|well|and|also)[,\s]+", re.I)


class HeuristicExtractor:
    name = "heuristic"

    def extract(self, segments: list[Segment], speaker_names: dict[str, str]) -> list[DraftCandidate]:
        out: list[DraftCandidate] = []
        for seg in segments:
            for sentence in _SENTENCE.split(seg.text):
                sentence = sentence.strip()
                if len(sentence.split()) < 4:
                    continue
                for kind, pattern, conf in _RULES:
                    if pattern.search(sentence):
                        text = _FILLER.sub("", sentence)
                        text = text[0].upper() + text[1:] if text else text
                        out.append(DraftCandidate(kind, text, [seg.index], conf, f"matched {kind} pattern"))
                        break
        return out


SYSTEM_PROMPT = """You are a senior business analyst. You read meeting transcripts and draft
project artifacts for a human reviewer. Only use what was said. Do not invent
owners, dates or scope. Respond with JSON only."""

PROMPT_TEMPLATE = """Transcript segments, numbered, with resolved speaker names:

{segments}

Draft the project artifacts this meeting produced. Use these kinds only:
- requirement: something the solution must do or support
- decision: something the group agreed on
- action_item: a task someone took on or was asked to do
- open_question: something raised and left unresolved

Return JSON in exactly this shape:
{{"drafts": [{{"kind": "requirement", "text": "one clear sentence", "segments": [3, 4], "confidence": 0.0}}]}}

"segments" must list the segment numbers the draft came from. "confidence" is 0 to 1.
Return {{"drafts": []}} if there is nothing to draft."""


class LLMExtractor:
    def __init__(self, client: LLMClient, chunk_size: int = 80):
        self.client = client
        self.chunk_size = chunk_size
        self.name = f"llm:{client.name}"
        self.warnings: list[str] = []

    def extract(self, segments: list[Segment], speaker_names: dict[str, str]) -> list[DraftCandidate]:
        out: list[DraftCandidate] = []
        for i in range(0, len(segments), self.chunk_size):
            chunk = segments[i : i + self.chunk_size]
            listing = "\n".join(
                f"[{s.index}] {speaker_names.get(s.speaker_label, s.speaker_label)}: {s.text}" for s in chunk
            )
            raw = self.client.complete(SYSTEM_PROMPT, PROMPT_TEMPLATE.format(segments=listing))
            out.extend(self.parse(raw, {s.index for s in chunk}))
        return out

    def parse(self, raw: str, valid_indexes: set[int]) -> list[DraftCandidate]:
        """Validate model output. Anything malformed is dropped with a warning, never guessed at."""
        payload = _first_json_object(raw)
        if payload is None:
            self.warnings.append("model returned no JSON object")
            return []
        drafts = payload.get("drafts", [])
        if not isinstance(drafts, list):
            self.warnings.append("'drafts' is not a list")
            return []
        out: list[DraftCandidate] = []
        for d in drafts:
            if not isinstance(d, dict):
                continue
            kind = str(d.get("kind", "")).strip().lower()
            text = str(d.get("text", "")).strip()
            segs = [int(x) for x in d.get("segments", []) if str(x).lstrip("-").isdigit()]
            segs = [x for x in segs if x in valid_indexes]
            if kind not in DRAFT_KINDS or not text or not segs:
                self.warnings.append(f"dropped invalid draft: {d!r:.120}")
                continue
            try:
                conf = min(max(float(d.get("confidence", 0.5)), 0.0), 1.0)
            except (TypeError, ValueError):
                conf = 0.5
            out.append(DraftCandidate(kind, text, segs, conf, "llm"))
        return out


def _first_json_object(raw: str) -> dict | None:
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None
