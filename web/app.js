/* GTM Decision Engine demo UI. A client of the headless engine:
   - local:  HTTP calls to the FastAPI app (/api/...)
   - hosted: the same Python engine running in the browser (Pyodide), called through gde.bridge
   No business logic lives here. */
"use strict";

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
const REPO = "https://github.com/vrutikadani/gtm-decision-engine";
const S = { mode: null, dispatch: null, scenarios: [], tab: "trace", feedback: {}, briefClaim: null, dataTab: "accounts" };

// ------------------------------------------------------------------ transport
async function call(method, path, body) {
  let res;
  if (S.mode === "api") {
    const r = await fetch("/api" + path, { method, headers: { "content-type": "application/json" },
      body: body ? JSON.stringify(body) : (method === "POST" ? "{}" : undefined) });
    res = { status: r.status, body: await r.json() };
  } else {
    res = JSON.parse(S.dispatch(method, path, body ? JSON.stringify(body) : ""));
  }
  if (res.status >= 400) {
    const e = new Error(res.body.detail || res.body.error || "error");
    e.status = res.status; e.kind = res.body.error; throw e;
  }
  return res.body;
}

async function boot() {
  const step = (t, n) => { $("#loading-step").textContent = t; if (n !== undefined) $("#loading-note").textContent = n; };
  const local = ["localhost", "127.0.0.1"].includes(location.hostname) && !location.search.includes("mode=browser");
  if (local) {
    try {
      const r = await fetch("/api/health");
      if (r.ok) { S.mode = "api"; }
    } catch (_) { /* fall through to browser mode */ }
  }
  if (!S.mode) {
    S.mode = "browser";
    step("Loading the Python runtime…", "The engine runs in your browser. First load downloads about 10 MB; nothing is sent anywhere.");
    await loadScript(PYODIDE + "pyodide.js");
    const py = await loadPyodide({ indexURL: PYODIDE });
    step("Loading SQLite…");
    await py.loadPackage("sqlite3");
    step("Loading the engine…");
    const manifest = await (await fetch("py_manifest.json")).json();
    await Promise.all(manifest.files.map(async (f) => {
      const text = await (await fetch("../" + f)).text();
      const dir = "/home/pyodide/" + f.split("/").slice(0, -1).join("/");
      py.FS.mkdirTree(dir);
      py.FS.writeFile("/home/pyodide/" + f, text);
    }));
    step("Seeding synthetic data…");
    const bridge = py.pyimport("gde.bridge");
    S.dispatch = (m, p, b) => bridge.dispatch(m, p, b);
  }
  const h = await call("GET", "/health");
  $("#mode").textContent = S.mode === "api" ? `Local API · LLM: ${h.llm}` : `Hosted · Python in your browser · LLM: ${h.llm}`;
  $("#mode").title = S.mode === "api" ? "UI calls the FastAPI service on this machine" :
    "The same Python package runs in your browser. Deterministic mock LLM, no API keys.";
  if (S.mode === "api") { const a = $("#api-docs"); a.hidden = false; a.href = "/docs"; }
  S.scenarios = await call("GET", "/demo/scenarios");
  renderScenarioList();
  $("#reset").onclick = async () => { await call("POST", "/demo/reset"); S.feedback = {}; toast("Demo reset to the seeded baseline"); go("#/"); refreshChrome(); };
  window.addEventListener("hashchange", route);
  await route();
}

function loadScript(src) {
  return new Promise((ok, fail) => { const s = document.createElement("script"); s.src = src; s.onload = ok;
    s.onerror = () => fail(new Error("could not load " + src)); document.head.appendChild(s); });
}

// ------------------------------------------------------------------ helpers
const $ = (q, el = document) => el.querySelector(q);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const json = (o) => `<pre class="json">${esc(JSON.stringify(o, null, 2))}</pre>`;
const go = (h) => { if (location.hash === h) route(); else location.hash = h; };
function tone(s) {
  s = String(s || "");
  if (/FAIL|critical|failed|DELIVERY_FAILED/.test(s)) return "bad";
  if (/^(SUPPRESS|SUPPRESSED|SKIPPED|NONE|DISMISSED|DUPLICATE|cancelled|SUPERSEDED|NONE ELIGIBLE|NO_MATCH|MISSING)/.test(s)) return "";
  if (/REVIEW|HOLD|HELD|WEAK|SNOOZED|UNAVAILABLE|PENDING|pending|CORRECTED|UNCLEAR|degraded|OUTSIDE|UNKNOWN/.test(s)) return "warn";
  if (/PASS|MATCH|CONFIRMED|DELIVER|ACCEPTED|EXECUTED|^OK|FOUND|RECEIVED|done|^ok/.test(s)) return "ok";
  return "info";
}
const badge = (s, cls) => `<span class="badge ${cls === undefined ? tone(s) : cls}">${esc(s)}</span>`;
function toast(msg, isErr) {
  const t = document.createElement("div"); t.className = "toast" + (isErr ? " err" : ""); t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), 3800);
}
async function safe(fn) {
  try { return await fn(); } catch (e) { toast((e.status ? e.status + " " : "") + e.message, true); console.error(e); }
}
function setActive(view) {
  document.querySelectorAll(".side a[data-view]").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  document.querySelectorAll(".side button.scn").forEach((b) => b.classList.toggle("active", "s" + b.dataset.n === view));
}
async function refreshChrome() {
  const h = await call("GET", "/health");
  $("#clock").textContent = "demo clock " + h.now.replace("T", " ").replace(":00Z", " UTC");
  const r = await call("GET", "/reviews");
  $("#review-count").textContent = r.length || "";
}

function renderScenarioList() {
  $("#scenario-list").innerHTML = S.scenarios.map((s) =>
    `<button class="scn" data-n="${s.n}"><span class="n">${s.n}</span>${esc(s.title)}</button>`).join("");
  document.querySelectorAll(".scn").forEach((b) => b.onclick = () => runScenario(+b.dataset.n));
}

async function runScenario(n) {
  await safe(async () => {
    S.feedback = {}; S.tab = "trace";
    const r = await call("POST", `/demo/scenarios/${n}`);
    S.lastScenario = r;
    if (n === 3) go(`#/brief?s=3`);
    else if (n === 6) go(`#/failure-story`);
    else go(`#/decision/${r.decision_id}?s=${n}`);
  });
}

