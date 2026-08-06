# Architecture decision records

- **Purpose:** preserve the reasoning behind durable architectural boundaries.
- **Audience:** maintainers and reviewers.
- **Canonical for:** accepted architectural decisions and their consequences.
- **Not canonical for:** current feature proof.

| ADR | Status | Decision |
| --- | --- | --- |
| [0001](0001-host-portable-authority.md) | Accepted | Caller owns retrieval/reasoning; StockResearchAgents core owns contracts/publication |
| [0002](0002-parallel-contract-versioning.md) | Accepted | Strict contracts evolve by versioned composition |
| [0003](0003-completed-only-presentation.md) | Accepted | Browser and read models expose completed results only |
| [0004](0004-compose-company-analytics.md) | Accepted | Compose analytics and quality around unchanged research through ports/adapters |
| [0006](0006-shared-automatic-presentation.md) | Accepted | Reuse one completed-only viewer and return its run URL automatically |

New ADRs should include context, decision, scope/non-goals, consequences, alternatives, contract impact, and validation evidence. Supersede an ADR explicitly rather than rewriting its historical decision.
