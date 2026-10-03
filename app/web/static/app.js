"use strict";
// Operator console for the DocIntel API. Plain DOM APIs, no framework and no build step.
// All server data (including document text, which is untrusted) is rendered via textContent,
// never innerHTML, so content inside a PDF cannot inject markup or script into this page.

const state = { docs: [], selectedId: null, health: null };

const $ = (sel, root = document) => root.querySelector(sel);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function chip(value) {
  const text = value === null || value === undefined ? "—" : String(value);
  return el("span", { class: `status-chip s-${text.toLowerCase()}` }, text);
}

function pct(value) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "—";
}

function confBar(value) {
  const width = typeof value === "number" ? Math.max(0, Math.min(1, value)) * 100 : 0;
  const fill = el("span");
  fill.style.width = `${width}%`;
  return el("span", {}, el("span", { class: "conf-bar" }, fill), pct(value));
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function fmtValue(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  return String(value);
}

let toastTimer = null;
function toast(message, isError = false) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add("hidden"), isError ? 7000 : 3500);
}

// ------------------------------------------------------------------ API client

async function api(path, options = {}, retried = false) {
  const headers = new Headers(options.headers || {});
  const key = sessionStorage.getItem("docintel_api_key");
  if (key) headers.set("X-API-Key", key);
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    options.body = JSON.stringify(options.json);
  }
  const response = await fetch(path, { ...options, headers });
  // In public demo mode, visitors without an API key get a session cookie (scoped to their own
  // workspace) on demand; outside demo mode the endpoint does not exist and the 401 stands.
  if (response.status === 401 && !key && !retried) {
    const session = await fetch("/demo/session", { method: "POST" });
    if (session.ok) return api(path, options, true);
  }
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    if (body && body.error) message = `${body.error.type}: ${body.error.message}`;
    else if (body && Array.isArray(body.detail)) message = body.detail.map((d) => d.msg).join("; ");
    throw new Error(message);
  }
  return body;
}

async function withBusy(button, fn) {
  const label = button ? button.textContent : "";
  if (button) {
    button.disabled = true;
    button.textContent = "Working…";
  }
  try {
    return await fn();
  } catch (err) {
    toast(err.message, true);
    return undefined;
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = label;
    }
  }
}

// ------------------------------------------------------------------ health

async function loadHealth() {
  const badge = $("#provider-badge");
  try {
    const health = await api("/health");
    state.health = health;
    badge.textContent = health.mock_mode ? `mock mode · ${health.providers.llm}` : health.providers.llm;
    badge.className = `badge ${health.mock_mode ? "mock" : "live"}`;
    badge.title = Object.entries(health.providers).map(([k, v]) => `${k}: ${v}`).join("\n");
  } catch (err) {
    badge.textContent = "API unreachable";
    badge.className = "badge down";
    badge.title = err.message;
  }
}

// ------------------------------------------------------------------ documents

async function loadDocuments() {
  try {
    state.docs = await api("/documents?limit=500");
  } catch (err) {
    toast(err.message, true);
    return;
  }
  renderDocList();
}

function renderDocList() {
  const list = $("#doc-list");
  list.replaceChildren();
  if (!state.docs.length) {
    list.append(el("li", { class: "muted small" }, "No documents yet."));
    return;
  }
  for (const doc of state.docs) {
    list.append(
      el(
        "li",
        {
          class: doc.document_id === state.selectedId ? "active" : "",
          onclick: () => selectDocument(doc.document_id),
        },
        el("span", { class: "doc-name", title: doc.filename }, doc.filename),
        el("span", {}, chip(doc.status), " ", el("span", { class: "muted small" }, doc.document_type || "unclassified")),
      ),
    );
  }
}