// ------------------------------------------------------------------ router
async function route() {
  const [path, q] = (location.hash.slice(1) || "/").split("?");
  const params = new URLSearchParams(q || "");
  const parts = path.split("/").filter(Boolean);
  const main = $("#main");
  await safe(async () => {
    await refreshChrome();
    const s = params.get("s");
    if (parts[0] === "decision") { setActive(s ? "s" + s : "decisions"); main.innerHTML = await viewDecision(parts[1], s && +s); bindDecision(parts[1], s && +s); }
    else if (parts[0] === "brief") { setActive(params.get("s") ? "s3" : "brief"); main.innerHTML = await viewBrief(params.get("s")); bindBrief(); }
    else if (parts[0] === "failure-story") { setActive("s6"); main.innerHTML = await viewFailureStory(); }
    else if (parts[0] === "slack") { setActive("slack"); main.innerHTML = await viewSlack(); }
    else if (parts[0] === "decisions") { setActive("decisions"); main.innerHTML = await viewDecisions(); }
    else if (parts[0] === "reviews") { setActive("reviews"); main.innerHTML = await viewReviews(); bindReviews(); }
    else if (parts[0] === "reliability") { setActive("reliability"); main.innerHTML = await viewReliability(); bindReliability(); }
    else if (parts[0] === "failures") { setActive("failures"); main.innerHTML = await viewFailures(); bindFailures(); }
    else if (parts[0] === "data") { setActive("data"); main.innerHTML = await viewData(parts[1]); bindData(); }
    else if (parts[0] === "architecture") { setActive("architecture"); main.innerHTML = viewArchitecture(); }
    else { setActive(""); main.innerHTML = viewOverview(); bindOverview(); }
    document.querySelectorAll("[data-href]").forEach((el) => el.onclick = () => go(el.dataset.href));
    window.scrollTo(0, 0);
  });
}

// ------------------------------------------------------------------ overview
function viewOverview() {
  return `<div class="head"><h1>What this system does</h1>
  <p class="presenter">Something happens (a former champion changes jobs, competitors start coming up on calls). The system gathers
  context from the CRM, the warehouse and conversations, evaluates it against explicit rules, then <b>makes or withholds</b> a decision.
  When it acts, a seller gets one card with the evidence and an approved play. Seller feedback changes what it does next.</p></div>
  <div class="flow">${["Signal", "Context", "Evaluate", "Decide or hold", "Evidence", "Slack card", "Seller feedback"].map((t, i, a) =>
    `<div class="f"><div class="chip ok"><b>${i + 1}</b>${t}</div>${i < a.length - 1 ? '<span class="arrow">→</span>' : ""}</div>`).join("")}</div>
  <div class="panel"><h2>Demo scenarios</h2>
  <div class="tablewrap"><table><thead><tr><th>#</th><th>Scenario</th><th>What it shows</th></tr></thead><tbody>
  ${S.scenarios.map((s) => `<tr class="click" data-n="${s.n}"><td>${s.n}</td><td><b>${esc(s.title)}</b></td><td class="muted">${esc(s.show)}</td></tr>`).join("")}
  </tbody></table></div>
  <p class="muted small">Each scenario resets the synthetic world first, so it gives the same result every time. Where the model runs:
  labeling buying intent in prospect utterances, extracting competitor mentions, and drafting one sentence of seller copy. It never
  picks the person, the play, the owner, or writes to the CRM.</p></div>`;
}
function bindOverview() { document.querySelectorAll("tr[data-n]").forEach((r) => r.onclick = () => runScenario(+r.dataset.n)); }

// ------------------------------------------------------------------ decision view
async function viewDecision(id, scen) {
  const d = await call("GET", `/decisions/${id}`);
  const ins = await call("GET", `/decisions/${id}/inspect`);
  S.current = { d, ins };
  const meta = scen ? S.scenarios.find((s) => s.n === scen) : null;
  const step = (k) => d.trace.find((t) => t.step === k) || {};
  const slackPosted = ins.side_effects.slack.length;
  const fb = ins.feedback[ins.feedback.length - 1];
  const crmLive = ins.side_effects.crm.filter((r) => r.kind !== "revert" && !r.reverted).length;
  const crmRev = ins.side_effects.crm.filter((r) => r.reverted).length;
  const chips = [
    ["Signal", step("signal").status], ["Identity", step("identity").status], ["Champion", step("champion").status],
    ["Account", step("qualification").status], ["Decision", d.outcome],
    ["Slack", slackPosted ? "POSTED" : (d.state === "DELIVERY_FAILED" ? "FAILED" : "—")],
    ["Seller", fb ? fb.action.toUpperCase() + (fb.reason ? ": " + fb.reason : "") : (slackPosted ? "WAITING" : "—")],
    ["CRM", crmLive || crmRev ? `${crmLive} live${crmRev ? ", " + crmRev + " reverted" : ""}` : "—"],
  ];
  const chipTone = (v) => { const t = tone(v); return v === "—" || v === "SKIPPED" || !v ? "idle" : (t === "info" ? "ok" : t || "idle"); };
  return `<div class="head">
    <div class="spread"><div><h1>${meta ? `Scenario ${meta.n} · ${esc(meta.title)}` : `Decision ${esc(d.id)}`}</h1>
    <div class="muted small mono">${esc(d.id)} · run ${esc(d.run_id)} · ${d.superseded_by ? `superseded by <a href="#/decision/${esc(d.superseded_by)}${scen ? "?s=" + scen : ""}">${esc(d.superseded_by)}</a> · run state` : "state"} ${badge(d.state)}</div></div>
    ${scen ? `<button class="btn" id="rerun-scn">Run again from baseline</button>` : ""}</div>
    ${meta ? `<div class="presenter"><b>Show:</b> ${esc(meta.show)}</div>` : ""}</div>
  <div class="flow">${chips.map(([k, v], i) => `<div class="f"><div class="chip ${chipTone(v)}"><b>${k}</b>${esc(v || "—")}</div>${i < chips.length - 1 ? '<span class="arrow">→</span>' : ""}</div>`).join("")}</div>
  <div class="grid2">
    <div class="stack">${d.surface ? slackCard(d, ins) : await outcomePanel(d)}${scen === 5 ? followups() : ""}</div>
    <div class="panel"><div class="tabs">
      <button data-tab="trace" class="${S.tab === "trace" ? "on" : ""}">Why did the system decide this?</button>
      <button data-tab="sources" class="${S.tab === "sources" ? "on" : ""}">Sources (${d.sources.length})</button>
      <button data-tab="inspector" class="${S.tab === "inspector" ? "on" : ""}">System inspector</button></div>
      <div id="tabbody">${tabBody(d, ins)}</div></div>
  </div>`;
}

function tabBody(d, ins) {
  if (S.tab === "sources") return sourcesTable(d.sources);
  if (S.tab === "inspector") return inspector(ins);
  return traceView(d);
}

