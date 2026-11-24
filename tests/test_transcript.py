from agentpmo.transcript import parse_file, parse_text


def test_vtt_voice_tags_and_merging(kickoff):
    segs = parse_file(kickoff)
    # the two opening cues by the same speaker merge into one turn
    assert segs[0].speaker_label == "Ortiz, Dana (Guest)"
    assert "cost center" in segs[0].text and segs[0].start == "00:00:02.100"
    assert [s.index for s in segs] == list(range(len(segs)))
    assert "+1 555 0100" in {s.speaker_label for s in segs}


def test_plain_text_with_timestamps_and_continuations():
    segs = parse_text("[00:01] Ana Ruiz: first line\n  carries on here\nBo Chen: reply\n")
    assert [(s.speaker_label, s.text) for s in segs] == [
        ("Ana Ruiz", "first line carries on here"),
        ("Bo Chen", "reply"),
    ]
    assert segs[0].start == "00:01"


def test_vtt_without_voice_tags():
    segs = parse_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nAna Ruiz: hello there\n")
    assert segs[0].speaker_label == "Ana Ruiz"