async function uploadFile(file) {
  if (!file) return;
  if (file.type && file.type !== "application/pdf") {
    toast("Only PDF files are accepted.", true);
    return;
  }
  const form = new FormData();
  form.append("file", file);
  try {
    const result = await api("/documents/upload", { method: "POST", body: form });
    toast(result.duplicate ? "Already uploaded — opened the existing document." : "Uploaded. Click Process to run the workflow.");
    await loadDocuments();
    await selectDocument(result.document.document_id);
  } catch (err) {
    toast(err.message, true);
  }
}

async function selectDocument(id) {
  state.selectedId = id;
  renderDocList();
  const detail = $("#detail");
  let doc;
  try {
    doc = await api(`/documents/${encodeURIComponent(id)}`);
  } catch (err) {
    toast(err.message, true);
    return;
  }
  const view = $("#tpl-detail").content.cloneNode(true);
  const f = (name) => $(`[data-f="${name}"]`, view);
  f("filename").textContent = doc.filename;
  f("meta").textContent = `${doc.document_id} · ${doc.page_count} page(s) · ${(doc.size_bytes / 1024).toFixed(1)} KB · sha256 ${doc.sha256.slice(0, 12)}…`;
  f("status").append(chip(doc.status));
  f("type").textContent = doc.document_type || "—";
  f("conf").append(doc.classification ? confBar(doc.classification.confidence) : "—");
  f("method").textContent = doc.text_extraction_method || "—";
  if (doc.security_flags.length) {
    f("flags").append(
      el("div", { class: "flags" }, el("strong", {}, "Security flags: "), doc.security_flags.join(", ")),
    );
  }

  for (const tab of view.querySelectorAll(".subtab")) {
    tab.addEventListener("click", () => switchSubtab(tab.dataset.sub));
  }
  const processBtn = $('[data-action="process"]', view);
  processBtn.addEventListener("click", () =>
    withBusy(processBtn, async () => {
      const result = await api(`/documents/${encodeURIComponent(id)}/process`, { method: "POST" });
      const note = result.review_reasons.length ? ` — review: ${result.review_reasons.join(", ")}` : "";
      toast(`Workflow finished: ${result.status}${note}`, result.status === "FAILED");
      await loadDocuments();
      await selectDocument(id);
      refreshReviewCount();
    }),
  );
  const askForm = $('[data-action="ask"]', view);
  askForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = askForm.question.value.trim();
    const target = $('[data-f="answer"]', detail);
    withBusy(askForm.querySelector("button"), async () => {
      const answer = await api(`/documents/${encodeURIComponent(id)}/ask`, { method: "POST", json: { question } });
      target.replaceChildren(renderAnswer(answer));
      refreshReviewCount();
    });
  });

  detail.replaceChildren(view);
  await Promise.all([renderFields(id, doc), renderAuditAndWorkflow(id, doc)]);
}

function switchSubtab(name) {
  for (const tab of document.querySelectorAll(".subtab")) tab.classList.toggle("active", tab.dataset.sub === name);
  for (const pane of document.querySelectorAll(".subview")) pane.classList.toggle("hidden", pane.dataset.subView !== name);
}