function slackCard(d, ins) {
  const s = d.surface, st = d.state;
  const can = { accept: st === "DELIVERED", execute: st === "ACCEPTED", snooze: st === "DELIVERED", dismiss: st === "DELIVERED", correct: ["DELIVERED", "ACCEPTED"].includes(st) };
  const posted = ins.side_effects.slack[0];
  const res = S.feedback[d.id];
  return `<div class="slack">
    <div class="slack-top"><span>Slack · DM to <b>${esc(s.owner.name)}</b> (${esc(s.owner.slack)})</span><span class="mono">${posted ? "ts " + esc(posted.ts) : "not posted"}</span></div>
    <div class="slack-msg"><div class="avatar">GS</div><div>
      <div class="slack-name">GTM Signals <span class="app">APP</span></div>
      <div class="blk">
        <div class="hd">Former champion joined ${esc(s.account)}</div>
        <div class="fld"><b>Account</b>${esc(s.account)} · Tier ${esc(s.tier)} · owner ${esc(s.owner.name)}</div>
        <div class="fld"><b>Why now</b>${esc(s.why_now)}</div>
        <div class="fld"><b>Who</b>${esc(s.who.name)}, ${esc(s.who.title)} <span class="muted">(was ${esc(s.who.previous)})</span>
          · identity ${Math.round(s.identity_confidence * 100)}%</div>
        <div class="fld"><b>Evidence</b><ul>${s.evidence.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>
        <div class="fld"><b>Approved play</b><span class="mono">${esc(s.play.id)}</span> · ${esc(s.play.name)}</div>
        <div class="fld"><b>Next best action</b>${esc(s.next_best_action)}</div>
        <div class="fld"><b>Suggested opener</b><div class="opener">${esc(s.suggested_opener)}</div>
          <div class="muted small">Drafted by the model from four facts; checked by rules before it is shown.</div></div>
        <div class="controls">
          <button class="btn primary sm" data-fb="accept" ${can.accept ? "" : "disabled"}>Accept</button>
          <button class="btn sm" data-fb="execute" ${can.execute ? "" : "disabled"}>Mark done</button>
          <button class="btn sm" data-fb="snooze" ${can.snooze ? "" : "disabled"}>Snooze 7d</button>
          <button class="btn sm" data-fb="dismiss" ${can.dismiss ? "" : "disabled"}>Dismiss</button>
          <button class="btn sm danger" id="correct-btn" ${can.correct ? "" : "disabled"}>Correct ▾</button>
          <div class="menu" id="correct-menu" hidden>
            <button data-reason="wrong_person">Wrong person<small>Not the person we worked with</small></button>
            <button data-reason="wrong_play">Wrong play<small>Right person, wrong action</small></button>
            <button data-reason="already_engaged">Already engaged<small>I'm already talking to them</small></button>
            <button data-reason="wrong_account">Wrong account<small>Company mapping is wrong</small></button>
          </div>
        </div>
      </div>
    </div></div>
    ${res ? feedbackResult(res) : ""}
    <div style="padding:0 14px 12px" class="muted small">Buttons call <span class="mono">POST /feedback</span>. Invalid clicks are rejected by the state machine, not hidden.</div>
  </div>`;
}

function feedbackResult(r) {
  if (r.error) return `<div class="result" style="margin:0 14px 12px"><b class="err">${esc(r.error)}</b></div>`;
  let html = `<div class="result" style="margin:0 14px 12px"><b>Feedback ${esc(r.feedback_id)}</b> → state ${badge(r.state)}<ul>${r.effects.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>`;
  if (r.rerun) html += `<div style="margin-top:6px">Re-evaluated the same signal: ${badge(r.rerun.outcome)} ${esc(r.rerun.reason)}
     <a href="#/decision/${esc(r.rerun.id)}${S.scen ? "?s=" + S.scen : ""}">open ${esc(r.rerun.id)}</a></div>`;
  return html + "</div>";
}

async function outcomePanel(d) {
  const next = {
    NEEDS_REVIEW: "No seller message was sent. A person decides first.",
    HOLD: "No seller message was sent. The run is held and can be retried when the dependency recovers.",
    SUPPRESS: "No seller message was sent. The trace shows which rule stopped it.",
  }[d.outcome] || "";
  let html = `<div class="panel"><div class="row" style="margin-bottom:6px">${badge(d.outcome)}${d.state !== d.outcome ? " " + badge(d.state) : ""}</div>
    <div style="font-size:15px;font-weight:600">${esc(d.reason)}</div><p class="muted">${next}</p>`;
  if (d.outcome === "HOLD" && d.state === "HELD") html += `<button class="btn primary" id="retry-run" data-run="${esc(d.run_id)}">Retry now</button>`;
  html += `</div>`;
  if (d.outcome === "NEEDS_REVIEW") {
    const items = (await call("GET", "/reviews")).filter((r) => r.decision_id === d.id);
    html += items.length ? reviewCard(items[0]) : `<div class="panel muted">Review already resolved.</div>`;
  }
  return html;
}

function followups() {
  return `<div class="panel"><h2>After the correction</h2>
    <p class="muted small">Does the system repeat the mistake? Try both after pressing Correct → Wrong person.</p>
    <div class="row"><button class="btn" data-follow="replay_same_webhook">Vendor redelivers the same webhook</button>
    <button class="btn" data-follow="other_vendor_later">Second vendor, 20 days later, no profile URL</button></div>
    <div id="follow-out"></div></div>`;
}

function traceView(d) {
  return `<div class="trace">${d.trace.map((t) => {
    const tn = t.status === "SKIPPED" ? "" : tone(t.status);
    return `<div class="ts ${t.status === "SKIPPED" ? "skipped" : ""}"><div class="rail"><span class="dot ${tn === "info" ? "ok" : tn}"></span><span class="line"></span></div>
      <div class="body"><div class="lbl">${esc(t.label)} ${badge(t.status)}${t.data && t.data.confidence !== undefined ? `<span class="muted small">confidence ${t.data.confidence.toFixed(2)}</span>` : ""}</div>
      <div class="det">${esc(t.detail)}</div>${t.rule ? `<div class="rule">rule: ${esc(t.rule)}</div>` : ""}${traceExtra(t)}</div></div>`;
  }).join("")}</div>
  <p class="muted small">This is the explicit business-rule and evidence trace the engine writes for every decision
  (<span class="mono">GET /decisions/${esc(d.id)}/trace</span>). It is not model reasoning.</p>`;
}

