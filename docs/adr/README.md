# Architecture decision records

- **Purpose:** preserve the reasoning behind durable architectural boundaries.
- **Audience:** maintainers and reviewers.
- **Canonical for:** accepted architectural decisions and their consequences.
- **Not canonical for:** current feature proof.

| ADR | Status | Decision |
| --- | --- | --- |
| [0001](0001-host-portable-authority.md) | Accepted | Host owns retrieval/reasoning; Portable owns contracts/publication |
| [0002](0002-parallel-contract-versioning.md) | Accepted | Frozen contracts evolve through parallel profiles |
| [0003](0003-completed-only-presentation.md) | Accepted | Browser and read models expose completed results only |
| [0004](0004-compose-company-analytics.md) | Accepted | Compose analytics and quality around unchanged v3 through ports/adapters |
| [0005](0005-host-native-core-and-legacy-retirement.md) | Accepted | Make the host-native core primary and gate legacy retirement on observable proof |
| [0006](0006-shared-automatic-presentation.md) | Accepted | Reuse one completed-only viewer and return its run URL automatically |
| [0007](0007-stockresearchagents-brand-and-upstream-oracle.md) | Accepted | Separate StockResearchAgents branding from frozen identities and keep upstream as an external oracle |

New ADRs should include context, decision, scope/non-goals, consequences, alternatives, compatibility impact, and validation evidence. Supersede an ADR explicitly rather than rewriting its historical decision.