async function renderFields(id, doc) {
  const pane = $('[data-sub-view="fields"]');
  let data;
  try {
    data = await api(`/documents/${encodeURIComponent(id)}/extractions`);
  } catch (err) {
    pane.replaceChildren(el("p", { class: "muted" }, err.message));
    return;
  }
  const latest = data.latest;
  if (!latest) {
    const hint = doc.status === "INGESTED" ? "Click Process to classify and extract fields." : "No extraction for this document.";
    pane.replaceChildren(el("p", { class: "muted" }, hint));
    return;
  }
  const header = el(
    "div",
    { class: "answer-meta" },
    el("span", {}, "Overall confidence: ", pct(latest.overall_confidence)),
    el("span", {}, "Model: ", `${latest.provider}:${latest.model_name}`),
    el("span", {}, "Prompt: v", latest.prompt_version),
    latest.is_mock ? el("span", { class: "badge mock" }, "mock output") : null,
    latest.corrected_by_review_id ? el("span", { class: "badge live" }, "corrected by reviewer") : null,
  );
  const rows = latest.entities.map((e) =>
    el(
      "tr",
      {},
      el("td", { class: "mono" }, e.name),
      el("td", {}, fmtValue(e.value), e.alternatives.length ? el("div", { class: "muted small" }, "alternatives: ", e.alternatives.map(fmtValue).join(", ")) : null),
      el("td", {}, confBar(e.confidence)),
      el("td", {}, chip(e.validation_status)),
      el(
        "td",
        { class: "evidence" },
        e.evidence
          ? [
              el("span", { class: e.evidence.verified ? "ok" : "bad" }, e.evidence.verified ? "✓ verified" : "✗ not found in source"),
              e.evidence.page_number ? ` · p.${e.evidence.page_number}` : "",
              el("div", { class: "mono" }, `“${e.evidence.snippet}”`),
            ]
          : "—",
        e.messages.length ? el("div", { class: "small" }, e.messages.join(" · ")) : null,
      ),
    ),
  );
  const table = el(
    "table",
    {},
    el("thead", {}, el("tr", {}, ["Field", "Value", "Confidence", "Validation", "Evidence"].map((h) => el("th", {}, h)))),
    el("tbody", {}, rows),
  );
  const issues = latest.validation_issues.length
    ? [
        el("h3", {}, "Validation issues"),
        el(
          "ul",
          {},
          latest.validation_issues.map((i) => el("li", {}, chip(i.severity), " ", el("span", { class: "mono" }, i.rule), " — ", i.message)),
        ),
      ]
    : [];
  const review = latest.requires_review
    ? el("div", { class: "notice" }, "Routed to human review: ", latest.review_reasons.join(", "))
    : null;
  pane.replaceChildren(header, review || "", el("div", { class: "table-wrap" }, table), ...issues);
}

function summarizeDetails(details) {
  if (!details) return "";
  if (details.from || details.to) return `${details.from || "start"} → ${details.to}`;
  return Object.entries(details)
    .filter(([, v]) => v !== null && typeof v !== "object")
    .slice(0, 3)
    .map(([k, v]) => `${k}=${v}`)
    .join(" · ");
}

async function renderAuditAndWorkflow(id, doc) {
  const auditPane = $('[data-sub-view="audit"]');
  const wfPane = $('[data-sub-view="workflow"]');
  let data;
  try {
    data = await api(`/documents/${encodeURIComponent(id)}/audit`);
  } catch (err) {
    auditPane.replaceChildren(el("p", { class: "muted" }, err.message));
    wfPane.replaceChildren(el("p", { class: "muted" }, err.message));
    return;
  }
  const events = data.events;
  auditPane.replaceChildren(
    events.length
      ? el(
          "ul",
          { class: "timeline" },
          events.map((ev) =>
            el(
              "li",
              {},
              el("span", { class: "when" }, fmtTime(ev.timestamp)),
              el("span", { class: "mono" }, ev.event_type),
              el("span", { class: "muted" }, ev.actor),
              el("span", { class: "muted small" }, summarizeDetails(ev.details)),
              el("span", { class: "muted small mono", title: ev.event_hash }, `#${ev.sequence} ${ev.event_hash.slice(0, 10)}…`),
            ),
          ),
        )
      : el("p", { class: "muted" }, "No audit events."),
  );

  const transitions = events.filter(
    (ev) => ev.event_type === "workflow.transition" && ev.workflow_id && ev.workflow_id === doc.current_workflow_id,
  );
  wfPane.replaceChildren(
    transitions.length
      ? el(
          "ul",
          { class: "timeline" },
          transitions.map((ev) =>
            el(
              "li",
              {},
              el("span", { class: "when" }, fmtTime(ev.timestamp)),
              el("span", {}, chip(ev.details.from || "start"), " → ", chip(ev.details.to)),
              el("span", { class: "muted" }, ev.details.reason || ""),
            ),
          ),
        )
      : el("p", { class: "muted" }, "Not processed yet."),
  );
}