function traceExtra(t) {
  const dd = t.data || {};
  if (t.step === "identity" && dd.candidates && dd.candidates.length) {
    const feats = ["profile_url", "name_exact", "previous_employer", "metro", "title_family"];
    return `<details class="more" ${t.status === "REVIEW" ? "open" : ""}><summary>${dd.candidates.length} candidate record(s)</summary><div class="tablewrap"><table>
      <thead><tr><th>Candidate</th><th>Current account</th>${feats.map((f) => `<th>${f.replace("_", " ")}</th>`).join("")}<th>Score</th></tr></thead><tbody>
      ${dd.candidates.map((c) => `<tr><td class="mono">${esc(c.person_id)}<br>${esc(c.name)}</td><td>${esc(c.current_account)}</td>
        ${c.excluded ? `<td colspan="${feats.length + 1}" class="muted">excluded: ${esc(c.excluded)}</td>` :
          feats.map((f) => `<td class="${c.features[f] ? "yes" : "no"}">${c.features[f] ? "✓" : "·"}</td>`).join("") + `<td class="mono">${c.score.toFixed(2)}</td>`}</tr>`).join("")}
      </tbody></table></div><div class="muted small">Score = 1 − Π(1 − w) over matching features. Weights: profile URL .80, previous employer .50, name .30, metro .15, title family .10.</div></details>`;
  }
  if (t.step === "champion" && dd.evidence && dd.evidence.length) {
    return `<details class="more"><summary>${dd.evidence.length} evidence record(s), types: ${esc(dd.types.join(", "))}</summary><div class="tablewrap"><table>
      <thead><tr><th>Type</th><th>Source</th><th>Record</th><th>Age</th></tr></thead><tbody>
      ${dd.evidence.map((e) => `<tr><td>${esc(e.type)}${e.first_party ? ' <span class="badge ok">1st party</span>' : ""}</td><td>${esc(e.source)}</td><td class="mono">${esc(e.record_id)}</td><td>${e.age_days}d</td></tr>`).join("")}
      </tbody></table></div></details>`;
  }
  if (t.step === "context" && dd.conflicts && dd.conflicts.length) {
    return `<details class="more"><summary>${dd.conflicts.length} source disagreement(s)</summary><table><thead><tr><th>Field</th><th>Values</th><th>Used</th><th>Rule</th></tr></thead><tbody>
      ${dd.conflicts.map((c) => `<tr><td>${esc(c.field)}</td><td class="mono">${esc(JSON.stringify(c.values))}</td><td>${esc(c.used)}</td><td class="mono">${esc(c.rule)}</td></tr>`).join("")}</tbody></table></details>`;
  }
  if (t.step === "conversation_context" && dd.intents && dd.intents.length) {
    return `<details class="more" open><summary>${dd.intents.length} labeled utterance(s)</summary>${dd.intents.map((i) =>
      `<div class="cite cur"><div class="src">${badge(i.label)} <span class="mono">${esc(i.conversation_id)}</span> ${esc(i.title)} · ${i.age_days}d ago · conf ${i.confidence}</div>“${esc(i.quote)}”</div>`).join("")}</details>`;
  }
  if (t.step === "plays" && dd.results) {
    return `<details class="more"><summary>${dd.results.length} plays checked in registry order</summary><table><thead><tr><th>Play</th><th>Result</th></tr></thead><tbody>
      ${dd.results.map((r) => `<tr><td class="mono">${esc(r.play)}</td><td>${r.eligible ? badge("PASS") : esc(r.failed.join("; "))}</td></tr>`).join("")}</tbody></table></details>`;
  }
  return "";
}

function sourcesTable(src) {
  if (!src.length) return `<div class="empty">No sources were consulted before the workflow stopped.</div>`;
  return `<p class="q">Every claim on the card points back to one of these records.</p><div class="tablewrap"><table><thead><tr><th>Source</th><th>Record</th><th>Timestamp</th><th>Age</th><th>Evidence</th><th>Conf.</th></tr></thead><tbody>
  ${src.map((s) => `<tr><td><b>${esc(s.source_type)}</b></td><td class="mono">${esc(s.record_id)}</td><td class="mono">${esc((s.timestamp || "—").replace("T00:00:00Z", ""))}</td>
    <td>${s.freshness_days == null ? "—" : s.freshness_days + "d"}</td><td>${esc(s.evidence)}</td><td>${s.confidence == null ? "—" : Number(s.confidence).toFixed(2)}</td></tr>`).join("")}
  </tbody></table></div>`;
}

