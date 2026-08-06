/* Completed company-analytics projection. No research logic belongs here. */
(() => {
  "use strict";

  const q = (selector) => document.querySelector(selector);
  const list = (value) => (Array.isArray(value) ? value : []);
  const record = (value) => (value && typeof value === "object" && !Array.isArray(value) ? value : {});

  function text(value, fallback = "—") {
    if (value === null || value === undefined || value === "") return fallback;
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (typeof value === "string" || typeof value === "number") return String(value);
    return fallback;
  }

  function firstDeclared(...values) {
    return values.find((value) => value !== null && value !== undefined && value !== "");
  }

  const LABELS = {
    analyst_opinions: "Attributable research opinions",
    debate: "Reasoning track",
    role: "Perspective",
    executor_runtime: "Runtime",
    execution_mode: "Run mode",
    non_executable: "Non-executable",
    source_document_ids: "Evidence documents",
    evidence_document_ids: "Evidence documents",
    counterevidence_document_ids: "Counterevidence documents",
    claim_ids: "Claims",
    metric_ids: "Metrics",
    calculation_ids: "Calculations"
  };

  function humanize(value, fallback = "—") {
    const source = text(value, fallback);
    if (source === fallback) return fallback;
    return source.replace(/[._-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function labelFor(key) {
    return LABELS[key] || humanize(key);
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
    if (!Number.isFinite(parsed)) return text(value);
    return `${Math.round(parsed * 100)}%`;
  }

  function node(tag, className = "", content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined && content !== null) element.textContent = String(content);
    return element;
  }

  function set(selector, value, fallback = "—") {
    const element = q(selector);
    if (element) element.textContent = text(value, fallback);
  }

  function replace(selector, children) {
    const element = q(selector);
    if (element) element.replaceChildren(...children);
  }

  function isSafePublicHost(hostname) {
    const host = hostname.toLowerCase();
    if (!host || host === "localhost" || host.endsWith(".local") || host.endsWith(".invalid") || host.endsWith(".test")) {
      return false;
    }
    if (/^(127\.|10\.|0\.|169\.254\.|192\.168\.)/.test(host)) return false;
    const match = host.match(/^172\.(\d{1,3})\./);
    return !match || Number(match[1]) < 16 || Number(match[1]) > 31;
  }

  function publicSourceLink(value) {
    const uri = text(value, "");
    try {
      const parsed = new URL(uri);
      if (!["http:", "https:"].includes(parsed.protocol)) return node("span", "", text(value));
      if (parsed.username || parsed.password || !isSafePublicHost(parsed.hostname)) {
        return node("span", "source-withheld", "Source reference retained · link withheld");
      }
      const link = node("a", "source-link", parsed.hostname);
      link.href = parsed.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      return link;
    } catch (_error) {
      return node("span", "", text(value));
    }
  }

  function researchValue(value, key = "") {
    if (Array.isArray(value)) {
      const values = node("ul", "value-list");
      value.forEach((item) => {
        const row = node("li");
        row.append(researchValue(item));
        values.append(row);
      });
      if (!value.length) values.append(node("li", "empty-inline", "None declared"));
      return values;
    }
    if (value && typeof value === "object") {
      const details = node("dl", "nested-record");
      Object.entries(value).forEach(([nestedKey, nestedValue]) => {
        const row = node("div");
        row.append(node("dt", "", labelFor(nestedKey)));
        const description = node("dd");
        description.append(researchValue(nestedValue, nestedKey));
        row.append(description);
        details.append(row);
      });
      return details;
    }
    if (/(^|_)(uri|url)$/.test(key)) return publicSourceLink(value);
    return node("span", "", text(value, "Not declared"));
  }

  function disclosureValue(value, key = "") {
    const isStructured = Array.isArray(value) || (value && typeof value === "object");
    const shortScalarList = Array.isArray(value) && value.length <= 4 && value.every((item) => {
      return item === null || ["string", "number", "boolean"].includes(typeof item);
    });
    if (!isStructured || shortScalarList) return researchValue(value, key);

    const count = Array.isArray(value) ? value.length : Object.keys(value).length;
    const noun = Array.isArray(value) ? (count === 1 ? "record" : "records") : (count === 1 ? "field" : "fields");
    const disclosure = node("details", "structured-disclosure");
    disclosure.append(node("summary", "", `${count} ${noun} · Show structured data`));
    disclosure.append(researchValue(value, key));
    return disclosure;
  }

  function empty(copy) {
    return node("p", "empty-row", copy);
  }

  function titleFor(item, ordinal) {
    return firstDeclared(
      item.title,
      item.name,
      item.label,
      item.statement,
      item.stage_id,
      item.forecast_id,
      item.hypothesis_id,
      item.id,
      `Record ${ordinal + 1}`
    );
  }

  const HEADING_KEYS = new Set(["title", "name", "label", "statement"]);

  function recordCard(value, ordinal, className = "record-card") {
    const item = record(value);
    if (!Object.keys(item).length) return node("article", className, text(value));
    const card = node("article", className);
    const header = node("header");
    header.append(node("span", "record-index", String(ordinal + 1).padStart(2, "0")));
    header.append(node("h4", "", titleFor(item, ordinal)));
    const status = firstDeclared(item.status, item.stance, item.kind, item.impact, item.final_status);
    if (status !== undefined) header.append(node("span", "record-status", humanize(status)));
    card.append(header);
    const details = node("dl", "record-details");
    Object.entries(item).forEach(([key, nestedValue]) => {
      if (HEADING_KEYS.has(key) || (key === "id" && item.title)) return;
      const row = node("div");
      row.append(node("dt", "", labelFor(key)));
      const description = node("dd");
      description.append(disclosureValue(nestedValue, key));
      row.append(description);
      details.append(row);
    });
    card.append(details);
    return card;
  }

  function recordsFrom(value) {
    if (Array.isArray(value)) return value;
    if (!value || typeof value !== "object") return value === null || value === undefined ? [] : [value];
    return Object.entries(value).map(([label, nestedValue]) => ({ label, value: nestedValue }));
  }

  function renderRecords(selector, value, emptyCopy, className = "record-card") {
    const values = recordsFrom(value);
    replace(selector, values.length ? values.map((item, index) => recordCard(item, index, className)) : [empty(emptyCopy)]);
  }

  function renderDocuments(documents) {
    const cards = documents.map((value, index) => {
      const item = record(value);
      const card = node("article", "document-card");
      const heading = node("header");
      heading.append(node("span", "document-kind", humanize(item.kind, "Source")));
      heading.append(node("h4", "", text(item.title, text(item.id, `Document ${index + 1}`))));
      card.append(heading);
      card.append(node("p", "document-publisher", text(item.publisher, "Publisher not declared")));
      const locator = record(item.locator);
      if (locator.canonical_uri) {
        const source = node("p", "document-link");
        source.append(publicSourceLink(locator.canonical_uri));
        card.append(source);
      }
      const metadata = node("dl", "document-meta");
      [
        ["Access", record(item.entitlement).access],
        ["Published", record(item.temporal).published_at],
        ["Retrieved", record(item.temporal).retrieved_at],
        ["Digest", locator.content_sha256]
      ].forEach(([label, value]) => {
        const row = node("div");
        row.append(node("dt", "", label), node("dd", "", /at$/.test(label.toLowerCase()) ? timestamp(value) : text(value)));
        metadata.append(row);
      });
      card.append(metadata);
      if (item.extract) card.append(node("p", "document-extract", item.extract));
      return card;
    });
    replace("#documents", cards.length ? cards : [empty("No evidence documents were retained in this result.")]);
    set("#document-count", documents.length);
  }

  function renderClaims(claims) {
    const cards = claims.map((value, index) => {
      const item = record(value);
      const card = recordCard(item, index, "claim-card");
      if (item.confidence !== undefined) {
        const confidence = node("div", "confidence-line");
        confidence.append(node("span", "", "Declared confidence"), node("strong", "", percentage(item.confidence)));
        card.append(confidence);
      }
      return card;
    });
    replace("#claims", cards.length ? cards : [empty("No claims were retained in this result.")]);
    set("#claim-count", claims.length);

    const challenged = claims
      .filter((claim) => list(record(claim).counterevidence_document_ids).length || list(record(claim).counterclaim_ids).length)
      .map((claim) => ({
        claim: firstDeclared(record(claim).statement, record(claim).id),
        counterevidence_document_ids: list(record(claim).counterevidence_document_ids),
        counterclaim_ids: list(record(claim).counterclaim_ids)
      }));
    renderRecords("#counterevidence", challenged, "No counterevidence references were declared.", "challenge-card");
  }

  function renderMetrics(metrics) {
    const cards = metrics.map((value) => {
      const item = record(value);
      const card = node("article", "metric-card");
      card.append(node("p", "metric-label", text(item.label, text(item.id, "Metric"))));
      const measure = node("p", "metric-value");
      measure.append(node("strong", "", text(item.value)), node("span", "", text(item.unit, "")));
      card.append(measure);
      card.append(node("p", "metric-basis", humanize(item.basis, "Basis not declared")));
      return card;
    });
    replace("#metrics", cards.length ? cards : [empty("No dossier metrics were retained.")]);
  }

  function renderLineage(sourceLineage) {
    const bindings = list(sourceLineage.bindings);
    const cards = bindings.map((value, index) => {
      const item = record(value);
      const card = node("article", "lineage-card");
      card.append(node("span", "lineage-number", String(index + 1).padStart(2, "0")));
      card.append(node("h4", "", text(item.dossier_document_id, text(item.binding_id, "Binding"))));
      const path = node("div", "lineage-path");
      [item.source_observation_id, item.analytics_source_id, item.analytics_license_receipt_id].forEach((part) => {
        path.append(node("span", "", text(part, "Not declared")));
      });
      card.append(path);
      const link = node("p", "lineage-link");
      link.append(publicSourceLink(item.canonical_uri));
      card.append(link);
      card.append(node("p", "lineage-access", `${humanize(item.entitlement_access)} · ${item.redistributable ? "Redistributable" : "Reference only"}`));
      return card;
    });
    replace("#source-lineage", cards.length ? cards : [empty("No source-lineage bindings were exposed.")]);
  }

  function renderRunCard(runCard) {
    const metadata = Object.entries(runCard)
      .filter(([key]) => !["stages", "source_batch_ids", "artifact_kinds", "coordinator_commitments"].includes(key))
      .map(([key, value]) => ({ label: labelFor(key), value }));
    renderRecords("#run-card-meta", metadata, "No run card was exposed.", "run-meta-card");

    const stages = list(runCard.stages).map((value, index) => {
      const stage = record(value);
      const item = node("li", "stage-item");
      item.dataset.status = text(stage.status, "unknown");
      const marker = node("span", "stage-marker", String(index + 1).padStart(2, "0"));
      const copy = node("div", "stage-copy");
      copy.append(node("h3", "", humanize(stage.stage_id, `Stage ${index + 1}`)));
      copy.append(node("p", "", `${humanize(stage.status)} · ${text(stage.attempts, "—")} attempt${Number(stage.attempts) === 1 ? "" : "s"}`));
      const receipt = node("code", "stage-digest", text(stage.output_digest, "No output digest"));
      item.append(marker, copy, receipt);
      if (stage.limitation) item.append(node("p", "stage-limitation", stage.limitation));
      return item;
    });
    replace("#run-card-stages", stages.length ? stages : [node("li", "empty-row", "No stage receipts were exposed.")]);
  }

  function renderAnalyticsBundle(analytics) {
    const cards = Object.entries(analytics).map(([key, value], index) => {
      const wrapper = node("article", "analytics-card");
      const header = node("header");
      header.append(node("span", "record-index", String(index + 1).padStart(2, "0")));
      header.append(node("h4", "", labelFor(key)));
      if (Array.isArray(value)) header.append(node("span", "count-chip", value.length));
      wrapper.append(header, disclosureValue(value, key));
      return wrapper;
    });
    replace("#analytics-bundle", cards.length ? cards : [empty("No analytics bundle was exposed.")]);
  }

  function renderOverview(view, overview, request, dossier) {
    const identity = record(firstDeclared(overview.identity, dossier.identity, request.identity));
    const symbol = firstDeclared(overview.symbol, identity.symbol);
    const company = firstDeclared(overview.company_name, overview.company_of_interest, identity.issuer_name, symbol);
    set("#hero-symbol", symbol);
    set("#rail-symbol", symbol);
    set("#hero-company", company);
    set("#hero-context", firstDeclared(overview.instrument_context, identity.instrument_id, identity.asset_type));
    set("#as-of-at", timestamp(firstDeclared(overview.as_of_at, overview.as_of_date, dossier.as_of_at, request.cutoff_at)));
    set("#completed-at", timestamp(firstDeclared(overview.completed_at, dossier.completed_at)));
    set("#research-mode", humanize(firstDeclared(overview.research_mode, request.research_mode)));
    set("#schema-version", firstDeclared(view.schema_version, overview.schema_version));
    set("#data-source-label", `${text(symbol, "Company")} · canonical result`);
    set("#run-status", humanize(overview.status, "Completed"));
    set("#prototype-notice", overview.prototype_notice, "Research output · verify against retained sources.");
    const status = q("#run-status");
    if (status) status.dataset.tone = overview.status === "completed" ? "complete" : "caution";
  }

  function render(view) {
    if (!isCompletedView(view)) {
      showEmpty("The requested result is not completed. Publication data remains hidden until completion.");
      return;
    }

    const overview = record(view.overview);
    const request = record(view.research_request);
    const dossier = record(view.research_dossier);
    const researchLab = record(view.research_lab);
    const analytics = record(firstDeclared(view.analytics, researchLab.analytics));
    const sourceLineage = record(view.source_lineage);
    const documents = list(firstDeclared(dossier.documents, dossier.source_documents));
    const claims = list(dossier.claims);

    renderOverview(view, overview, request, dossier);
    set("#recommendation", humanize(firstDeclared(overview.recommendation, dossier.recommendation)));
    set("#executive-summary", firstDeclared(overview.executive_summary, dossier.executive_summary), "No executive summary was declared.");
    renderRecords("#overview-metadata", {
      symbol: overview.symbol,
      issuer_name: firstDeclared(overview.issuer_name, overview.company_name),
      asset_type: overview.asset_type,
      exchange: overview.exchange,
      currency: overview.currency,
      country: overview.country,
      status: overview.status,
      profile: overview.profile,
      coverage_decision: overview.coverage_decision,
      non_executable: overview.non_executable
    }, "No overview metadata was exposed.");
    renderRecords("#request-metadata", {
      request_id: request.request_id,
      requested_at: request.requested_at,
      cutoff_at: request.cutoff_at,
      research_mode: request.research_mode,
      output_language: request.output_language,
      non_executable: request.non_executable
    }, "No research request metadata was exposed.");
    renderRecords("#request-objectives", record(request.research_plan).objectives, "No research objectives were exposed.");
    renderRecords("#request-coverage", record(request.research_plan).coverage_dimensions, "No coverage plan was exposed.");

    renderDocuments(documents);
    renderClaims(claims);
    renderRecords("#arguments", dossier.arguments, "No argument receipts were exposed.");
    renderLineage(sourceLineage);

    renderMetrics(list(dossier.metrics));
    renderRecords("#calculations", dossier.calculations, "No calculation receipts were exposed.");
    renderRecords("#valuations", firstDeclared(dossier.valuations, dossier.valuation_cases), "No valuations were exposed.");
    renderAnalyticsBundle(analytics);

    renderRecords("#risk-register", dossier.risks, "No risks were declared.");
    renderRecords(
      "#limitations",
      [...list(overview.warnings), ...list(dossier.limitations), ...list(view.warnings)],
      "No limitations or warnings were declared.",
      "limitation-card"
    );

    renderRecords("#monitoring-rules", firstDeclared(dossier.monitoring, dossier.monitoring_rules), "No monitoring rules were declared.");
    renderRecords("#research-delta", dossier.research_delta, "No research delta was exposed.");
    renderRecords("#hypotheses", firstDeclared(researchLab.hypotheses, view.hypotheses), "No hypotheses were exposed.");
    renderRecords("#iterations", firstDeclared(researchLab.iterations, view.iterations), "No iteration receipts were exposed.");
    renderRecords("#quality", firstDeclared(researchLab.quality, view.quality), "No quality receipt was exposed.");
    renderRecords("#forecasts", firstDeclared(researchLab.forecasts, view.forecasts), "No forecasts were exposed.");

    renderRunCard(record(firstDeclared(researchLab.run_card, view.run_card)));
    renderRecords("#reports", view.reports, "No reports were exposed.");
    renderRecords("#artifacts", view.artifacts, "No artifacts were exposed.");
    renderRecords("#events", view.events, "No lifecycle events were exposed.", "event-card");
    renderRecords("#actions", view.actions, "No viewer actions were exposed.");

    const emptyState = q("#empty-state");
    const shell = q("#report-shell");
    if (emptyState) emptyState.hidden = true;
    if (shell) shell.hidden = false;
    if (document.body.classList) document.body.classList.add("report-loaded");
    set("#interface-status", `Completed company analytics loaded for ${text(overview.symbol, text(record(dossier.identity).symbol, "company"))}.`);
  }

  function showEmpty(message) {
    const emptyState = q("#empty-state");
    const shell = q("#report-shell");
    if (shell) shell.hidden = true;
    if (emptyState) emptyState.hidden = false;
    set("#data-source-label", "No report loaded");
    set("#run-status", "Offline");
    set("#empty-copy", message);
    set("#interface-status", message);
  }

  function isCompletedView(view) {
    return record(view.overview).status === "completed";
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
      headers: { Accept: "application/json", "X-StockResearchAgents-Viewer-Token": accessToken },
      cache: "no-store"
    });
    if (!response.ok) return false;
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    return true;
  }

  async function load() {
    if (window.location.protocol === "file:") {
      showEmpty("Offline preview only. Start the loopback report server to load a canonical completed result.");
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
      if (accessToken) headers["X-StockResearchAgents-Viewer-Token"] = accessToken;
      const response = await fetch(endpoint, { headers, cache: "no-store" });
      if (!response.ok) {
        showEmpty(`No completed company analytics result is available (${response.status}).`);
        return;
      }
      const payload = await response.json();
      const view = record(payload.view).overview ? payload.view : payload;
      if (!payload || payload.ok === false || !view.overview || !isCompletedView(view)) {
        showEmpty("The local report endpoint returned no completed canonical result.");
        return;
      }
      render(view);
    } catch (_error) {
      showEmpty("The local result endpoint is unavailable. No report was loaded.");
    }
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      establishViewerSession,
      isCompletedView,
      publicSourceLink,
      render,
      researchValue,
      resolveViewEndpoint,
      timestamp,
      viewerAccessToken
    };
  }

  if (typeof window !== "undefined" && typeof document !== "undefined") load();
})();
