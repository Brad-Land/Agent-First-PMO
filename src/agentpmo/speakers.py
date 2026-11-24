"""Map transcript speaker labels to known people.

Meeting tools label speakers inconsistently ("Ortiz, Dana", "Dana O.",
"Speaker 2", a phone number). Extraction runs on resolved people, so
this step runs first and reports anything it could not resolve.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from agentpmo.models import Person

FUZZY_THRESHOLD = 0.85


@dataclass
class Resolution:
    label: str
    person_id: str | None
    method: str  # override | exact | alias | reordered | fuzzy | unresolved
    score: float


def _norm(s: str) -> str:
    s = re.sub(r"\(.*?\)", "", s)  # drop "(Guest)", "(External)"
    s = re.sub(r"[^\w\s,@.-]", "", s)
    return re.sub(r"\s+", " ", s).strip().casefold()


def _reorder(s: str) -> str:
    """'ortiz, dana' -> 'dana ortiz'."""
    if "," in s:
        last, _, first = s.partition(",")
        return f"{first.strip()} {last.strip()}".strip()
    return s


class Roster:
    def __init__(self, people: list[Person], overrides: dict[str, str] | None = None):
        self.people = {p.id: p for p in people}
        self.overrides = {_norm(k): v for k, v in (overrides or {}).items()}
        self._names: dict[str, str] = {}
        self._aliases: dict[str, str] = {}
        for p in people:
            self._names[_norm(p.name)] = p.id
            for a in p.aliases:
                self._aliases[_norm(a)] = p.id
            if p.email:
                self._aliases[_norm(p.email)] = p.id
                self._aliases[_norm(p.email.split("@")[0].replace(".", " "))] = p.id

    @classmethod
    def load(cls, path: str | Path) -> "Roster":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        people = [
            Person(p["id"], p["name"], p.get("email"), list(p.get("aliases", [])))
            for p in data.get("people", [])
        ]
        return cls(people, data.get("overrides", {}))

    @classmethod
    def empty(cls) -> "Roster":
        return cls([])

    def resolve(self, label: str) -> Resolution:
        key = _norm(label)
        if key in self.overrides and self.overrides[key] in self.people:
            return Resolution(label, self.overrides[key], "override", 1.0)
        if key in self._names:
            return Resolution(label, self._names[key], "exact", 1.0)
        if key in self._aliases:
            return Resolution(label, self._aliases[key], "alias", 1.0)
        reordered = _reorder(key)
        if reordered in self._names:
            return Resolution(label, self._names[reordered], "reordered", 0.95)
        best_id, best = None, 0.0
        for name, pid in list(self._names.items()) + list(self._aliases.items()):
            score = SequenceMatcher(None, reordered, name).ratio()
            if score > best:
                best_id, best = pid, score
        if best >= FUZZY_THRESHOLD:
            return Resolution(label, best_id, "fuzzy", round(best, 2))
        return Resolution(label, None, "unresolved", round(best, 2))