function inspector(ins) {
  const sec = (title, summary, body, open) => `<details ${open ? "open" : ""}><summary>${title}<span>${summary}</span></summary><div class="in">${body}</div></details>`;
  const o = ins.output, se = ins.side_effects;
  return `<div class="insp"><p class="q">“Walk me through exactly what happens after the webhook arrives.”</p>
  ${sec("1 · Inputs", `${esc(ins.inputs.provider)} webhook`, `<div class="muted small">Raw vendor payload</div>${json(ins.inputs.raw_payload)}
     <div class="muted small" style="margin-top:8px">Normalized JobChange (providers/job_change.py)</div>${json(ins.inputs.normalized)}
     <div class="small">Subject keys (used to remember corrections): <span class="mono">${esc(ins.inputs.subject_keys.join(" · "))}</span></div>`, true)}
  ${sec("2 · Context", esc(ins.context.status || ""), `<div>${esc(ins.context.detail || "not reached")}</div>${ins.context.conflicts ? json(ins.context.conflicts) : ""}`)}
  ${sec("3 · Evidence", `${ins.evidence.length} records`, sourcesTable(ins.evidence))}
  ${sec("4 · Rules", `${ins.rules.filter((r) => r.status !== "SKIPPED").length} checks ran`, `<table><thead><tr><th>Step</th><th>Status</th><th>Rule</th></tr></thead><tbody>
     ${ins.rules.map((r) => `<tr><td>${esc(r.step)}</td><td>${badge(r.status)}</td><td class="mono">${esc(r.rule)}</td></tr>`).join("")}</tbody></table>`)}
  ${sec("5 · Model", ins.model.used ? `${ins.model.calls.length} bounded call(s)` : "not used", `<p class="small"><b>Boundary:</b> ${esc(ins.model.boundary)}</p>
     ${ins.model.calls.length ? `<table><thead><tr><th>Purpose</th><th>Provider</th><th>Input</th><th>Output</th><th>Validated</th></tr></thead><tbody>
     ${ins.model.calls.map((c) => `<tr><td class="mono">${esc(c.purpose)}</td><td>${esc(c.provider)} / ${esc(c.model)}</td><td class="mono">${esc(typeof c.input === "string" ? c.input : JSON.stringify(c.input))}</td>
       <td>${esc(typeof c.output === "string" ? c.output : JSON.stringify(c.output))}</td><td>${c.validated ? badge("PASS") : badge("FAIL")}</td></tr>`).join("")}</tbody></table>` : `<div class="muted">The workflow stopped before any model call.</div>`}`)}
  ${sec("6 · State", esc(ins.state.current), `<table><thead><tr><th>#</th><th>From</th><th>To</th><th>Reason</th></tr></thead><tbody>
     ${ins.state.transitions.map((t) => `<tr><td>${t.seq}</td><td>${badge(t.from_state)}</td><td>${badge(t.to_state)}</td><td>${esc(t.reason)}</td></tr>`).join("")}</tbody></table>
     <div class="muted small">Allowed transitions are a table in workflows/state.py. Anything else is rejected and audited.</div>`)}
  ${sec("7 · Output", esc(o.outcome), `<div>${esc(o.reason)}</div>${o.surface ? json(o.surface) : ""}`)}
  ${sec("8 · Side effects", `Slack ${se.slack.length} · CRM ${se.crm.length} · outbox ${se.outbox.length}`, `
     <div class="muted small">Outbox (written in the same transaction as the decision)</div>
     ${se.outbox.length ? `<table><thead><tr><th>Row</th><th>Kind</th><th>Status</th><th>Attempts</th><th>Last error</th></tr></thead><tbody>
       ${se.outbox.map((r) => `<tr><td class="mono">${esc(r.id)}</td><td>${esc(r.kind)}</td><td>${badge(r.status)}</td><td>${r.attempts}</td><td>${esc(r.last_error || "")}</td></tr>`).join("")}</tbody></table>` : `<div class="muted">none</div>`}
     <div class="muted small" style="margin-top:8px">Slack messages (metadata carries the idempotency key)</div>
     ${se.slack.length ? se.slack.map((m) => `<div class="mono small">${esc(m.channel)} ts ${esc(m.ts)} key ${esc(m.metadata.gde_key)}</div>`).join("") : `<div class="muted">none</div>`}
     <div class="muted small" style="margin-top:8px">CRM records (search-before-create on gde_key)</div>
     ${se.crm.length ? `<table><thead><tr><th>CRM id</th><th>Kind</th><th>gde_key</th><th>Status</th></tr></thead><tbody>
       ${se.crm.map((r) => `<tr><td class="mono">${esc(r.id)}</td><td>${esc(r.kind)}${r.action ? " · " + esc(r.action) : ""}</td><td class="mono">${esc(r.gde_key)}</td><td>${r.reverted ? badge("reverted", "") : r.kind === "revert" ? "" : badge("live", "ok")}</td></tr>`).join("")}</tbody></table>` : `<div class="muted">none</div>`}`)}
  ${sec("9 · Feedback", `${ins.feedback.length} event(s)`, ins.feedback.length ? `<table><thead><tr><th>Id</th><th>Action</th><th>Reason</th><th>At</th></tr></thead><tbody>
     ${ins.feedback.map((f) => `<tr><td class="mono">${esc(f.id)}</td><td>${esc(f.action)}</td><td>${esc(f.reason || "")}</td><td class="mono">${esc(f.at)}</td></tr>`).join("")}</tbody></table>` : `<div class="muted">No seller feedback yet.</div>`)}
  ${sec("Audit log", `${ins.audit.length} events`, `<table><tbody>${ins.audit.map((a) => `<tr><td class="mono">${a.seq}</td><td class="mono">${esc(a.kind)}</td><td class="small">${esc(JSON.stringify(a.detail))}</td></tr>`).join("")}</tbody></table>`)}
  </div>`;
}

function bindDecision(id, scen) {
  S.scen = scen;
  document.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => {
    S.tab = b.dataset.tab; document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    $("#tabbody").innerHTML = tabBody(S.current.d, S.current.ins);
  });
  const rerun = $("#rerun-scn"); if (rerun) rerun.onclick = () => runScenario(scen);
  document.querySelectorAll("[data-fb]").forEach((b) => b.onclick = () => sendFeedback(id, b.dataset.fb, null));
  const cb = $("#correct-btn"), menu = $("#correct-menu");
  if (cb) cb.onclick = (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; };
  document.querySelectorAll("[data-reason]").forEach((b) => b.onclick = () => sendFeedback(id, "correct", b.dataset.reason));
  const rr = $("#retry-run"); if (rr) rr.onclick = () => safe(async () => { const d = await call("POST", `/runs/${rr.dataset.run}/retry`); go(`#/decision/${d.id}${scen ? "?s=" + scen : ""}`); });
  bindReviews(scen);
  document.querySelectorAll("[data-follow]").forEach((b) => b.onclick = () => safe(async () => {
    const r = await call("POST", `/demo/scenarios/5/followup/${b.dataset.follow}`);
    const x = r.result;
    $("#follow-out").innerHTML = `<div class="result"><b>${esc(r.description)}</b><br>${x.duplicate ? badge("DUPLICATE") + " " + esc(x.reason)
      : `${badge(x.outcome)} ${esc(x.reason)} <a href="#/decision/${esc(x.id)}">open ${esc(x.id)}</a>`}
      <div class="muted small">Seller messages sent in total: ${r.slack_messages_total}</div></div>`;
    refreshChrome();
  }));
}

async function sendFeedback(id, action, reason) {
  try {
    const body = { decision_id: id, action };
    if (reason) body.reason = reason;
    if (action === "snooze") body.days = 7;
    S.feedback[id] = await call("POST", "/feedback", body);
  } catch (e) {
    S.feedback[id] = { error: `${e.status} ${e.kind}: ${e.message}` };
  }
  route();
}

