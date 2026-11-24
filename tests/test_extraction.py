from agentpmo.extraction import HeuristicExtractor, LLMExtractor
from agentpmo.models import Segment


class FakeLLM:
    name = "fake"

    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def complete(self, system, prompt):
        self.prompts.append(prompt)
        return self.reply


def test_heuristic_kinds():
    segs = [
        Segment(0, "A", "We need the form to capture the cost center."),
        Segment(1, "B", "We decided to use single sign-on for the pilot."),
        Segment(2, "C", "I'll send the approval matrix by Friday."),
        Segment(3, "D", "Does finance want a queue in the portal?"),
        Segment(4, "E", "Thanks everyone for joining today."),
    ]
    kinds = [c.kind for c in HeuristicExtractor().extract(segs, {})]
    assert kinds == ["requirement", "decision", "action_item", "open_question"]


def test_llm_output_is_validated():
    reply = """```json
    {"drafts": [
      {"kind": "requirement", "text": "Capture the cost center", "segments": [0], "confidence": 0.9},
      {"kind": "wish", "text": "bad kind", "segments": [0]},
      {"kind": "decision", "text": "Points at a segment that doesn't exist", "segments": [42]},
      {"kind": "action_item", "text": "Send matrix", "segments": ["1"], "confidence": 7}
    ]}
    ```"""
    llm = FakeLLM(reply)
    ext = LLMExtractor(llm)
    out = ext.extract([Segment(0, "A", "x"), Segment(1, "B", "y")], {"A": "Ana", "B": "Bo"})
    assert [(c.kind, c.segment_indexes, c.confidence) for c in out] == [
        ("requirement", [0], 0.9),
        ("action_item", [1], 1.0),
    ]
    assert len(ext.warnings) == 2
    assert "[0] Ana: x" in llm.prompts[0]


def test_llm_garbage_returns_nothing():
    ext = LLMExtractor(FakeLLM("I can't help with that."))
    assert ext.extract([Segment(0, "A", "x")], {}) == []
    assert ext.warnings


def test_llm_chunks_long_transcripts():
    llm = FakeLLM('{"drafts": []}')
    LLMExtractor(llm, chunk_size=2).extract([Segment(i, "A", "x") for i in range(5)], {})
    assert len(llm.prompts) == 3
