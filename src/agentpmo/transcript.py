"""Parse meeting transcripts into speaker segments.

Supports WebVTT (the format Teams exports, with <v Speaker> voice tags)
and plain text lines such as "Dana Ortiz: we need ..." or
"[00:01:02] Dana Ortiz: we need ...".
"""

from __future__ import annotations

import re
from pathlib import Path

from agentpmo.models import Segment

_VOICE = re.compile(r"<v(?:\.[^ >]+)?\s+([^>]+)>(.*?)(?:</v>|$)", re.S)
_TIMING = re.compile(r"^\s*(\S+)\s+-->\s+(\S+)")
_PLAIN = re.compile(r"^\s*(?:\[(?P<ts>[\d:.]+)\]\s*)?(?P<name>[^:\[\]]{1,60}):\s+(?P<text>.+)$")
_TAG = re.compile(r"</?[^>]+>")


def parse_file(path: str | Path) -> list[Segment]:
    text = Path(path).read_text(encoding="utf-8-sig")
    return parse_text(text)


def parse_text(text: str) -> list[Segment]:
    if text.lstrip().startswith("WEBVTT"):
        raw = _parse_vtt(text)
    else:
        raw = _parse_plain(text)
    return _merge_consecutive(raw)


def _parse_vtt(text: str) -> list[Segment]:
    out: list[Segment] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [ln for ln in block.strip().split("\n") if ln.strip()]
        timing_at = next((i for i, ln in enumerate(lines) if _TIMING.match(ln)), None)
        if timing_at is None:
            continue  # header, NOTE or STYLE block
        start, end = _TIMING.match(lines[timing_at]).groups()
        body = " ".join(lines[timing_at + 1 :]).strip()
        if not body:
            continue
        voices = _VOICE.findall(body)
        if voices:
            for speaker, said in voices:
                said = _TAG.sub("", said).strip()
                if said:
                    out.append(Segment(len(out), speaker.strip(), said, start, end))
        else:
            m = _PLAIN.match(_TAG.sub("", body))
            if m:
                out.append(Segment(len(out), m["name"].strip(), m["text"].strip(), start, end))
            else:
                out.append(Segment(len(out), "Unknown", _TAG.sub("", body).strip(), start, end))
    return out


def _parse_plain(text: str) -> list[Segment]:
    out: list[Segment] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _PLAIN.match(line)
        if m:
            out.append(Segment(len(out), m["name"].strip(), m["text"].strip(), m["ts"]))
        elif out:
            # continuation of the previous speaker's turn
            out[-1].text = f"{out[-1].text} {line.strip()}"
    return out


def _merge_consecutive(segments: list[Segment]) -> list[Segment]:
    """Teams splits one turn into many cues; join back-to-back cues by the same speaker."""
    merged: list[Segment] = []
    for seg in segments:
        if merged and merged[-1].speaker_label == seg.speaker_label:
            merged[-1].text = f"{merged[-1].text} {seg.text}"
            merged[-1].end = seg.end or merged[-1].end
        else:
            merged.append(Segment(len(merged), seg.speaker_label, seg.text, seg.start, seg.end))
    return merged