// ------------------------------------------------------------------ reviews
function reviewCard(r) {
  const live = r.candidates.filter((c) => !c.excluded);
  const feats = ["profile_url", "name_exact", "previous_employer", "metro", "title_family"];
  return `<div class="panel"><div class="spread"><h2>Review ${esc(r.id)} · ${esc(r.queue)} queue</h2>${badge("NEEDS_REVIEW")}</div>
    <p style="margin-top:0">${esc(r.reason)}</p>
    <div class="small muted">Signal: <b>${esc(r.signal.name)}</b> → ${esc(r.signal.new_title)} at ${esc(r.signal.new_company)}
      · previous company: ${esc(r.signal.previous_company || "not given")} · profile URL: ${esc(r.signal.profile_url || "not given")}</div>
    ${live.length ? `<div class="tablewrap" style="margin-top:8px"><table class="cand"><thead><tr><th>Candidate</th><th>Current account</th>${["URL", "Name", "Prev. co.", "Metro", "Title"].map((f) => `<th>${f}</th>`).join("")}<th>Score</th><th></th></tr></thead><tbody>
    ${live.map((c) => `<tr><td class="mono">${esc(c.person_id)}<br>${esc(c.name)}</td><td>${esc(c.current_account)}</td>${feats.map((f) => `<td class="${c.features[f] ? "yes" : "no"}">${c.features[f] ? "✓" : "·"}</td>`).join("")}
      <td class="mono">${c.score.toFixed(2)}</td><td><button class="btn sm primary" data-review="${esc(r.id)}" data-choice="${esc(c.person_id)}">This one</button></td></tr>`).join("")}
    </tbody></table></div>` : ""}
    <div class="row" style="margin-top:10px">${live.length ? `<button class="btn sm" data-review="${esc(r.id)}" data-choice="none">None of these</button>` : ""}
    <span class="muted small">Choosing resumes the workflow with the reviewer recorded in the trace. “None” remembers the exclusion.</span></div></div>`;
}
async function viewReviews() {
  const items = await call("GET", "/reviews");
  return `<div class="head"><h1>Human review queue</h1><p class="presenter">Uncertainty is represented, not hidden: anything the rules cannot settle waits here, and no seller sees it until a person decides.</p></div>
  ${items.length ? `<div class="stack">${items.map(reviewCard).join("")}</div>` : `<div class="empty">Queue is empty. Run scenario 2 to create an identity review.</div>`}`;
}
function bindReviews(scen) {
  document.querySelectorAll("[data-review]").forEach((b) => b.onclick = () => safe(async () => {
    const out = await call("POST", `/reviews/${b.dataset.review}`, { choice: b.dataset.choice, reviewer: "revops-ana" });
    if (out.id) go(`#/decision/${out.id}${scen ? "?s=" + scen : ""}`); else { toast("Review resolved: " + out.state); route(); }
  }));
}

// ------------------------------------------------------------------ brief
async function viewBrief(s) {
  const b = await call("GET", "/briefs");
  S.brief = b;
  const nConv = b.windows.current.conversations.length + b.windows.prior.conversations.length;
  const head = s ? `<h1>Scenario 3 · GTM brief</h1><div class="presenter"><b>Show:</b> ${esc(S.scenarios[2].show)}</div>` :
    `<h1>GTM brief</h1>`;
  return `<div class="head"><div class="spread"><div>${head}</div><button class="btn" id="regen">Regenerate</button></div></div>
  <div class="flow">${[["Raw sources", nConv + " conversations"], ["Quarantined", b.quarantined.length + " utterance"], ["Model extracts", (b.evidence.length + b.rejected.length) + " mentions"],
    ["Rejected", b.rejected.length + " unsupported"], ["Evidence records", b.evidence.length], ["Window compare", b.window_days + "d vs prior " + b.window_days + "d"], ["Claims", b.claims.length + " cited"]]
    .map(([k, v], i, a) => `<div class="f"><div class="chip ${k === "Rejected" && b.rejected.length ? "warn" : "ok"}"><b>${k}</b>${esc(v)}</div>${i < a.length - 1 ? '<span class="arrow">→</span>' : ""}</div>`).join("")}</div>
  <div class="grid2"><div class="stack"><div class="panel"><h2>Brief ${esc(b.id)}</h2><div class="claims">
    ${b.claims.map((c) => `<button class="claim ${S.briefClaim === c.id ? "on" : ""}" data-claim="${esc(c.id)}">${esc(c.text)}
      <div class="meta">${c.citations.length} citation(s) · click to see the sources</div></button>`).join("")}</div>
    <p class="muted small">Numbers and sentences come from code. The model (${esc(b.model.provider)}) only finds mentions, and each one must quote the source verbatim.</p></div>
    <div class="panel"><h2>Kept out of the brief</h2>
      ${b.quarantined.map((q) => `<div class="cite"><div class="src">${badge("QUARANTINED")} <span class="mono">${esc(q.conversation_id)}</span> utterance ${q.utterance_index}</div>“${esc(q.text)}”<div class="muted small">${esc(q.reason)}</div></div>`).join("")}
      ${b.rejected.map((r) => `<div class="cite"><div class="src">${badge("REJECTED")} <span class="mono">${esc(r.conversation_id)}</span></div>“${esc(r.mention.quote)}”<div class="muted small">${esc(r.reason)}</div></div>`).join("")}
      ${!b.quarantined.length && !b.rejected.length ? `<div class="muted">Nothing rejected.</div>` : ""}
      <p class="muted small">Inject a fabricated quote from <a href="#/failures">Failure injection</a> → unsupported_brief_claim.</p></div></div>
  <div class="panel" id="cites">${citations(b)}</div></div>`;
}
function citations(b) {
  const c = b.claims.find((x) => x.id === S.briefClaim);
  if (!c) return `<div class="empty">Select a claim to see the conversations behind it.</div>`;
  const ev = b.evidence.filter((e) => c.citations.includes(e.id));
  const hl = (q) => esc(q).replace(new RegExp(esc(c.competitor), "g"), `<mark>${esc(c.competitor)}</mark>`);
  return `<h2>Sources for: ${esc(c.text)}</h2>${ev.map((e) => `<div class="cite ${e.window === "current" ? "cur" : ""}">
    <div class="src"><b>${esc(e.source_type)}</b> <span class="mono">${esc(e.conversation_id)}</span> ${esc(e.title)} · ${esc(e.date)} · ${badge(e.window === "current" ? "last " + b.window_days + "d" : "prior " + b.window_days + "d")}
    · speaker: ${esc(e.speaker_role)}${e.reason ? " · reason: " + esc(e.reason) : ""}</div>“${hl(e.quote)}”
    <div class="muted small mono">evidence ${esc(e.id)} · account ${esc(e.account_id)}</div></div>`).join("")}`;
}
function bindBrief() {
  document.querySelectorAll("[data-claim]").forEach((el) => el.onclick = () => {
    S.briefClaim = el.dataset.claim;
    document.querySelectorAll("[data-claim]").forEach((x) => x.classList.toggle("on", x === el));
    $("#cites").innerHTML = citations(S.brief);
  });
  const r = $("#regen"); if (r) r.onclick = () => safe(async () => { await call("POST", "/briefs/generate"); route(); });
}

