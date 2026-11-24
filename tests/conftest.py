from pathlib import Path

import pytest

from agentpmo.graph import GraphStore
from agentpmo.speakers import Roster

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture
def store():
    s = GraphStore(":memory:")
    yield s
    s.close()


@pytest.fixture
def roster():
    return Roster.load(SAMPLES / "roster.json")


@pytest.fixture
def kickoff():
    return SAMPLES / "kickoff.vtt"
