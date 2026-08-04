/* Packaged final-dossier renderer. */
(() => {
  "use strict";

  const q = (selector) => document.querySelector(selector);
  const list = (value) => (Array.isArray(value) ? value : []);
  const record = (value) => (value && typeof value === "object" && !Array.isArray(value) ? value : {});
  const RESEARCH_SNAPSHOT_ROLES = [
    ["bull", "Bull Researcher"],
    ["bear", "Bear Researcher"]
  ];
  const RISK_SNAPSHOT_ROLES = [
    ["aggressive", "Aggressive Analyst"],
    ["conservative", "Conservative Analyst"],
    ["neutral", "Neutral Analyst"]
  ];
  const SOURCE_QUALITY_ORDER = [
    "primary_regulatory",
    "primary_company",
    "primary_agency",
    "primary_partner",
    "established_market_data",
    "reputable_journalism",
    "aggregator_discovery",
    "public_discussion",
    "synthetic_fixture",
    "unknown"
  ];

  function text(value, fallback = "—") {
    if (value === null || value === undefined || value === "") return fallback;
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (typeof value === "string" || typeof value === "number") return String(value);
    return fallback;
  }

  function humanize(value, fallback = "—") {
    const source = text(value, fallback);
    if (source === fallback) return fallback;
    return source.replace(/[._-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function date(value) {
    const source = text(value, "");
    const parsed = /^\d{4}-\d{2}-\d{2}$/.test(source) ? new Date(`${source}T12:00:00`) : new Date(source);
    if (!Number.isFinite(parsed.getTime())) return text(value);
    return new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" }).format(parsed);
  }

  function timestamp(value) {
    const parsed = new Date(value || "");
    if (!Number.isFinite(parsed.getTime())) return text(value);
    const formatted = new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC"
    }).format(parsed);
    return `${formatted} UTC`;
  }

  function percentage(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return "—";
    return `${Math.round(parsed * 100)}%`;
  }

  function daySpan(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return "Not declared";
    return `${parsed.toLocaleString()} ${parsed === 1 ? "day" : "days"}`;
  }

  function scalar(value) {
    if (Array.isArray(value)) {
      if (value.length && value.every((item) => item && typeof item === "object")) {
        return `${value.length} structured ${value.length === 1 ? "record" : "records"}`;
      }
      return value.map((item) => text(item)).join(", ");
    }
    if (value && typeof value === "object") return Object.keys(value).join(", ") || "—";
    return text(value);
  }

  function node(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined && content !== null) element.textContent = String(content);
    return element;
  }

  function cleanMarkdownText(value) {
    return text(value, "").replace(/\*\*|__|`/g, "").trim();
  }

  function richText(value, fallback = "—") {
    const container = node("div", "rich-text");
    const source = text(value, fallback).replace(/\r\n/g, "\n");
    source.split(/\n{2,}/).forEach((rawBlock) => {
      const block = rawBlock.trim();
      if (!block) return;
      const heading = block.match(/^#{2,4}\s+(.+)$/s);
      if (heading && !heading[1].includes("\n")) {
        container.append(node("h4", "", cleanMarkdownText(heading[1])));
        return;
      }
      const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
      if (lines.length && lines.every((line) => /^[-*]\s+/.test(line))) {
        const items = node("ul");
        lines.forEach((line) => items.append(node("li", "", cleanMarkdownText(line.replace(/^[-*]\s+/, "")))));
        container.append(items);
        return;
      }
      container.append(node("p", "", cleanMarkdownText(lines.join(" "))));
    });
    if (!container.childElementCount) container.append(node("p", "", fallback));
    return container;
  }

  function publicSourceLink(value) {
    const uri = text(value, "");
    try {
      const parsed = new URL(uri);
      if (!["http:", "https:"].includes(parsed.protocol)) return node("span", "", text(value));
      if (parsed.username || parsed.password) return node("span", "", "Source URL withheld");
      if (parsed.hostname.toLowerCase().endsWith(".invalid")) {
        return node("span", "", "Synthetic placeholder · not a public link");
      }
      const link = node("a", "source-link", uri);
      link.href = parsed.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      return link;
    } catch (_error) {
      return node("span", "", text(value));
    }
  }

  function set(selector, value, fallback = "—") {
    const element = q(selector);
    if (element) element.textContent = text(value, fallback);
  }

  function replace(selector, children) {
    const element = q(selector);
    if (element) element.replaceChildren(...children);
  }

  function replaceRich(selector, value, fallback = "—") {
    replace(selector, [richText(value, fallback)]);
  }

  function emptyItem(copy) {
    return node("li", "empty-row", copy);
  }

  function renderList(selector, values, emptyCopy) {
    const items = list(values).map((value) => node("li", "", text(value)));
    replace(selector, items.length ? items : [emptyItem(emptyCopy)]);
  }

  function renderDefinitionList(selector, entries) {
    const rows = [];
    entries.forEach(([label, value, detail]) => {
      const wrapper = node("div", "definition-row");
      const term = node("dt", "", label);
      const description = node("dd");
      description.append(node("b", "", scalar(value)));
      if (detail) description.append(node("small", "", detail));
      wrapper.append(term, description);
      rows.push(wrapper);
    });
    replace(selector, rows.length ? rows : [node("div", "empty-row", "No fields declared in RunView.")]);
  }

  function evidenceLookup(view) {
    return new Map(list(view.evidence).map((item) => [String(item.id), item]));
  }

  function evidenceNames(ids, lookup) {
    return list(ids).map((id) => {
      const item = lookup.get(String(id));
      return item ? text(item.title, id) : String(id);
    });
  }

  function snapshotRoleEntries(snapshot, roleDefinitions) {
    const histories = record(record(snapshot).role_histories);
    return roleDefinitions.flatMap(([key, label]) => {
      const position = text(histories[key], "");
      return position ? [{ speaker: label, position, snapshot: true }] : [];
    });
  }

  function resolveDebateEntries(turns, snapshot, roleDefinitions) {
    const normalizedTurns = list(turns);
    return normalizedTurns.length ? normalizedTurns : snapshotRoleEntries(snapshot, roleDefinitions);
  }

  function renderHero(view) {
    const overview = record(view.overview);
    const dossier = record(view.research_dossier);
    const researchRequest = record(view.research_request);
    const portableRequest = record(view.request);
    const research = record(record(view.decisions).research);
    const risk = record(record(view.decisions).risk);
    const portfolio = record(record(view.decisions).portfolio);
    const signal = record(view.signal);
    const companyName = text(overview.company_name || overview.company_of_interest || record(view.request).company_name, "");
    const researchMode = researchRequest.research_mode || portableRequest.research_mode || dossier.research_mode;
    const subject = companyName || text(overview.symbol, "Company");
    const title = `${subject} · Completed Research Dossier`;

    set("#data-source-label", `Completed read model · ${text(view.run_id)}`);
    set("#run-status", humanize(overview.status));
    set("#asset-class", humanize(overview.asset_type));
    set("#symbol", overview.symbol);
    set("#report-title", title);
    set("#decision-summary", portfolio.executive_summary);
    set("#analysis-date", date(overview.as_of_date));
    set("#research-mode", humanize(researchMode), "Not declared");
    set("#run-id", view.run_id);
    set("#completed-at", timestamp(overview.completed_at));
    set("#research-confidence", percentage(research.confidence));
    set("#decision-action", humanize(portfolio.rating));
    set("#risk-level", humanize(risk.risk_level));
    set("#processed-signal", humanize(signal.processed_signal));
    set("#signal-meaning", signal.meaning);

    const status = q("#run-status");
    if (status) status.dataset.tone = overview.status === "completed" ? "complete" : "caution";
  }

  function renderExecutive(view) {
    const decisions = record(view.decisions);
    const research = record(decisions.research);
    const portfolio = record(decisions.portfolio);
    set("#portfolio-rating", humanize(portfolio.rating));
    set("#portfolio-summary", portfolio.executive_summary);
    set("#portfolio-thesis", portfolio.investment_thesis);
    set("#portfolio-price-target", portfolio.price_target, "Not specified");
    set("#portfolio-time-horizon", portfolio.time_horizon, "Not specified");
    set("#portfolio-disclaimer", portfolio.disclaimer);
    set("#research-recommendation", humanize(research.recommendation));
    set("#research-rationale", research.rationale);
    set("#research-strategic-actions", research.strategic_actions);
    set("#supporting-turns", list(research.supporting_turns).join(", "), "None declared");
  }

  function declaredSourceQuality(entry, lookup) {
    const direct = text(record(entry).source_quality, "");
    if (SOURCE_QUALITY_ORDER.includes(direct)) return direct;
    const evidence = lookup.get(String(record(entry).evidence_id));
    const inherited = text(record(record(evidence).values).source_quality, "unknown");
    return SOURCE_QUALITY_ORDER.includes(inherited) ? inherited : "unknown";
  }

  function traceNode(step, title, linkKind, headline, detail, references = []) {
    const item = node("li", "trace-node");
    item.dataset.link = linkKind;
    const header = node("header");
    header.append(node("span", "trace-step", String(step).padStart(2, "0")), node("span", "trace-status", humanize(linkKind)));
    item.append(header, node("h3", "", title), node("strong", "", headline), node("p", "", detail));
    const receipt = node("small", "trace-references", list(references).join(" · ") || "No direct references declared");
    item.append(receipt);
    return item;
  }

  function renderDecisionTrace(view) {
    const lookup = evidenceLookup(view);
    const evidenceIds = Array.from(lookup.keys());
    const reports = list(view.analyst_reports);
    const analystReferences = reports.flatMap((report) => list(report.evidence_ids).map(String));
    const analystMissing = analystReferences.filter((id) => !lookup.has(id));
    const researchTurns = list(record(record(view.debates).research).turns);
    const researchReferences = researchTurns.flatMap((turn) => list(turn.evidence_ids).map(String));
    const researchMissing = researchReferences.filter((id) => !lookup.has(id));
    const riskTurns = list(record(record(view.debates).risk).turns);
    const riskReferences = riskTurns.flatMap((turn) => list(turn.evidence_ids).map(String));
    const riskMissing = riskReferences.filter((id) => !lookup.has(id));
    const researchDecision = record(record(view.decisions).research);
    const portfolio = record(record(view.decisions).portfolio);
    const intelligence = record(view.intelligence);
    const coverage = record(intelligence.coverage);
    const qualities = Object.entries(record(coverage.source_quality_buckets)).map(([quality, count]) => `${humanize(quality)} ${count}`);
    const supportingTurns = list(researchDecision.supporting_turns).map(String);
    let riskLinkKind = "missing";
    if (riskTurns.length) riskLinkKind = "projected";
    if (riskReferences.length && !riskMissing.length) riskLinkKind = "explicit";

    const nodes = [
      traceNode(
        1,
        "Evidence",
        evidenceIds.length ? "explicit" : "missing",
        `${evidenceIds.length} retained records`,
        `${text(coverage.limitation_count, 0)} limitations · ${qualities.join(" · ") || "source quality not declared"}`,
        evidenceIds
      ),
      traceNode(
        2,
        "Analyst claims",
        analystReferences.length && !analystMissing.length ? "explicit" : "missing",
        `${reports.length} independent reports`,
        analystMissing.length ? `${analystMissing.length} unresolved evidence references` : `${analystReferences.length} explicit evidence references`,
        analystReferences
      ),
      traceNode(
        3,
        "Bull / bear",
        researchReferences.length && !researchMissing.length ? "explicit" : "missing",
        `${researchTurns.length} preserved turns`,
        researchMissing.length ? `${researchMissing.length} unresolved evidence references` : "Ordered challenge history with retained evidence IDs",
        researchTurns.map((turn) => `turn ${text(turn.turn)}`)
      ),
      traceNode(
        4,
        "Research manager",
        supportingTurns.length ? "explicit" : "projected",
        humanize(researchDecision.recommendation),
        supportingTurns.length ? "Decision names supporting debate turns" : "No supporting-turn attribution declared",
        supportingTurns.map((turn) => `turn ${turn}`)
      ),
      traceNode(
        5,
        "Risk review",
        riskLinkKind,
        `${riskTurns.length} preserved turns`,
        riskReferences.length ? `${riskReferences.length} evidence references across risk perspectives` : "Risk history is present without direct evidence references",
        riskTurns.map((turn) => `turn ${text(turn.turn)}`)
      ),
      traceNode(
        6,
        "Portfolio rating",
        "projected",
        humanize(portfolio.rating),
        "Attribution gap: PortfolioDecision has no direct evidence-ID field; this link is a transparent projection from the completed manager and risk record.",
        []
      )
    ];
    replace("#decision-trace-chain", nodes);

    const changes = list(intelligence.monitoring_conditions).map((condition) => {
      const entry = record(condition);
      const item = node("li");
      item.append(
        node("p", "", text(entry.condition || entry.trigger || entry.title || entry.monitoring_condition)),
        node("small", "", `${text(entry.evidence_id, entry.source || "Declared research condition")} · ${humanize(entry.category, "Cross-stage")}`)
      );
      return item;
    });
    replace("#decision-trace-change", changes.length ? changes : [emptyItem("No structured view-change condition was declared.")]);
  }

  function renderCountGroups(selector, groups) {
    const sections = groups.map(([title, values]) => {
      const section = node("section", "count-group");
      section.append(node("h4", "", title));
      const ledger = node("dl");
      const entries = Object.entries(record(values));
      entries.forEach(([label, value]) => {
        const row = node("div");
        row.append(node("dt", "", humanize(label)), node("dd", "", scalar(value)));
        ledger.append(row);
      });
      section.append(entries.length ? ledger : node("p", "empty-row", "No declared values."));
      return section;
    });
    replace(selector, sections);
  }

  function statusChip(value) {
    const status = text(value, "unassessed");
    const chip = node("span", "matrix-status", humanize(status));
    chip.dataset.tone = status;
    return chip;
  }

  function researchTable(captionCopy, columns, rows) {
    const table = node("table", "research-table");
    table.append(node("caption", "", captionCopy));
    const head = node("thead");
    const headRow = node("tr");
    columns.forEach(([label]) => {
      const header = node("th", "", label);
      header.scope = "col";
      headRow.append(header);
    });
    head.append(headRow);
    const body = node("tbody");
    rows.forEach((row) => {
      const tableRow = node("tr");
      columns.forEach(([, field, formatter]) => {
        const cell = node("td");
        cell.append(formatter ? formatter(row[field], row) : node("span", "", text(row[field], "Not declared")));
        tableRow.append(cell);
      });
      body.append(tableRow);
    });
    table.append(head, body);
    return table;
  }

  function renderSourceAnalysis(intelligence) {
    const analysis = record(intelligence.source_analysis);
    const totals = record(analysis.totals);
    const concentration = record(analysis.concentration);
    const independence = record(analysis.independence);
    const claimSupport = record(analysis.claim_support);
    const verdict = text(analysis.coverage_verdict || analysis.verdict, "unassessed");
    set("#source-analysis-summary", analysis.summary, "No deterministic source-portfolio analysis was retained.");
    set("#source-analysis-verdict", `Coverage: ${humanize(verdict)}`);
    const verdictNode = q("#source-analysis-verdict");
    if (verdictNode) verdictNode.dataset.tone = verdict;

    const hasTopPublisherShare = concentration.top_publisher_share !== null
      && concentration.top_publisher_share !== undefined
      && Number.isFinite(Number(concentration.top_publisher_share));
    const topPublisherShare = Number(concentration.top_publisher_share);
    renderDefinitionList("#source-analysis-totals", [
      ["Retained document records", totals.retained_document_record_count, `${text(totals.canonical_document_count, "0")} canonical · ${text(totals.attributable_document_count, "0")} attributable · ${text(totals.unattributable_document_count, "0")} unattributable`],
      ["Document access", `${text(totals.accessible_document_count, "0")} accessible`, `${text(totals.blocked_document_count, "0")} blocked · ${text(totals.access_unknown_document_count, "0")} unknown`],
      ["Linked source items", totals.linked_source_item_count, `${text(totals.linked_accessible_count, "0")} accessible · ${text(totals.linked_blocked_count, "0")} blocked · ${text(totals.linked_access_unknown_count, "0")} unknown`],
      ["Opened + attributable links", totals.opened_attributable_link_count, "Requires canonical URL, allowed access, and a qualifying status receipt"],
      ["Linked status ledger", `${text(totals.primary_confirmed_link_count, "0")} primary · ${text(totals.multi_source_confirmed_link_count, "0")} multi-source`, `${text(totals.single_source_reported_link_count, "0")} single-source · ${text(totals.discovery_only_link_count, "0")} discovery · ${text(totals.unverified_link_count, "0")} unverified`],
      ["Unique traceable sources", totals.unique_traceable_source_count, "Deduplicated only by exact content hash or canonical URL"],
      ["Metadata conflicts", totals.source_metadata_conflict_count, "Conflicting values remain explicit and are never selected silently"],
      ["Declared publishers", totals.declared_publisher_count, `${text(totals.undeclared_publisher_record_count, "0")} distinct records undeclared; not an independence measure`],
      ["Origin hosts", totals.origin_host_count, `${text(totals.undeclared_origin_host_record_count, "0")} distinct records without a canonical host`],
      ["Retrieval providers", totals.retrieval_provider_count, `${text(totals.undeclared_retrieval_provider_record_count, "0")} observations undeclared; counted across observations and never substituted from publisher`],
      ["Top publisher share", hasTopPublisherShare ? percentage(topPublisherShare) : "Not assessable", `${text(concentration.top_publisher)} · ${text(concentration.publisher_unattributed_record_count, "0")} publisher-unattributed records excluded`],
      ["Claims with multiple publishers", `${text(claimSupport.multiple_publisher_claim_count, "0")} / ${text(claimSupport.claim_count, "0")}`, "Publisher diversity proxy only"],
      ["Unlinked claims", claimSupport.unlinked_claim_count, "Claims without document or metric lineage"],
      ["Independence contract", humanize(independence.status), `Requires ${humanize(independence.required_receipt)}`]
    ]);
    set(
      "#source-independence-note",
      claimSupport.independence_note,
      "Editorial independence is counted only from explicit ownership or editorial-control receipts."
    );

    const rows = list(analysis.coverage_rows).map((value) => {
      const row = record(value);
      const hasPlannedMinimum = row.planned_minimum !== null
        && row.planned_minimum !== undefined
        && Number.isFinite(Number(row.planned_minimum));
      const required = hasPlannedMinimum
        ? `${text(row.unique_accessible_source_count, "0")} / ${text(row.planned_minimum, "0")}`
        : `${text(row.unique_accessible_source_count, "0")} / not planned`;
      return {
        area: humanize(row.area),
        held_required: required,
        publisher_diversity: text(row.publisher_diversity_count, "0"),
        origin_hosts: text(row.origin_host_count, "0"),
        latest_usable: row.latest_usable_at ? date(row.latest_usable_at) : "Not declared",
        verdict: text(row.verdict, row.reported_status || "unassessed")
      };
    });
    const matrix = rows.length
      ? researchTable(
          "Unique accessible sources held against the declared research plan",
          [
            ["Research area", "area"],
            ["Held / required", "held_required"],
            ["Publishers", "publisher_diversity"],
            ["Origin hosts", "origin_hosts"],
            ["Latest usable", "latest_usable"],
            ["Verdict", "verdict", (value) => statusChip(value)]
          ],
          rows
        )
      : node("p", "empty-row", "No coverage plan or coverage receipt was retained; coverage remains unassessed.");
    replace("#source-coverage-matrix", [matrix]);

    const gaps = list(analysis.gaps).map((value) => {
      const gap = record(value);
      const item = node("li", "source-analysis-gap");
      item.dataset.severity = text(gap.severity, "information");
      item.append(
        node("p", "", text(gap.finding, "Evidence gap declared without detail.")),
        node("small", "", `${humanize(gap.area, "Cross-cutting")} · Next: ${text(gap.next_source_class, "Additional attributable evidence")}`)
      );
      return item;
    });
    replace(
      "#source-analysis-gap-list",
      gaps.length ? gaps : [node("li", "empty-row", "No source-portfolio gap was declared by the completed projection.")]
    );
  }

  function renderEvidenceMetrics(intelligence) {
    const rows = list(intelligence.evidence_metrics).map((metric) => {
      const item = record(metric);
      const unit = text(item.unit, "");
      const value = scalar(item.value);
      return {
        metric: humanize(item.label || item.name || item.metric),
        value: unit ? `${value} ${unit}` : value,
        period: text(item.period || item.fiscal_period || item.source_date),
        basis: text(item.basis || item.reporting_basis || item.trend || item.context),
        source: `${text(item.evidence_id)} · ${humanize(item.category)}`
      };
    });
    const content = rows.length
      ? researchTable(
          "Structured evidence metrics",
          [["Metric", "metric"], ["Value", "value"], ["Period", "period"], ["Basis / trend", "basis"], ["Evidence", "source"]],
          rows
        )
      : node("p", "empty-row", "No structured metrics were declared. Raw evidence remains available in the source ledger.");
    replace("#evidence-metrics", [content]);
  }

  function renderNewsIntelligence(view, intelligence) {
    const lookup = evidenceLookup(view);
    const groups = new Map();
    list(intelligence.news).forEach((article) => {
      const quality = declaredSourceQuality(article, lookup);
      if (!groups.has(quality)) groups.set(quality, []);
      groups.get(quality).push(article);
    });

    const ordered = Array.from(groups.entries()).sort(([left], [right]) => {
      const leftRank = SOURCE_QUALITY_ORDER.includes(left)
        ? SOURCE_QUALITY_ORDER.indexOf(left)
        : SOURCE_QUALITY_ORDER.length;
      const rightRank = SOURCE_QUALITY_ORDER.includes(right)
        ? SOURCE_QUALITY_ORDER.indexOf(right)
        : SOURCE_QUALITY_ORDER.length;
      return leftRank - rightRank || left.localeCompare(right);
    });

    const sections = ordered.map(([quality, articles]) => {
      const section = node("section", "news-quality-group");
      const heading = node("header");
      heading.append(node("h4", "", humanize(quality)), node("span", "count-receipt", `${articles.length} retained`));
      section.append(heading);
      const records = node("div", "news-records");
      articles.forEach((article) => {
        const item = record(article);
        const recordNode = node("article", "news-record");
        const receipt = node("p", "news-receipt");
        receipt.append(
          node("span", "", text(item.publisher, "Publisher not declared")),
          node("span", "", date(item.published_at || item.date)),
          node("span", "", humanize(item.verification_status, "Verification not declared")),
          node("span", "", humanize(item.claim_type, "Claim type not declared"))
        );
        recordNode.append(
          receipt,
          node("h5", "", text(item.title || item.headline)),
          node("p", "news-summary", text(item.summary, "No supported summary declared."))
        );
        if (item.why_it_matters) {
          const why = node("p", "why-it-matters");
          why.append(node("b", "", "Why it matters"), node("span", "", text(item.why_it_matters)));
          recordNode.append(why);
        }
        const footer = node("footer");
        footer.append(
          node("span", "", `${text(item.evidence_id)} · ${humanize(item.stance || item.sentiment, "Stance not declared")}`),
          publicSourceLink(item.url || item.source_url)
        );
        recordNode.append(footer);
        records.append(recordNode);
      });
      section.append(records);
      return section;
    });
    replace("#news-intelligence", sections.length ? sections : [node("p", "empty-row", "No structured article intelligence was declared.")]);
  }

  function ledgerPrimary(entry, keys) {
    for (const key of keys) {
      const value = text(entry[key], "");
      if (value) return value;
    }
    return "Structured item without a declared summary";
  }

  function renderStructuredLedger(selector, values, primaryKeys, emptyCopy) {
    const records = list(values).map((value) => {
      const entry = record(value);
      const item = node("article", "structured-record");
      item.append(node("p", "", ledgerPrimary(entry, primaryKeys)));
      const metadata = node("dl");
      Object.entries(entry)
        .filter(([key, fieldValue]) => !primaryKeys.includes(key) && !["evidence_id", "category"].includes(key) && text(fieldValue, ""))
        .forEach(([key, fieldValue]) => {
          const row = node("div");
          row.append(node("dt", "", humanize(key)), node("dd", "", scalar(fieldValue)));
          metadata.append(row);
        });
      if (metadata.childElementCount) item.append(metadata);
      item.append(node("small", "", `${text(entry.evidence_id, entry.source || "Decision record")} · ${humanize(entry.category, "Cross-stage")}`));
      return item;
    });
    replace(selector, records.length ? records : [node("p", "empty-row", emptyCopy)]);
  }

  function dossierRecords(dossier, keys) {
    return list(keys).flatMap((key) => {
      const value = record(dossier)[key];
      if (value === null || value === undefined || value === "") return [];
      return Array.isArray(value) ? value : [value];
    });
  }

  function researchValue(value, field = "") {
    if (Array.isArray(value)) {
      const items = node("ul", "research-value-list");
      value.forEach((entry) => {
        const item = node("li");
        item.append(researchValue(entry, field));
        items.append(item);
      });
      return items;
    }
    if (value && typeof value === "object") {
      const definitions = node("dl", "research-value-map");
      Object.entries(value).forEach(([key, entry]) => {
        const row = node("div");
        row.append(node("dt", "", humanize(key)));
        const description = node("dd");
        description.append(researchValue(entry, key));
        row.append(description);
        definitions.append(row);
      });
      return definitions;
    }
    if (/(?:^|_)(?:url|uri)$/.test(field) && text(value, "")) return publicSourceLink(value);
    return node("span", "", text(value, "Not declared"));
  }

  function summaryValue(key, value) {
    if (/(?:^|_)(?:url|uri)$/.test(key) && text(value, "")) return publicSourceLink(value);
    if (/(?:^|_)(?:at|timestamp)$/.test(key) && text(value, "")) return node("span", "", timestamp(value));
    if (["confidence", "probability", "calibration_score"].includes(key)) return node("span", "", percentage(value));
    return node("span", "", scalar(value));
  }

  function rawDisclosure(value) {
    const disclosure = node("details", "research-raw");
    disclosure.append(node("summary", "", "Full structured record"), researchValue(value));
    return disclosure;
  }

  function metricSummaryLabel(key, entry) {
    if (key === "as_of_at") return "Information vintage";
    if (key === "period_start") return "Economic period start";
    if (key === "period_end") {
      const periodEnd = Date.parse(text(entry.period_end, ""));
      const asOf = Date.parse(text(entry.as_of_at, ""));
      return Number.isFinite(periodEnd) && Number.isFinite(asOf) && periodEnd > asOf
        ? "Forecast / model period"
        : "Reported / measurement period";
    }
    if (key === "source_document_ids") return "Source documents";
    if (key === "calculation_id") return "Calculation lineage";
    return humanize(key);
  }

  function typedResearchRecord(value, ordinal, config = {}) {
    const entry = record(value);
    const summaryEntry = config.summaryProjection ? record(config.summaryProjection(entry)) : entry;
    const article = node("article", `research-record${config.primary ? " research-record--primary" : ""}`);
    const titleKeys = config.titleKeys || ["title", "name", "statement", "summary", "id"];
    const title = titleKeys.map((key) => summaryEntry[key]).find((candidate) => text(candidate, ""));
    const heading = node("header", "research-record-heading");
    heading.append(node("h4", "", text(title, `${config.label || "Record"} ${ordinal + 1}`)));
    if (summaryEntry.status) {
      const status = node("span", "matrix-status", humanize(summaryEntry.status));
      status.dataset.tone = String(summaryEntry.status);
      heading.append(status);
    }
    article.append(heading);

    const facts = node("dl", "research-summary-fields");
    (config.summaryKeys || []).forEach((key) => {
      const valueForKey = summaryEntry[key];
      if (valueForKey === null || valueForKey === undefined || valueForKey === "" || (Array.isArray(valueForKey) && !valueForKey.length)) return;
      const row = node("div");
      const label = config.summaryLabel ? config.summaryLabel(key, summaryEntry) : humanize(key);
      row.append(node("dt", "", label));
      const description = node("dd");
      description.append(summaryValue(key, valueForKey));
      row.append(description);
      facts.append(row);
    });
    if (facts.childElementCount) article.append(facts);
    article.append(rawDisclosure(value));
    return article;
  }

  function renderTypedRecords(selector, dossier, keys, config, emptyCopy) {
    const records = dossierRecords(dossier, keys).map((value, ordinal) => typedResearchRecord(value, ordinal, config));
    replace(selector, records.length ? records : [node("p", "empty-row", emptyCopy)]);
  }

  function renderResearchDelta(dossier) {
    renderTypedRecords("#research-change", dossier, ["research_delta", "what_changed"], {
      label: "Research delta",
      titleKeys: ["summary"],
      summaryKeys: ["summary", "added_document_ids", "changed_claim_ids", "changed_valuation_ids", "previous_dossier_sha256"],
      primary: true
    }, "No research delta was included in the completed dossier.");
  }

  function renderCoverageStatusMatrix(dossier) {
    renderTypedRecords("#research-coverage", dossier, ["coverage"], {
      label: "Coverage area",
      titleKeys: ["area"],
      summaryKeys: ["status", "source_document_ids", "limitation"]
    }, "No coverage receipt was included in the completed dossier.");
  }

  function renderSources(dossier) {
    renderTypedRecords("#source-explorer", dossier, ["documents", "source_documents", "sources"], {
      label: "Source",
      titleKeys: ["title", "name", "id"],
      summaryKeys: ["document_kind", "publisher", "published_at", "available_at", "retrieved_at", "canonical_uri", "verification_status", "access", "redistributable", "terms_uri"],
      summaryProjection: (entry) => {
        const locator = record(entry.locator);
        const temporal = record(entry.temporal);
        const entitlement = record(entry.entitlement);
        return {
          ...entry,
          document_kind: entry.kind || entry.source_kind || entry.document_kind,
          canonical_uri: locator.canonical_uri || entry.canonical_uri || entry.url || entry.uri,
          published_at: temporal.published_at || entry.published_at,
          available_at: temporal.available_at || entry.available_at,
          retrieved_at: temporal.retrieved_at || entry.retrieved_at,
          access: entitlement.access || entry.entitlement,
          redistributable: entitlement.redistributable,
          terms_uri: entitlement.terms_uri
        };
      }
    }, "No source-document records were included in the completed dossier.");
  }

  function renderArgumentsAndClaims(dossier) {
    renderTypedRecords("#claim-graph", dossier, ["claims", "arguments", "thesis_graph"], {
      label: "Claim or argument",
      titleKeys: ["statement", "role", "argument_id", "id"],
      summaryKeys: ["kind", "stance", "confidence", "debate", "round", "turn", "claim_ids", "rebuttal_of", "concessions", "unresolved"]
    }, "No claim, argument, or thesis-graph records were included in the completed dossier.");
  }

  function renderFilingChanges(dossier) {
    renderTypedRecords("#filings-ledger", dossier, ["filings", "filing_changes"], {
      label: "Filing record",
      titleKeys: ["summary", "form", "id"],
      summaryKeys: ["form", "filed_at", "period_end", "change_kind", "summary", "metric_ids", "claim_ids", "amendment"]
    }, "No filing or filing-change records were included in the completed dossier.");
  }

  function renderTranscriptsAndGuidance(dossier) {
    renderTypedRecords("#earnings-ledger", dossier, ["transcripts", "guidance", "earnings"], {
      label: "Management record",
      titleKeys: ["speaker_summary", "metric", "title", "id"],
      summaryKeys: ["event_at", "period", "status", "low", "high", "unit", "speaker_summary", "themes", "guidance_claim_ids"]
    }, "No earnings, guidance, or transcript records were included in the completed dossier.");
  }

  function renderFactors(dossier) {
    renderTypedRecords("#factor-history", dossier, ["factor_snapshots", "factors"], {
      label: "Factor",
      titleKeys: ["factor", "name", "id"],
      summaryKeys: ["direction", "magnitude", "value", "unit", "delta", "as_of_at", "methodology_version"]
    }, "No factor-history records were included in the completed dossier.");
  }

  function renderPeers(dossier) {
    renderTypedRecords("#peer-matrix", dossier, ["peer_set", "peers"], {
      label: "Peer",
      titleKeys: ["name", "peer_instrument_id", "id"],
      summaryKeys: ["peer_instrument_id", "rationale", "methodology", "metric_ids"]
    }, "No peer-set records were included in the completed dossier.");
  }

  function renderValuationAndCalculations(dossier) {
    renderTypedRecords("#valuation-cases", dossier, ["valuations", "valuation_cases", "calculations", "metrics"], {
      label: "Valuation record",
      titleKeys: ["name", "label", "formula", "id"],
      summaryKeys: ["methodology", "formula", "operation", "result", "fair_value", "value", "unit", "currency", "horizon", "basis", "as_of_at", "period_start", "period_end", "source_document_ids", "calculation_id", "deterministic"],
      summaryLabel: metricSummaryLabel
    }, "No deterministic valuation or calculation records were included in the completed dossier.");
  }

  function renderEventsAndEntities(dossier) {
    renderTypedRecords("#event-timeline", dossier, ["events", "entities"], {
      label: "Event or entity",
      titleKeys: ["title", "name", "id"],
      summaryKeys: ["occurred_at", "status", "kind", "entity_ids", "ripple_event_ids", "claim_ids"]
    }, "No event, ripple, or entity records were included in the completed dossier.");
  }

  function renderRisks(dossier) {
    renderTypedRecords("#stress-scenarios", dossier, ["risks", "stress_scenarios"], {
      label: "Risk",
      titleKeys: ["name", "scenario", "title", "id"],
      summaryKeys: ["probability", "impact", "thesis", "trigger", "trigger_metric_ids", "claim_ids"]
    }, "No structured risk or stress records were included in the completed dossier.");
  }

  function renderMonitoring(dossier) {
    renderTypedRecords("#invalidation-rules", dossier, ["monitoring_rules", "monitoring"], {
      label: "Monitoring rule",
      titleKeys: ["description", "title", "id"],
      summaryKeys: ["cadence", "trigger", "consequence", "related_ids"]
    }, "No monitoring or invalidation rules were included in the completed dossier.");
  }

  function renderPriorOutcomes(dossier) {
    renderTypedRecords("#prior-outcomes", dossier, ["prior_outcomes", "calibration"], {
      label: "Prior outcome",
      titleKeys: ["result", "title", "id"],
      summaryKeys: ["result", "forecast_at", "evaluated_at", "calibration_score", "notes"]
    }, "No prior-outcome or calibration records were included in the completed dossier.");
  }

  function renderPortfolioContextAndImpact(dossier) {
    renderTypedRecords("#portfolio-context-impact", dossier, ["portfolio_context", "portfolio_impact", "impact"], {
      label: "Portfolio analysis",
      titleKeys: ["thesis", "objective", "title"],
      summaryKeys: ["objective", "horizon", "risk_tolerance", "thesis", "issuer_exposure_percent", "issuer_exposure_delta_percent", "sector_exposure_percent", "sector_exposure_delta_percent", "diversification_effect", "risk_contribution", "non_executable"]
    }, "No portfolio context or impact analysis was included in the completed dossier.");
  }

  function renderEvaluationStatusMatrix(dossier) {
    const evaluation = record(dossier["evaluation"] || dossier["evaluation_receipts"] || dossier.evaluations);
    if (!Object.keys(evaluation).length) {
      replace("#evaluation-receipts", [node("p", "empty-row", "No evaluation receipts were included in the completed dossier.")]);
      return;
    }
    const records = [typedResearchRecord(evaluation, 0, {
      label: "Evaluation",
      titleKeys: ["evaluator"],
      summaryKeys: ["evaluator", "evaluator_provenance", "rubric_version", "limitations"],
      primary: true
    })];
    list(evaluation.checks).forEach((check, ordinal) => records.push(typedResearchRecord(check, ordinal, {
      label: "Evaluation check",
      titleKeys: ["rubric", "id"],
      summaryKeys: ["status", "rubric", "evaluator", "evaluated_at", "notes"]
    })));
    replace("#evaluation-receipts", records);
  }

  function renderCompletedResearch(view) {
    const dossier = record(view.research_dossier);
    const section = q("#complete-research");
    const navigation = q("#complete-research-nav");
    if (!Object.keys(dossier).length || dossier.status !== "completed") {
      if (section) section.hidden = true;
      if (navigation) navigation.hidden = true;
      return;
    }
    if (section) section.hidden = false;
    if (navigation) navigation.hidden = false;

    renderResearchDelta(dossier);
    renderCoverageStatusMatrix(dossier);
    renderSources(dossier);
    renderArgumentsAndClaims(dossier);
    renderFilingChanges(dossier);
    renderTranscriptsAndGuidance(dossier);
    renderFactors(dossier);
    renderPeers(dossier);
    renderValuationAndCalculations(dossier);
    renderEventsAndEntities(dossier);
    renderRisks(dossier);
    renderMonitoring(dossier);
    renderPriorOutcomes(dossier);
    renderPortfolioContextAndImpact(dossier);
    renderEvaluationStatusMatrix(dossier);
  }

  function renderResearchLab(view) {
    const lab = record(view.research_lab);
    const analytics = record(lab.analytics);
    const runCard = record(lab.run_card);
    const quality = record(lab.quality);
    const qualityHistory = record(lab.quality_history);
    const hypotheses = list(lab.hypotheses);
    const iterations = list(lab.iterations);
    const forecasts = list(lab.forecasts);
    const section = q("#research-lab");
    const navigation = q("#research-lab-nav");
    const available = [analytics, runCard, quality].some((entry) => Object.keys(entry).length)
      || hypotheses.length || iterations.length || forecasts.length;
    if (!available) {
      if (section) section.hidden = true;
      if (navigation) navigation.hidden = true;
      return;
    }
    if (section) section.hidden = false;
    if (navigation) navigation.hidden = false;

    const analyticsCount = [
      "facts", "statement_snapshots", "ratios", "dcf_valuations", "reverse_dcf_results",
      "comparable_valuations", "consensus", "ownership", "experiments", "catalysts"
    ].reduce((total, key) => total + list(analytics[key]).length, 0);
    renderDefinitionList("#analytics-summary", [
      ["Coverage decision", analytics.coverage_decision, "Declared by the completed analytics bundle"],
      ["Analytical records", analyticsCount, "Facts, models, consensus, positioning, experiments, and events"],
      ["Research cutoff", analytics.cutoff_at, "No source available later may support this publication"],
      ["Limitations", list(analytics.limitations).length, "Explicit analytical limitations"]
    ]);
    renderDefinitionList("#run-summary", [
      ["Research pack", runCard.research_pack_id, "Versioned workflow intent"],
      ["Harness", runCard.harness, "Host that executed the research"],
      ["Execution mode", runCard.execution_mode, "Full, compatible, tools-only, replay, or fixture"],
      ["Stage receipts", list(runCard.stages).length, "Completed, skipped, and blocked work"]
    ]);
    const rules = list(quality.rules);
    renderDefinitionList("#quality-summary", [
      ["Policy", text(record(quality.policy).policy_id, "Not declared"), text(record(quality.policy).policy_version, "")],
      ["Rules", rules.length, "Immutable quality-rule results"],
      ["Failed or unverified", rules.filter((rule) => ["fail", "unverified"].includes(text(record(rule).status))).length, "Requires reader attention"],
      ["Forecasts", forecasts.length, "Typed predictions with independent resolution rules"]
    ]);

    renderTypedRecords("#run-card-ledger", { stages: list(runCard.stages), iterations }, ["stages", "iterations"], {
      label: "Stage or iteration",
      titleKeys: ["stage_id", "iteration_id"],
      summaryKeys: ["status", "started_at", "completed_at", "attempts", "decision", "consumed_units", "budget_units", "limitation"]
    }, "No run-card stages were retained.");
    const hypothesisRecords = hypotheses.map((ledger) => {
      const item = record(ledger);
      return { ...record(item.hypothesis), final_status: item.final_status, transitions: list(item.transitions), run_id: item.run_id };
    });
    renderTypedRecords("#hypothesis-lab", { hypotheses: hypothesisRecords }, ["hypotheses"], {
      label: "Hypothesis",
      titleKeys: ["statement", "hypothesis_id"],
      summaryKeys: ["final_status", "falsification_criteria", "expected_observation", "horizon_at", "evidence_ids"]
    }, "No explicit hypotheses were retained.");
    renderTypedRecords("#fundamental-lab", analytics, ["facts", "statement_snapshots", "restatements"], {
      label: "Fundamental record",
      titleKeys: ["concept", "statement", "snapshot_id", "amended_fact_id", "fact_id"],
      summaryKeys: ["value", "unit", "currency", "scale", "period", "filed_at", "available_at", "source_id", "complete", "limitation"]
    }, "No analytics-v1 fundamental records were retained.");
    renderTypedRecords("#model-lab", analytics, ["ratios", "dcf_valuations", "reverse_dcf_results", "comparable_valuations"], {
      label: "Model result",
      titleKeys: ["valuation_id", "result_id", "observation_id", "model_id"],
      summaryKeys: ["value", "output_unit", "enterprise_value", "equity_value", "fair_value_per_share", "target_price", "implied_terminal_growth_rate", "feasible", "limitation"]
    }, "No deterministic model results were retained.");
    renderTypedRecords("#consensus-lab", analytics, ["analyst_opinions", "estimates", "consensus"], {
      label: "Consensus record",
      titleKeys: ["institution", "metric", "snapshot_id", "opinion_id"],
      summaryKeys: ["normalized_rating", "price_target", "fiscal_period_id", "value", "mean", "median", "low", "high", "contributor_count", "revision_percent", "as_of_at"]
    }, "No attributable analyst or consensus records were retained.");
    renderTypedRecords("#positioning-lab", analytics, ["ownership", "insider_transactions", "short_interest"], {
      label: "Positioning record",
      titleKeys: ["holder_type", "insider_name", "snapshot_id", "transaction_id"],
      summaryKeys: ["as_of_at", "settlement_at", "transaction_at", "shares_held", "ownership_percent", "transaction_type", "shares", "short_percent_float", "days_to_cover"]
    }, "No ownership, insider, or short-interest records were retained.");
    renderTypedRecords("#event-lab", analytics, ["catalysts", "event_clusters"], {
      label: "Catalyst or event cluster",
      titleKeys: ["title", "catalyst_id", "cluster_id"],
      summaryKeys: ["catalyst_type", "expected_at", "window_start_at", "window_end_at", "condition", "materiality", "catalyst_ids", "dependency_ids"]
    }, "No analytics-v1 catalysts were retained.");
    renderTypedRecords("#experiment-lab", analytics, ["datasets", "splits", "factors", "experiment_specs", "experiments"], {
      label: "Experiment record",
      titleKeys: ["experiment_id", "dataset_id", "split_id", "factor_id", "receipt_id"],
      summaryKeys: ["status", "point_in_time", "start_at", "cutoff_at", "target_starts_at", "strategy", "purge_days", "embargo_days", "shuffled", "target", "target_horizon_days", "metrics", "limitation"]
    }, "No point-in-time experiment records were retained.");
    renderTypedRecords("#forecast-lab", { forecasts }, ["forecasts"], {
      label: "Forecast",
      titleKeys: ["target", "forecast_id"],
      summaryKeys: ["forecast_kind", "probability", "point_estimate", "interval_lower", "interval_upper", "direction", "benchmark_id", "forecast_at", "resolve_after", "resolution_rule"]
    }, "No explicit forecasts were retained.");
    renderTypedRecords("#quality-lab", {
      rules,
      receipt: quality,
      scorecards: list(qualityHistory.scorecards),
      outcome_ledgers: list(qualityHistory.outcome_ledgers)
    }, ["rules", "receipt", "scorecards", "outcome_ledgers"], {
      label: "Quality record",
      titleKeys: ["rule_id", "receipt_id", "forecast_id"],
      summaryKeys: ["status", "detail", "issued_at", "forecast_kind", "scored_at", "observation_id", "metrics", "workflow_sha256", "request_sha256", "dossier_sha256", "limitations"]
    }, "No research-quality receipt was retained.");
    renderTypedRecords("#policy-lab", analytics, ["source_licenses"], {
      label: "Source policy",
      titleKeys: ["source_id", "receipt_id"],
      summaryKeys: ["access", "permitted_purpose", "machine_use", "retention_days", "derived_data_rights", "redistribution", "terms_uri", "checked_at", "limitation"]
    }, "No source-policy receipts were retained.");
  }

  function renderIntelligence(view) {
    const intelligence = record(view.intelligence);
    const coverage = record(intelligence.coverage);
    const freshness = record(intelligence.freshness);
    const fixtureMode = list(view.evidence).length > 0 && list(view.evidence).every((item) => record(item.provenance).fixture === true);
    renderDefinitionList("#coverage-grid", [
      ["Evidence records", coverage.evidence_count, "Retained in canonical RunView"],
      ["Analyst reports", coverage.analyst_count, "Independent stage outputs"],
      ["Traceable public URLs", coverage.source_url_count, "Sanitized source and article links"],
      ["Dated sources", coverage.dated_source_count, "Source date explicitly declared"],
      ["Limitations", coverage.limitation_count, "Evidence-level disclosures"],
      ["Quality buckets", Object.entries(record(coverage.source_quality_buckets)).map(([key, value]) => `${humanize(key)} ${value}`).join(" · "), "Declared vocabulary only"],
      ["Unrecognized quality labels", coverage.unrecognized_source_quality_count, "Projected as Unknown; raw evidence is preserved"]
    ]);
    renderCountGroups("#source-mix", [
      ["Evidence categories", record(record(intelligence.source_mix).categories)],
      ["Evidence retrieval providers", record(record(intelligence.source_mix).providers)],
      ["Source types", record(record(intelligence.source_mix).source_types)]
    ]);
    renderDefinitionList("#freshness-grid", [
      ["Research cutoff", date(freshness.cutoff), fixtureMode ? "Synthetic fixture date · not a current market cutoff" : "No later evidence is allowed"],
      ["Oldest source", date(freshness.oldest_source_date), fixtureMode ? "Synthetic fixture source date" : "Declared source date"],
      ["Latest source", date(freshness.latest_source_date), fixtureMode ? "Synthetic fixture source date" : "Declared source date"],
      ["Source-history span", daySpan(freshness.source_history_days), "Publication-date range in retained evidence"],
      ["Latest-source lag", daySpan(freshness.latest_source_lag_days), "Distance from latest retained source to cutoff"],
      ["First retrieval", timestamp(freshness.oldest_retrieved_at), fixtureMode ? "Synthetic fixture timestamp · no retrieval occurred" : "Host retrieval receipt"],
      ["Latest retrieval", timestamp(freshness.latest_retrieved_at), fixtureMode ? "Synthetic fixture timestamp · no retrieval occurred" : "Host retrieval receipt"]
    ]);
    renderSourceAnalysis(intelligence);
    renderEvidenceMetrics(intelligence);
    renderNewsIntelligence(view, intelligence);
    renderStructuredLedger("#catalyst-ledger", intelligence.catalysts, ["catalyst", "title", "detail"], "No structured catalysts were declared.");
    renderStructuredLedger("#risk-register", intelligence.risk_register, ["risk", "title", "detail"], "No structured risks were declared.");
    renderStructuredLedger("#conflict-ledger", intelligence.conflicts, ["conflict", "title", "detail"], "No structured conflicts were declared.");
    renderStructuredLedger("#unknown-ledger", intelligence.unknowns, ["unknown", "title", "detail"], "No structured unknowns were declared.");
    renderStructuredLedger("#monitoring-ledger", intelligence.monitoring_conditions, ["condition", "trigger", "title", "detail"], "No structured monitoring conditions were declared.");
  }

  function renderAnalysts(view) {
    const lookup = evidenceLookup(view);
    const cards = list(view.analyst_reports).map((report) => {
      const card = node("article", "analyst-card");
      const heading = node("header");
      heading.append(node("p", "eyebrow", humanize(report.analyst)), node("span", "confidence", percentage(report.confidence)));
      const thesis = node("h3", "", text(report.thesis));
      const content = richText(report.content, text(report.thesis));
      content.classList.add("analyst-content");
      const sources = node("footer");
      sources.append(node("span", "", "Evidence"), node("p", "", evidenceNames(report.evidence_ids, lookup).join(" · ") || "No evidence references declared"));
      card.append(heading, thesis, content, sources);
      return card;
    });
    replace("#analyst-grid", cards.length ? cards : [node("p", "empty-row", "No analyst reports declared in RunView.")]);
  }

  function debateTurn(turn, lookup) {
    const item = node("li", "debate-turn");
    const rail = node("div", "turn-rail");
    const receipt = turn.snapshot ? "Legacy completed-state history" : `Round ${text(turn.round)} · Turn ${text(turn.turn)}`;
    rail.append(node("span", "", humanize(turn.speaker)), node("small", "", receipt));
    const copy = node("div", "turn-copy");
    copy.append(node("p", "", text(turn.position)));
    const sourceNames = evidenceNames(turn.evidence_ids, lookup);
    if (sourceNames.length) copy.append(node("small", "", `Evidence: ${sourceNames.join(" · ")}`));
    if (turn.responds_to) copy.append(node("small", "", `Responds to: ${text(turn.responds_to)}`));
    item.append(rail, copy);
    return item;
  }

  function renderResearchDebate(view) {
    const research = record(record(view.debates).research);
    const snapshot = record(research.snapshot);
    const lookup = evidenceLookup(view);
    const turns = resolveDebateEntries(research.turns, snapshot, RESEARCH_SNAPSHOT_ROLES).map((turn) => debateTurn(turn, lookup));
    replace("#research-debate-list", turns.length ? turns : [emptyItem("No research debate turns declared in RunView.")]);
    replaceRich("#research-manager", snapshot.judge_decision || record(record(view.decisions).research).rationale);
  }

  function renderTrader(view) {
    const trader = record(record(view.decisions).trader);
    set("#trader-action", humanize(trader.action));
    set(
      "#trader-executable",
      trader.executable || trader.execution_authority !== "none" || trader.submitted
        ? "Invalid execution state"
        : "Non-executable · no authority · not submitted"
    );
    set("#trader-reasoning", trader.reasoning);
    set("#trader-entry-price", trader.entry_price, "Not specified");
    set("#trader-stop-loss", trader.stop_loss, "Not specified");
    set("#trader-position-sizing", trader.position_sizing, "Not specified");
    renderList("#trader-caveats", trader.caveats, "No trader caveats declared in RunView.");
  }

  function renderRisk(view) {
    const riskDebate = record(record(view.debates).risk);
    const riskDecision = record(record(view.decisions).risk);
    const portfolio = record(record(view.decisions).portfolio);
    const lookup = evidenceLookup(view);
    const groups = new Map();
    resolveDebateEntries(riskDebate.turns, riskDebate.snapshot, RISK_SNAPSHOT_ROLES).forEach((turn) => {
      const speaker = text(turn.speaker, "Risk perspective");
      if (!groups.has(speaker)) groups.set(speaker, []);
      groups.get(speaker).push(turn);
    });

    const cards = Array.from(groups.entries()).map(([speaker, turns]) => {
      const card = node("article", "risk-card");
      card.dataset.perspective = speaker.toLowerCase();
      card.append(node("p", "eyebrow", humanize(speaker)));
      const positions = node("div");
      turns.forEach((turn) => {
        const entry = node("section");
        const receipt = turn.snapshot ? "Legacy completed-state history" : `Round ${text(turn.round)} · Turn ${text(turn.turn)}`;
        entry.append(node("small", "", receipt), node("p", "", text(turn.position)));
        const names = evidenceNames(turn.evidence_ids, lookup);
        if (names.length) entry.append(node("small", "", `Evidence: ${names.join(" · ")}`));
        positions.append(entry);
      });
      card.append(positions);
      return card;
    });
    replace("#risk-perspectives", cards.length ? cards : [node("p", "empty-row", "No risk perspectives declared in RunView.")]);
    renderList("#risk-constraints", riskDecision.constraints, "No constraints declared in RunView.");
    renderList("#risk-unresolved", riskDecision.unresolved, "No unresolved risks declared in RunView.");
    replaceRich("#risk-manager-judgment", record(riskDebate.snapshot).judge_decision || portfolio.executive_summary);
  }

  function renderEvidence(view) {
    const records = list(view.evidence).map((item) => {
      const provenance = record(item.provenance);
      const article = node("article", "evidence-record");
      const head = node("header");
      const titleBlock = node("div");
      titleBlock.append(node("p", "eyebrow", humanize(item.category)), node("h3", "", text(item.title)));
      head.append(titleBlock, node("code", "", text(item.id)));
      article.append(head, node("p", "evidence-summary", text(item.summary)));

      const values = Object.entries(record(item.values)).map(([key, value]) => [humanize(key), scalar(value), ""]);
      const valueList = node("dl", "evidence-values");
      values.forEach(([label, value]) => {
        const row = node("div");
        row.append(node("dt", "", label), node("dd", "", value));
        valueList.append(row);
      });
      if (values.length) article.append(valueList);

      const receipt = node("dl", "source-receipt");
      [
        ["Provider", provenance.provider],
        ["Source type", humanize(provenance.source_type)],
        ["Source URI", provenance.source_uri],
        ["Source date", date(provenance.source_date)],
        ["Retrieved", timestamp(provenance.retrieved_at)],
        ["Fixture", provenance.fixture]
      ].forEach(([label, value]) => {
        const row = node("div");
        const description = node("dd");
        description.append(label === "Source URI" ? publicSourceLink(value) : node("span", "", text(value)));
        row.append(node("dt", "", label), description);
        receipt.append(row);
      });
      article.append(receipt);

      const notes = [...list(provenance.notes), ...list(item.limitations)];
      if (notes.length) {
        const noteList = node("ul", "source-notes");
        notes.forEach((note) => noteList.append(node("li", "", text(note))));
        article.append(noteList);
      }
      return article;
    });
    replace("#evidence-provenance", records.length ? records : [node("p", "empty-row", "No evidence records declared in RunView.")]);
  }

  function renderWarnings(view) {
    const overview = record(view.overview);
    const intelligence = record(view.intelligence);
    const conflicts = list(intelligence.conflicts).map((item) => `Conflict: ${ledgerPrimary(record(item), ["conflict", "title", "detail"])}`);
    const unknowns = list(intelligence.unknowns).map((item) => `Unknown: ${ledgerPrimary(record(item), ["unknown", "title", "detail"])}`);
    const warnings = [...list(overview.warnings), ...conflicts, ...unknowns];
    const limitations = list(view.evidence).flatMap((item) => list(item.limitations));
    renderList("#warning-list", warnings, "No run-level warnings, conflicts, or unknowns declared in RunView.");
    set(
      "#degradation-note",
      limitations.length
        ? `${limitations.length} evidence limitations: ${limitations.join(" · ")}`
        : "No evidence-level limitations declared in RunView."
    );
  }

  function badgeEntries(section) {
    return list(record(section).badges).map((badge) => [text(badge.label), badge.value, text(badge.detail, "")]);
  }

  function metadataEntries(metadata) {
    return Object.entries(record(metadata)).map(([key, value]) => [humanize(key), value, ""]);
  }

  function renderTransparency(view) {
    const capability = record(view.capability);
    const persistence = record(view.persistence);
    renderDefinitionList("#capability-grid", [...badgeEntries(capability), ...metadataEntries(capability.metadata)]);
    renderDefinitionList("#persistence-grid", [...badgeEntries(persistence), ...metadataEntries(persistence.metadata)]);
    renderDefinitionList("#execution-grid", metadataEntries(view.execution_config));
  }

  function renderArtifacts(view) {
    const artifacts = list(view.artifacts).map((artifact) => {
      const item = node("li");
      const copy = node("div");
      copy.append(node("b", "", text(artifact.title)), node("small", "", `${text(artifact.kind)} · ${text(artifact.media_type)}`));
      item.append(copy, node("code", "", text(artifact.id)));
      return item;
    });
    replace("#artifacts", artifacts.length ? artifacts : [emptyItem("No report artifacts declared in RunView.")]);
    set("#complete-report-reference", record(view.reports).complete_artifact_id, "No complete-report artifact reference declared.");
  }

  function renderMethodology(view) {
    const events = list(view.events);
    const eventKinds = new Map();
    events.forEach((event) => eventKinds.set(text(event.kind), (eventKinds.get(text(event.kind)) || 0) + 1));
    const stageEvents = new Map();
    events.forEach((event) => {
      if (event.stage_id) stageEvents.set(String(event.stage_id), event);
    });

    const stages = list(record(view.topology).stages).map((stage, index) => {
      const item = node("li");
      const receipt = stageEvents.get(String(stage.id));
      item.append(
        node("span", "", String(index + 1).padStart(2, "0")),
        node("b", "", text(stage.role, humanize(stage.kind))),
        node("small", "", receipt ? `${humanize(receipt.status)} · ${text(receipt.message)}` : "No stage event declared")
      );
      return item;
    });
    replace("#topology-list", stages.length ? stages : [emptyItem("No workflow stages declared in RunView.")]);
    renderDefinitionList("#event-summary", [
      ["Total events", events.length, "Canonical RunView event count"],
      ...Array.from(eventKinds.entries()).map(([kind, count]) => [humanize(kind), count, "Event kind"]),
      ["Research debate turns", list(record(record(view.debates).research).turns).length, "Preserved turns"],
      ["Risk debate turns", list(record(record(view.debates).risk).turns).length, "Preserved turns"]
    ]);
  }

  function isCompletedView(view) {
    return record(view.overview).status === "completed";
  }

  function render(view) {
    if (!isCompletedView(view)) {
      showEmpty("The requested RunView is not completed. Final research remains hidden until completion.");
      return;
    }
    renderHero(view);
    renderExecutive(view);
    renderDecisionTrace(view);
    renderIntelligence(view);
    renderCompletedResearch(view);
    renderResearchLab(view);
    renderAnalysts(view);
    renderResearchDebate(view);
    renderTrader(view);
    renderRisk(view);
    renderEvidence(view);
    renderWarnings(view);
    renderTransparency(view);
    renderArtifacts(view);
    renderMethodology(view);
    set("#schema-version", `Schema ${text(view.schema_version)}`);

    const empty = q("#empty-state");
    const shell = q("#report-shell");
    if (empty) empty.hidden = true;
    if (shell) shell.hidden = false;
    document.body.classList.add("report-loaded");
    set("#interface-status", `Final research dossier loaded for ${text(record(view.overview).symbol)}.`);
  }

  function showEmpty(message) {
    const empty = q("#empty-state");
    const shell = q("#report-shell");
    if (shell) shell.hidden = true;
    if (empty) empty.hidden = false;
    set("#data-source-label", "No report loaded");
    set("#run-status", "Offline");
    set("#empty-copy", message);
    set("#interface-status", message);
  }

  function resolveViewEndpoint(search = "") {
    const runId = new URLSearchParams(search).get("run");
    if (runId === null || runId === "") return "/api/runs/current/view";
    if (!/^[A-Za-z0-9._-]{1,128}$/.test(runId)) return null;
    return `/api/runs/${encodeURIComponent(runId)}/view`;
  }

  function viewerAccessToken(hash = "") {
    const candidate = new URLSearchParams(hash.replace(/^#/, "")).get("access_token");
    return candidate && /^[A-Za-z0-9_-]{32,256}$/.test(candidate) ? candidate : null;
  }

  async function establishViewerSession(accessToken) {
    if (!accessToken) return true;
    const response = await fetch("/api/session", {
      headers: {
        Accept: "application/json",
        "X-TradingAgents-Viewer-Token": accessToken
      },
      cache: "no-store"
    });
    if (!response.ok) return false;
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    return true;
  }

  async function load() {
    if (window.location.protocol === "file:") {
      showEmpty("Offline preview only. Start the loopback report server to load the canonical final RunView.");
      return;
    }
    try {
      const endpoint = resolveViewEndpoint(window.location.search);
      if (!endpoint) {
        showEmpty("The requested run identifier is invalid.");
        return;
      }
      const accessToken = viewerAccessToken(window.location.hash);
      if (!(await establishViewerSession(accessToken))) {
        showEmpty("The local viewer session could not be established.");
        return;
      }
      const headers = { Accept: "application/json" };
      if (accessToken) headers["X-TradingAgents-Viewer-Token"] = accessToken;
      const response = await fetch(endpoint, {
        headers,
        cache: "no-store"
      });
      if (!response.ok) {
        showEmpty(`No completed RunView is available (${response.status}).`);
        return;
      }
      const payload = await response.json();
      const view = record(payload.view).overview ? payload.view : payload;
      if (!payload || payload.ok === false || !view.overview || !isCompletedView(view)) {
        showEmpty("The local report endpoint returned no completed canonical final RunView.");
        return;
      }
      render(view);
    } catch (_error) {
      showEmpty("The local final RunView endpoint is unavailable. No report was loaded.");
    }
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      RESEARCH_SNAPSHOT_ROLES,
      RISK_SNAPSHOT_ROLES,
      dossierRecords,
      establishViewerSession,
      viewerAccessToken,
      isCompletedView,
      render,
      researchValue,
      timestamp,
      resolveDebateEntries,
      snapshotRoleEntries,
      resolveViewEndpoint
    };
  }

  if (typeof window !== "undefined" && typeof document !== "undefined") load();
})();