// ------------------------------------------------------------------ answers

function renderAnswer(a) {
  const meta = el(
    "div",
    { class: "answer-meta" },
    el("span", {}, "Confidence: ", pct(a.confidence)),
    el("span", {}, "Groundedness: ", pct(a.groundedness)),
    el("span", {}, "Model: ", `${a.model_provider}:${a.model_name}`),
    el("span", {}, "Embeddings: ", a.embedding_model),
    a.is_mock ? el("span", { class: "badge mock" }, "mock output") : null,
  );
  const notices = [];
  if (a.refused) notices.push(el("div", { class: "notice" }, "Refused: ", a.refusal_reason || "insufficient evidence"));
  if (a.requires_review) notices.push(el("div", { class: "notice" }, "Sent to human review", a.review_id ? ` (${a.review_id})` : ""));
  for (const w of a.warnings) notices.push(el("div", { class: "notice" }, w));
  const citations = a.citations.map((c, i) =>
    el(
      "div",
      { class: "citation" },
      el("div", { class: "small muted" }, `[${i + 1}] page ${c.page_number ?? "?"} · score ${c.retrieval_score.toFixed(3)} · ${c.document_id}`),
      el("div", { class: "snippet" }, c.text_snippet),
    ),
  );
  return el(
    "div",
    { class: "answer" },
    el("div", { class: "answer-text" }, a.answer),
    meta,
    ...notices,
    citations.length ? el("h3", {}, "Citations") : null,
    ...citations,
  );
}

// ------------------------------------------------------------------ reviews

async function refreshReviewCount() {
  try {
    const data = await api("/reviews?status=pending&limit=500");
    const pill = $("#review-count");
    pill.textContent = String(data.count);
    pill.classList.toggle("hidden", data.count === 0);
  } catch {
    /* badge is informational only */
  }
}

async function loadReviews() {
  const status = $("#review-status").value;
  const list = $("#review-list");
  let data;
  try {
    data = await api(`/reviews?limit=200${status ? `&status=${status}` : ""}`);
  } catch (err) {
    list.replaceChildren(el("p", { class: "muted" }, err.message));
    return;
  }
  if (!data.items.length) {
    list.replaceChildren(el("p", { class: "muted" }, "Nothing here. Documents that fail a confidence, validation or evidence check land in this queue."));
    return;
  }
  list.replaceChildren(...data.items.map(renderReview));
}

function docName(id) {
  const doc = state.docs.find((d) => d.document_id === id);
  return doc ? doc.filename : id || "—";
}

// Pre-fills the corrections editor with only the values a reviewer is being asked to check.
function correctionTemplate(r) {
  const out = r.original_output || {};
  if (r.target_type === "answer") return { answer: (out.answer && out.answer.answer) || "" };
  const entities = (out.extraction && out.extraction.entities) || [];
  const flagged = {};
  for (const e of entities) if (e.validation_status !== "valid") flagged[e.name] = e.value;
  return flagged;
}

