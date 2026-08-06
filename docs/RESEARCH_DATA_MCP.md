# Research-data MCP adapters

- **Purpose:** document the isolated, provider-neutral SourceBatch v1 research-data server.
- **Audience:** source-adapter authors, harness integrators, and release reviewers.
- **Canonical for:** tool categories, ownership, normalization, failure semantics, and readiness proof.
- **Not canonical for:** credentials, provider accounts, or claims of complete live-company-research parity.

## Current status

`stock-research-data-mcp` launches the separate, read-only research-data server. Its default `PublicResearchDataAdapter` registers seven receipt-backed tools: SEC regulatory filings, fundamentals, and financial statements; GDELT company and global news discovery metadata plus publisher links; World Bank macro observations; and credential-free `prediction_markets` search through Polymarket Gamma. The coordination server owns `company-analytics.v1`, `run-control.v1`, validation, publication, and completed-result reads; it registers none of these retrieval tools.

The implemented status and exact default exposure are machine-readable in [research-data-tools.v1.json](../src/stock_research_agents/workflow/research-data-tools.v1.json). `SourceBatch` v1 is implemented and validated for every response. Registration remains validation-receipt gated: a tool is discoverable only when the configured adapter has a matching receipt.

This is partial live coverage, not complete live company research for an `import` caller. Prices and indicators require an entitled caller `SourcePort`; Yahoo Finance/`yfinance` remains an explicit caller-owned route subject to applicable terms rather than a credential-free default. Reddit requires approved caller-owned OAuth. StockTwits fails closed as denied and is unregistered. FRED and Alpha Vantage are not default providers. The prediction-market tool does not solve these market-data or social/provider gaps. The cross-provider collection policy is defined in [Source portfolio](SOURCE_PORTFOLIO.md).

Hosts that configure more than one provider for a capability can inject the additive `SourcePortfolioCollector`. The server then exposes `research_data_collect_source_portfolio`, which requires at least two explicitly configured routes and returns the terminal deterministic `SourcePortfolioReceipt`. It preserves one `SourceBatch` and entitlement per provider rather than merging them. The seven default tools and their `SourceBatch` wire contracts remain unchanged; the portfolio tool is not exposed by the default public server. The collector is orchestration and auditability, not a provider or an authorization mechanism.

The scheduled live-provider canary probes the credential-free SEC, GDELT, World Bank, and Polymarket routes for ORCL and META twice weekly. It is bounded to eight minutes, uploads only sanitized status/shape evidence for seven days, and is deliberately non-gating because network availability is not a deterministic CI invariant. A passing canary is operational evidence for that run, not proof of arbitrary-symbol freshness or complete live company research.

## Ownership and dependency direction

```text
host/provider MCP or browser
          |
          v
research-data adapter ---- authentication, entitlement, pagination, retries
          |
          v
versioned SourcePort boundary ---- normalized bounded SourceBatch
          |
          v
StockResearchAgents workflow and evidence contracts
```

- Host adapters own provider SDKs, credentials, sessions, terms compliance, retries, and concrete MCP registration.
- The StockResearchAgents core owns normalized versioned requests/responses, cutoff rules, provenance, entitlement declarations, completeness, bounds, and deterministic validation.
- Workflow manifests use semantic capability IDs. They do not import provider SDKs or hard-code a vendor.
- Codex is one adapter, not the data layer. A non-MCP Python/replay adapter must be substitutable.

## Tool status

