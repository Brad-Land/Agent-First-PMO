import pytest


@pytest.mark.parametrize(
    "label, person, method",
    [
        ("Dana Ortiz", "p-dana", "exact"),
        ("Ortiz, Dana (Guest)", "p-dana", "reordered"),
        ("Dana O.", "p-dana", "alias"),
        ("Speaker 3", "p-lee", "override"),
        ("dana.ortiz@example.com", "p-dana", "alias"),
        ("Sam Whitfeld", "p-sam", "fuzzy"),
    ],
)
def test_resolution(roster, label, person, method):
    res = roster.resolve(label)
    assert (res.person_id, res.method) == (person, method)


def test_unknown_stays_unresolved(roster):
    res = roster.resolve("+1 555 0100")
    assert res.person_id is None and res.method == "unresolved"
