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
    return new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    }).format(parsed);
  }

  function percentage(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return "—";
    return `${Math.round(parsed * 100)}%`;
  }

  function scalar(value) {
    if (Array.isArray(value)) return value.map((item) => text(item)).join(", ");
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
      if (!['http:', 'https:'].includes(parsed.protocol)) return node("span", "", text(value));
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
    const research = record(record(view.decisions).research);
    const risk = record(record(view.decisions).risk);
    const portfolio = record(record(view.decisions).portfolio);
    const signal = record(view.signal);
    const companyName = text(overview.company_name || overview.company_of_interest || record(view.request).company_name, "");
    const title = companyName ? `${companyName} research dossier` : `${text(overview.symbol, "Company")} research dossier`;

    set("#data-source-label", `Canonical RunView · ${text(view.run_id)}`);
    set("#run-status", humanize(overview.status));
    set("#asset-class", humanize(overview.asset_type));
    set("#symbol", overview.symbol);
    set("#report-title", title);
    set("#decision-summary", portfolio.summary);
    set("#analysis-date", date(overview.as_of_date));
    set("#run-id", view.run_id);
    set("#completed-at", timestamp(overview.completed_at));
    set("#research-confidence", percentage(research.confidence));
    set("#decision-action", humanize(portfolio.action));
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
    const outputs = record(view.outputs);

    set("#portfolio-decision", portfolio.summary);
    set("#portfolio-output", outputs.portfolio_manager_decision);
    set("#portfolio-disclaimer", portfolio.disclaimer);
    set("#research-decision", humanize(research.decision));
    set("#research-rationale", research.rationale);
    set("#supporting-turns", list(research.supporting_turns).join(", "), "None declared");
    set("#final-trade-decision", outputs.final_trade_decision);
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
    set("#research-manager", snapshot.judge_decision || record(record(view.decisions).research).rationale);
  }

  function renderTrader(view) {
    const trader = record(record(view.decisions).trader);
    const outputs = record(view.outputs);
    set("#trader-stance", humanize(trader.stance));
    set("#trader-executable", trader.executable ? "Executable" : "Non-executable analytical output");
    const plan = q("#trader-plan");
    if (plan) plan.replaceChildren(...richText(trader.plan).childNodes);
    set("#investment-plan", outputs.investment_plan || outputs.trader_investment_plan);
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
    set("#risk-manager-judgment", record(riskDebate.snapshot).judge_decision || portfolio.summary);
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
    const warnings = list(overview.warnings);
    const limitations = list(view.evidence).flatMap((item) => list(item.limitations));
    renderList("#warning-list", warnings, "No run-level warnings declared in RunView.");
    set("#degradation-note", limitations.length ? `Evidence limitations: ${limitations.join(" · ")}` : "No evidence-level limitations declared in RunView.");
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

  function render(view) {
    renderHero(view);
    renderExecutive(view);
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
      const response = await fetch(endpoint, {
        headers: { Accept: "application/json" },
        cache: "no-store"
      });
      if (!response.ok) {
        showEmpty(`No completed RunView is available (${response.status}).`);
        return;
      }
      const payload = await response.json();
      const view = record(payload.view).overview ? payload.view : payload;
      if (!payload || payload.ok === false || !view.overview) {
        showEmpty("The local report endpoint returned no canonical final RunView.");
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
      resolveDebateEntries,
      snapshotRoleEntries,
      resolveViewEndpoint
    };
  }

  if (typeof window !== "undefined" && typeof document !== "undefined") load();
})();
