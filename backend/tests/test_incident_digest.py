from flooreplay.domain.hashing import incident_digest


def test_incident_digest_normalizes_instants_but_keeps_rank_order() -> None:
    first = {"cutoff": "2026-09-28T11:00:00+05:30", "ranked_results": [{"id": "A"}, {"id": "B"}]}
    same = {"ranked_results": [{"id": "A"}, {"id": "B"}], "cutoff": "2026-09-28T05:30:00Z"}
    reordered = {"cutoff": same["cutoff"], "ranked_results": [{"id": "B"}, {"id": "A"}]}
    assert incident_digest(first) == incident_digest(same)
    assert incident_digest(first) != incident_digest(reordered)
