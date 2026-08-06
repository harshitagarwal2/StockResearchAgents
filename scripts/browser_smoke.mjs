#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import readline from "node:readline";

import AxeBuilder from "@axe-core/playwright";
import { chromium } from "playwright";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(process.env.STOCKRESEARCHAGENTS_ROOT || join(SCRIPT_DIR, ".."));
const STATE_DIR = mkdtempSync(join(tmpdir(), "stockresearchagents-browser-smoke-"));
const PYTHON = process.env.PYTHON || (existsSync(join(ROOT, ".venv", "bin", "python"))
  ? join(ROOT, ".venv", "bin", "python")
  : "python3");
const STARTUP_TIMEOUT_MS = 20_000;

const pythonServer = String.raw`
import json
import secrets
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

root = Path.cwd()
sys.path.insert(0, str(root / "tests"))

from company_analytics_fixtures import complete_analytics_submission
from stock_research_agents.company_analytics import build_company_analytics_draft, submit_company_analytics
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.store import RunStore
from stock_research_agents.viewer_server import create_viewer_server

state_dir = Path(sys.argv[1])
store = RunStore(state_dir / "runs")
completed, _events = submit_company_analytics(
    complete_analytics_submission("ORCL"),
    store=store,
    quality_store=QualityStore(),
)
partial = build_company_analytics_draft(complete_analytics_submission("META"))
store.put_events(partial.result.run_id, partial.events[:-1])

access_token = secrets.token_urlsafe(32)
server = create_viewer_server("127.0.0.1", 0, store=store, access_token=access_token)
host, port = server.server_address[:2]
query = urlencode({"run": completed.run_id})
fragment = urlencode({"access_token": access_token})
print(json.dumps({
    "url": f"http://{host}:{port}/?{query}#{fragment}",
    "completedRunId": completed.run_id,
    "partialRunId": partial.result.run_id,
}), flush=True)
server.serve_forever()
`;

function firstJsonLine(child) {
  return new Promise((resolveLine, rejectLine) => {
    const lines = readline.createInterface({ input: child.stdout });
    const stderr = [];
    child.stderr.on("data", (chunk) => stderr.push(chunk.toString()));
    const timeout = setTimeout(() => {
      lines.close();
      rejectLine(new Error(`viewer startup timed out: ${stderr.join("")}`));
    }, STARTUP_TIMEOUT_MS);
    lines.once("line", (line) => {
      clearTimeout(timeout);
      lines.close();
      try {
        resolveLine(JSON.parse(line));
      } catch (error) {
        rejectLine(new Error(`viewer emitted invalid startup metadata: ${line}`, { cause: error }));
      }
    });
    child.once("exit", (code) => {
      clearTimeout(timeout);
      rejectLine(new Error(`viewer exited before startup (code ${code}): ${stderr.join("")}`));
    });
  });
}

async function stopChild(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  const exited = await Promise.race([
    once(child, "exit").then(() => true),
    new Promise((resolveTimeout) => setTimeout(() => resolveTimeout(false), 2_000)),
  ]);
  if (!exited && child.exitCode === null && child.signalCode === null) {
    child.kill("SIGKILL");
    await once(child, "exit");
  }
}

async function assertCompletedDossier(page, viewportName) {
  await page.locator("#report-shell").waitFor({ state: "visible" });
  await assert.doesNotReject(() => page.locator("#hero-symbol").waitFor({ state: "visible" }));
  assert.equal((await page.locator("#hero-symbol").textContent())?.trim(), "ORCL");
  assert.equal((await page.locator("#run-status").textContent())?.trim(), "Completed");
  const bodyText = (await page.locator("body").innerText()).toLowerCase();
  assert.match(bodyText, /fixture/);
  assert.match(bodyText, /non-executable/);
  assert.ok(await page.locator("#run-card").isVisible(), `${viewportName}: run ledger is hidden`);
}

async function assertAccessible(page, viewportName) {
  const results = await new AxeBuilder({ page }).analyze();
  const material = results.violations.filter((violation) =>
    violation.impact === "serious" || violation.impact === "critical"
  );
  assert.deepEqual(material, [], `${viewportName}: serious/critical axe violations`);
}

const viewer = spawn(PYTHON, ["-u", "-c", pythonServer, STATE_DIR], {
  cwd: ROOT,
  env: { ...process.env, PYTHONUNBUFFERED: "1" },
  stdio: ["ignore", "pipe", "pipe"],
});

let browser;
try {
  const metadata = await firstJsonLine(viewer);
  const launchUrl = new URL(metadata.url);
  assert.equal(launchUrl.hostname, "127.0.0.1");
  assert.match(launchUrl.hash, /^#access_token=/);

  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "chromium", headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => runtimeErrors.push(`page: ${error.message}`));

  const sessionResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname === "/api/session"
  );
  await page.goto(metadata.url, { waitUntil: "domcontentloaded" });
  const exchanged = await sessionResponse;
  assert.equal(exchanged.status(), 200);
  const setCookie = await exchanged.headerValue("set-cookie");
  assert.match(setCookie || "", /stockresearchagents_viewer=.*HttpOnly.*SameSite=Strict/i);
  await page.waitForFunction(() => window.location.hash === "");
  assert.equal(new URL(page.url()).hash, "");
  assert.ok(!page.url().includes("access_token"));

  const cookies = await context.cookies();
  const sessionCookie = cookies.find((cookie) => cookie.name === "stockresearchagents_viewer");
  assert.ok(sessionCookie, "viewer session cookie was not created");
  assert.equal(sessionCookie.httpOnly, true);
  assert.ok(!(await page.evaluate(() => document.cookie)).includes("stockresearchagents_viewer"));

  await assertCompletedDossier(page, "desktop");
  await assertAccessible(page, "desktop");

  const partialResponse = await context.request.get(
    new URL(`/api/runs/${encodeURIComponent(metadata.partialRunId)}/view`, page.url()).href,
    { headers: { Accept: "application/json" } },
  );
  const partial = { status: partialResponse.status(), payload: await partialResponse.json() };
  assert.equal(partial.status, 404);
  assert.equal(partial.payload.ok, false);
  assert.ok(!Object.hasOwn(partial.payload, "view"));
  assert.ok(!Object.hasOwn(partial.payload, "result"));

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload({ waitUntil: "domcontentloaded" });
  await assertCompletedDossier(page, "narrow");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 1, `narrow: page overflows horizontally by ${overflow}px`);
  await assertAccessible(page, "narrow");
  assert.deepEqual(runtimeErrors, [], "viewer emitted console or page errors");

  await context.close();
  console.log(JSON.stringify({
    ok: true,
    fixture: true,
    nonExecutable: true,
    completedRunId: metadata.completedRunId,
    viewports: ["1440x1000", "390x844"],
    accessibility: "axe serious/critical: 0",
  }));
} finally {
  if (browser) await browser.close();
  await stopChild(viewer);
  rmSync(STATE_DIR, { recursive: true, force: true });
}