// ------------------------------------------------------------------ hardest failure
async function viewFailureStory() {
  const r = S.lastScenario && S.lastScenario.scenario === 6 ? S.lastScenario : await call("POST", "/demo/scenarios/6");
  const recs = (list, after) => list.filter((x) => x.kind !== "revert").map((x) => {
    const wrong = ["associate_contact", "create_task"].includes(x.kind) && !x.reverted;
    return `<div class="rec"><span class="k">${esc(x.id)}</span><span class="${x.reverted ? "strike" : ""}">${esc(x.kind)} ${esc(x.contact || x.owner || "")}${x.company ? " → " + esc(x.company) : ""}</span>
      ${x.reverted ? badge("reverted", "") : wrong ? badge("STILL LIVE: WRONG", "bad") : badge("ok", "ok")}</div>`;
  }).join("");
  return `<div class="head"><h1>Scenario 6 · Hardest failure: a correction that fixed the future but not the past</h1>
    <p class="presenter">${esc(r.summary)} Found while writing adversarial tests for this reference build, not in production.
    Full write-up: <a href="${REPO}/blob/main/docs/FAILURE_POSTMORTEM.md" target="_blank" rel="noopener">FAILURE_POSTMORTEM.md</a>.</p></div>
  <div class="flow">${["Chris Walker card delivered", "Seller accepts", "CRM: contact → Redwood, task created", "Seller: wrong person", "Exclusion + rerun = SUPPRESS", "CRM still wrong?"]
    .map((t, i, a) => `<div class="f"><div class="chip ${i === 5 ? "warn" : "ok"}"><b>${i + 1}</b>${t}</div>${i < a.length - 1 ? '<span class="arrow">→</span>' : ""}</div>`).join("")}</div>
  <div class="grid-eq ba">
    <div class="panel before"><h2>Before the fix</h2><div class="muted small">${esc(r.before.source)}</div>
      <h3>CRM after the correction</h3>${recs(r.before.crm_after_correction, false)}
      <p><b class="err">${r.before.wrong_records_left.length} wrong records left in the system of record.</b> The rerun said SUPPRESS, so the dashboard looked fine.</p></div>
    <div class="panel after"><h2>After the fix</h2><div class="muted small">${esc(r.after.source)}</div>
      <h3>Correction effects</h3><ul class="small">${r.after.correct_effects.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>
      <h3>CRM after the correction</h3>${recs(r.after.crm_after_correction, true)}
      <p><b style="color:var(--ok)">${r.after.wrong_records_left.length} wrong records left.</b> Rerun outcome: ${badge(r.after.rerun_outcome)}</p>
      <a href="#/decision/${esc(r.decision_id)}">Open the live decision and its inspector →</a></div>
  </div>
  <div class="panel" style="margin-top:16px"><h2>Regression tests</h2><ul class="mono small">${r.regression_tests.map((t) => `<li>${esc(t)}</li>`).join("")}</ul></div>`;
}

// ------------------------------------------------------------------ lists
async function viewSlack() {
  const d = await call("GET", "/data");
  const msgs = d.slack_messages;
  return `<div class="head"><h1>Seller inbox (simulated Slack)</h1><p class="presenter">Slack is only the delivery surface. The decision exists before and without it.</p></div>
  ${msgs.length ? `<div class="stack">${msgs.slice().reverse().map((m) => `<div class="slack"><div class="slack-top"><span>DM to ${esc(m.channel)}</span><span class="mono">ts ${esc(m.ts)} · key ${esc(m.metadata.gde_key)}</span></div>
    <div class="slack-msg"><div class="avatar">GS</div><div><div class="slack-name">GTM Signals <span class="app">APP</span></div>
    <div class="blk"><div class="hd">Former champion joined ${esc(m.blocks.account)}</div><div>${esc(m.blocks.why_now)}</div>
    <div class="fld"><b>Next best action</b>${esc(m.blocks.next_best_action)}</div>
    <div><a href="#/decision/${esc(m.blocks.decision_id)}">Open decision ${esc(m.blocks.decision_id)}</a></div></div></div></div></div>`).join("")}</div>`
    : `<div class="empty">No messages yet. Run scenario 1, 4 or 5.</div>`}`;
}
async function viewDecisions() {
  const list = await call("GET", "/decisions");
  return `<div class="head"><h1>Decisions</h1><p class="presenter">Every evaluation, including the ones that sent nothing.</p></div>
  ${list.length ? `<div class="panel tablewrap"><table><thead><tr><th>Decision</th><th>Run</th><th>Person</th><th>New company</th><th>Outcome</th><th>Play</th><th>State</th></tr></thead><tbody>
  ${list.map((d) => `<tr class="click" data-href="#/decision/${esc(d.id)}"><td class="mono">${esc(d.id)}</td><td class="mono">${esc(d.run_id)}</td><td>${esc(d.person)}</td><td>${esc(d.account)}</td>
    <td>${badge(d.outcome)}</td><td class="mono">${esc(d.play || "—")}</td><td>${badge(d.state)}</td></tr>`).join("")}</tbody></table></div>`
    : `<div class="empty">No decisions yet. Pick a scenario.</div>`}`;
}

async function viewReliability() {
  const r = await call("GET", "/reliability");
  const tiles = [["Failed workflows", r.failed_workflows.length], ["Held (retryable)", r.held.length], ["Deliveries retried", r.retries.length],
    ["Identity / ownership reviews open", r.review_queue.length], ["Duplicate events suppressed", r.duplicates_suppressed],
    ["Unsupported claims rejected", r.unsupported_claims_rejected], ["Content quarantined", r.content_quarantined],
    ["Invalid transitions rejected", r.invalid_transitions_rejected], ["Stale signals suppressed", r.stale_signals_suppressed]];
  return `<div class="head"><h1>Reliability</h1><p class="presenter">Counts since the last reset. No uptime percentages: this is a demo, and these are real counters from this session.</p></div>
  <div class="tiles">${tiles.map(([k, v]) => `<div class="tile ${v ? "alert" : ""}"><div class="v">${v}</div><div class="k">${k}</div></div>`).join("")}</div>
  <div class="grid-eq"><div class="stack">
    <div class="panel"><h2>Provider health</h2><table><tbody>${Object.entries(r.provider_health).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${badge(v.status)}</td><td class="muted">${v.recent_errors} recent errors</td></tr>`).join("")}</tbody></table></div>
    <div class="panel"><h2>Held and failed runs</h2>${[...r.held, ...r.failed_workflows].map((x) => `<div class="rec"><span class="k">${esc(x.id)}</span>${badge(x.state)}${x.state === "HELD" ? `<button class="btn sm" data-retry="${esc(x.id)}">Retry</button>` : ""}</div>`).join("") || `<div class="muted">none</div>`}</div>
    <div class="panel"><h2>Retries</h2>${r.retries.length ? `<table><thead><tr><th>Outbox</th><th>Kind</th><th>Status</th><th>Attempts</th><th>Last error</th></tr></thead><tbody>${r.retries.map((x) => `<tr><td class="mono">${esc(x.id)}</td><td>${esc(x.kind)}</td><td>${badge(x.status)}</td><td>${x.attempts}</td><td>${esc(x.last_error || "")}</td></tr>`).join("")}</tbody></table>` : `<div class="muted">none</div>`}</div>
  </div><div class="panel"><h2>Recent audit events</h2><div class="tablewrap"><table><tbody>${r.recent_audit.map((a) => `<tr><td class="mono">${a.seq}</td><td class="mono">${esc(a.kind)}</td><td class="mono small">${esc(a.run_id || "")}</td><td class="small">${esc(JSON.stringify(a.detail))}</td></tr>`).join("")}</tbody></table></div></div></div>`;
}
function bindReliability() {
  document.querySelectorAll("[data-retry]").forEach((b) => b.onclick = () => safe(async () => { const d = await call("POST", `/runs/${b.dataset.retry}/retry`); go(`#/decision/${d.id}`); }));
}