function renderReview(r) {
  const pending = r.status === "pending";
  const comment = el("input", { placeholder: "Comment (optional)", maxlength: 2000 });
  const corrections = el("textarea", { placeholder: '{"field_name": "corrected value"}', spellcheck: "false" });
  corrections.value = JSON.stringify(correctionTemplate(r), null, 2);
  const decide = (action, button) =>
    withBusy(button, async () => {
      const body = { comment: comment.value || null };
      if (action === "correct") {
        try {
          body.corrections = JSON.parse(corrections.value);
        } catch {
          throw new Error("Corrections must be a JSON object.");
        }
      }
      await api(`/reviews/${encodeURIComponent(r.review_id)}/${action}`, { method: "POST", json: body });
      toast(`Review ${action === "correct" ? "corrected" : action + "d"}.`);
      await Promise.all([loadReviews(), refreshReviewCount(), loadDocuments()]);
    });

  const actions = pending
    ? el(
        "div",
        {},
        el("div", { class: "row" }, comment),
        corrections,
        el(
          "div",
          { class: "row" },
          el("button", { class: "ok", onclick: (e) => decide("approve", e.currentTarget) }, "Approve"),
          el("button", { class: "danger", onclick: (e) => decide("reject", e.currentTarget) }, "Reject"),
          el("button", { onclick: (e) => decide("correct", e.currentTarget) }, "Submit corrections"),
        ),
      )
    : el(
        "div",
        { class: "small muted" },
        `Resolved ${fmtTime(r.resolved_at)} by ${r.reviewer_id || "—"}`,
        r.reviewer_comment ? ` — “${r.reviewer_comment}”` : "",
      );

  return el(
    "div",
    { class: "review" },
    el(
      "div",
      { class: "review-head" },
      el("div", {}, el("strong", {}, docName(r.document_id)), " ", el("span", { class: "muted small" }, `${r.target_type} · ${r.review_id}`)),
      chip(r.status),
    ),
    el("div", { class: "reasons" }, r.reasons.map((x) => el("span", { class: "status-chip s-warning" }, x))),
    r.details.length ? el("ul", { class: "small" }, r.details.map((d) => el("li", {}, d))) : null,
    el("div", { class: "small muted" }, `model ${r.model_version} · prompts ${r.prompt_version} · created ${fmtTime(r.created_at)}`),
    actions,
  );
}

// ------------------------------------------------------------------ corpus Q&A

function setupCorpus() {
  const select = $("#corpus-type");
  for (const t of ["invoice", "bank_statement", "income_statement", "balance_sheet", "fund_summary"]) {
    select.append(el("option", { value: t }, t));
  }
  $("#corpus-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const question = $("#corpus-question").value.trim();
    const type = select.value;
    const body = { question, ...(type ? { filters: { document_type: type } } : {}) };
    withBusy(event.target.querySelector("button"), async () => {
      const answer = await api("/ask", { method: "POST", json: body });
      $("#corpus-answer").replaceChildren(renderAnswer(answer));
      refreshReviewCount();
    });
  });
}

// ------------------------------------------------------------------ wiring

function switchView(name) {
  for (const tab of document.querySelectorAll(".tab")) tab.classList.toggle("active", tab.dataset.view === name);
  for (const view of document.querySelectorAll(".view")) view.classList.toggle("hidden", view.id !== `view-${name}`);
  if (name === "reviews") loadReviews();
}

function setupUpload() {
  const zone = $("#dropzone");
  const input = $("#file-input");
  input.addEventListener("change", () => {
    uploadFile(input.files[0]);
    input.value = "";
  });
  zone.addEventListener("dragover", (e) => {
    e.preventDefault();
    zone.classList.add("over");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("over");
    uploadFile(e.dataTransfer.files[0]);
  });
}

function setupSettings() {
  const input = $("#api-key");
  input.value = sessionStorage.getItem("docintel_api_key") || "";
  input.addEventListener("change", () => {
    if (input.value) sessionStorage.setItem("docintel_api_key", input.value);
    else sessionStorage.removeItem("docintel_api_key");
    loadDocuments();
    refreshReviewCount();
  });
  $("#settings-toggle").addEventListener("click", () => $("#settings").classList.toggle("hidden"));
}

document.addEventListener("DOMContentLoaded", () => {
  for (const tab of document.querySelectorAll(".tab")) tab.addEventListener("click", () => switchView(tab.dataset.view));
  $("#refresh-docs").addEventListener("click", loadDocuments);
  $("#review-status").addEventListener("change", loadReviews);
  setupUpload();
  setupSettings();
  setupCorpus();
  loadHealth();
  loadDocuments();
  refreshReviewCount();
});