| Adapter MCP name | Default registration | Provider / gate | Required result or limitation |
| --- | --- | --- | --- |
| `research_data_get_prices` | No | Licensed host `SourcePort` | Point-in-time OHLCV; unavailable without the host port |
| `research_data_get_indicators` | No | Licensed host `SourcePort` | Versioned indicator series; unavailable without the host port |
| `research_data_get_regulatory_filings` | Yes | SEC EDGAR | Filing metadata and bounded normalized facts |
| `research_data_get_fundamentals` | Yes | SEC EDGAR company facts | Requested reported facts available for the resolved issuer |
| `research_data_get_financial_statements` | Yes | SEC EDGAR company facts | Requested statement facts; not a vendor-restated feed |
| `research_data_get_company_news` | Yes | GDELT DOC 2.0 | Discovery metadata and publisher links; `seendate` is a seen-time proxy, not asserted publication time; no article bodies |
| `research_data_get_global_news` | Yes | GDELT DOC 2.0 | Discovery metadata and publisher links; `seendate` is a seen-time proxy, not asserted publication time; no article bodies |
| `research_data_get_macro` | Yes | World Bank API v2 | Current-vintage observations; no historical revision lineage |
| `research_data_get_prediction_markets` | Yes | Polymarket Gamma | Public search/read-only market metadata; current market-implied probabilities only, with no historical snapshot reconstruction |
| `research_data_get_stocktwits` | No | Denied | Approved API access is not configured |
| `research_data_get_reddit` | No | Host OAuth `SourcePort` | Bounded sample only after host OAuth and validation receipt |

The Polymarket adapter uses Gamma public search only. It exposes no wallet, CLOB, order, position, or trading endpoints. Use it only when a prediction market is relevant to a research decision, and treat returned probabilities as market-implied observations—not truth, forecasts, or executable signals. Because current Gamma search does not reconstruct historical market state, it cannot establish an as-of probability snapshot for a historical replay.

Company investor-relations and verified-market-snapshot adapters may be added as separately versioned capabilities. Provider-specific names remain outside the core workflow. Issuer pages or publisher documents must be opened through a caller-owned restricted document port using an opaque reference from prior discovery; the public MCP must not become an arbitrary-URL fetcher.

## Common contract

Every request and response must declare:

- wire schema and capability semantic versions;
- stable query ID and resolved instrument identity;
- cutoff plus requested and effective windows;
- pagination or continuation state and explicit completeness;
- typed status: `complete`, `partial`, `unavailable`, `denied`, `rate_limited`, or `stale`;
- provider and adapter versions, retrieval time, canonical URI, and content digest;
- access class, redistribution permission, terms reference, license receipt, and entitlement limitation;
- bounded facts and, only for redistributable sources, bounded extracts plus limitations; and
- no credential, authorization header, cookie, signed URL secret, or raw licensed body.

The implemented `SourceBatch` v1 contract expresses these fields and rejects unsupported versions, mismatched typed queries, credentials, and credential-bearing signed URLs. When a source is non-redistributable, retained records may contain metadata and a canonical reference only; they must not retain even a bounded extract.

## Validation requirements

Each category needs deterministic fixture and replay tests for:

1. capability-to-query-type validation;
2. exact-cutoff exclusion and requested/effective-date disclosure;
3. source identity, provenance, entitlement, and redistribution enforcement;
4. pagination, partial results, stale data, denial, rate limits, and explicit limitations;
5. raw-content and credential rejection;
6. stable normalization across MCP and direct-Python/replay adapters; and
7. identical canonical terminal semantics from the same recorded corpus.

Social adapters additionally enforce the 30-item maximum, sample size, source divergence, qualitative-only interpretation, and a prohibition on presenting discussion as company fact.

## Live validation matrix

Before claiming complete live coverage for an `import` integration, recorded evidence must include at least:

- two equities on different exchanges;
- one fund or ETF;
- one supported crypto-shaped request;
- one ambiguous symbol and one unsupported or delisted symbol;
- a weekend or exchange-holiday cutoff;
- partial/stale, entitlement-blocked, authentication-denied, rate-limited, and paginated responses.

Every record identifies provider, adapter, harness, configuration digest, and cutoff. Secrets remain host-side.

## Non-goals

- no provider or model credentials in StockResearchAgents state;
- no paywall, authentication, CAPTCHA, or robots bypass;
- no silent provider fallback;
- no claim that a search result is verified evidence until its attributable source is opened; and
- no broker, order, or paper-exchange authority.