async function viewFailures() {
  const f = await call("GET", "/demo/failures");
  return `<div class="head"><h1>Failure injection</h1></div>
  <div class="demo-banner">DEMO ONLY · disabled when the service runs with demo=False (tests/test_reliability.py::test_fault_injection_disabled_outside_demo)</div>
  <p class="presenter">Each button resets the world, injects one failure into the baseline flow, and shows what the system did.</p>
  <div class="inj">${Object.entries(f.injections).map(([k, v]) => `<button data-inject="${esc(k)}"><b>${esc(k)}</b><span>${esc(v)}</span></button>`).join("")}</div>
  <div id="inj-out" style="margin-top:16px"></div>`;
}
function bindFailures() {
  document.querySelectorAll("[data-inject]").forEach((b) => b.onclick = () => safe(async () => {
    const r = await call("POST", `/demo/failures/${b.dataset.inject}`);
    const rel = r.reliability;
    $("#inj-out").innerHTML = `<div class="panel"><div class="spread"><h2>${esc(r.injection)}</h2><span class="demo-tag">DEMO ONLY</span></div>
      <p class="muted" style="margin-top:0">${esc(r.description)}</p><ol class="steps">${r.steps.map((s) => `<li>${esc(s.what)}<div class="r">${esc(s.result)}</div></li>`).join("")}</ol>
      <div class="row" style="margin-top:10px">${r.decision_id ? `<a class="btn" href="#/decision/${esc(r.decision_id)}">Open decision trace</a>` : ""}<a class="btn" href="#/reliability">Reliability panel</a></div>
      <div class="muted small" style="margin-top:8px">duplicates suppressed ${rel.duplicates_suppressed} · held ${rel.held.length} · retries ${rel.retries.length} · reviews ${rel.review_queue.length} · unsupported claims rejected ${rel.unsupported_claims_rejected} · invalid transitions ${rel.invalid_transitions_rejected}</div></div>`;
    refreshChrome();
  }));
}

const DATA_TABS = ["accounts", "people", "employment", "champion_evidence", "opportunities", "conversations", "signals", "plays", "decisions", "feedback", "identity_exclusions", "suppressions", "crm_records", "slack_messages"];
async function viewData(tab) {
  S.dataTab = tab || S.dataTab;
  const d = await call("GET", "/data");
  const rows = d[S.dataTab] || [];
  const cell = (v) => v === null || v === undefined ? `<span class="muted">—</span>` : typeof v === "object" ? `<span class="mono small">${esc(JSON.stringify(v).slice(0, 160))}${JSON.stringify(v).length > 160 ? "…" : ""}</span>` : esc(v);
  let body;
  if (S.dataTab === "conversations") {
    body = rows.map((c) => `<div class="cite"><div class="src"><b>${esc(c.type)}</b> <span class="mono">${esc(c.id)}</span> ${esc(c.title)} · ${esc(c.date)} · ${esc(c.account_id)}</div>
      ${c.utterances.map((u) => `<div><span class="muted small">${esc(u.speaker)} (${esc(u.role)}):</span> ${esc(u.text)}</div>`).join("")}</div>`).join("");
  } else if (!rows.length) {
    body = `<div class="empty">Empty. Operational tables fill as you run scenarios.</div>`;
  } else {
    const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))].filter((c) => c !== "blocks");
    body = `<div class="tablewrap"><table><thead><tr>${cols.map((c) => `<th>${c === "_why" ? "why this record exists" : esc(c)}</th>`).join("")}</tr></thead><tbody>
      ${rows.map((r) => `<tr>${cols.map((c) => `<td>${cell(r[c])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  return `<div class="head"><h1>Data explorer</h1><p class="presenter">A small dataset where every record exists for a scenario or an evaluation case. Synthetic; no employer data.</p></div>
  <div class="subtabs">${DATA_TABS.map((t) => `<button data-dt="${t}" class="${t === S.dataTab ? "on" : ""}">${t} (${(d[t] || []).length})</button>`).join("")}</div>
  <div class="panel">${body}</div>`;
}
function bindData() { document.querySelectorAll("[data-dt]").forEach((b) => b.onclick = () => go(`#/data/${b.dataset.dt}`)); }

function viewArchitecture() {
  const base = "../docs/diagrams/";
  const ds = [["a-system", "A · System architecture"], ["b-decision-boundary", "B · Decision boundary: rules, model, human"],
    ["c-feedback-loop", "C · Feedback loop"], ["d-champion-resolution", "D · Champion resolution"]];
  return `<div class="head"><h1>Architecture</h1><p class="presenter">Diagrams are Mermaid source in <span class="mono">docs/diagrams/</span>, exported to SVG.</p></div>
  <div class="stack arch">${ds.map(([f, t]) => `<div class="panel"><h2>${t}</h2><img src="${base}${f}.svg" alt="${t}" loading="lazy"></div>`).join("")}</div>`;
}

document.addEventListener("click", () => { const m = $("#correct-menu"); if (m) m.hidden = true; });
boot().catch((e) => {
  $("#loading-step").innerHTML = `<span class="err">Could not start the demo: ${esc(e.message)}</span>`;
  $("#loading-note").innerHTML = `Fallbacks: run it locally with <span class="mono">make demo</span>, or see the screenshots in the <a href="${REPO}#readme">README</a>.`;
});
