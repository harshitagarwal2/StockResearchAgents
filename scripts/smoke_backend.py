"""Dependency-free backend smoke check used before installing MCP."""

from __future__ import annotations

from tradingrearchagents import RunRequest, build_legacy_topology, run_fixture


def main() -> None:
    request = RunRequest(debate_rounds=2, risk_rounds=2)
    topology = build_legacy_topology(request.analysts, request.debate_rounds, request.risk_rounds)
    assert (
        len([stage for stage in topology.stages if stage.id.startswith("research.") and stage.id != "research.manager"])
        == 4
    )
    assert len([stage for stage in topology.stages if stage.id.startswith("risk.")]) == 6
    result, events = run_fixture(request)
    assert result.status.value == "completed"
    assert len(result.research_debate) == 2 * request.debate_rounds
    assert len(result.risk_debate) == 3 * request.risk_rounds
    assert events[-1].status == "completed"
    print(f"ok run={result.run_id} stages={len(topology.stages)} events={len(events)}")


if __name__ == "__main__":
    main()
