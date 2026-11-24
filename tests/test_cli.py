from agentpmo.cli import main


def test_cli_end_to_end(tmp_path, kickoff, capsys):
    db = str(tmp_path / "pmo.db")
    roster = str(kickoff.parent / "roster.json")
    assert main(["--db", db, "ingest", str(kickoff), "--roster", roster, "--title", "Kickoff"]) == 0
    assert main(["--db", db, "drafts"]) == 0
    first = next(line.split()[0] for line in capsys.readouterr().out.splitlines() if line.startswith("drf-"))
    assert main(["--db", db, "accept", first]) == 0
    assert main(["--db", db, "metrics"]) == 0
    assert "100%" in capsys.readouterr().out
    assert main(["--db", db, "accept", first]) == 1  # second review of the same draft is refused
    assert main(["--db", db, "export", "--target", "ado"]) == 1  # org and project required
