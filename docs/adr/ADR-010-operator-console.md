# ADR-010: Static operator console

- Status: Accepted
- Date: 2026-10-03

## Context

The platform was API-only. Reviewers and evaluators had to drive it with `curl` or the OpenAPI
page, which hides the parts that matter most to them: the evidence behind each extracted value,
the citations behind each answer, and the review queue. A UI was wanted for demos and for the
human-review workflow, without turning a backend reference implementation into a front-end
project.

## Decision

Serve a small static console from the API at `/ui` (`app/web/static/`: one HTML file, one CSS
file, one JavaScript file).

- **No framework and no build step.** Nothing to install, nothing to compile in CI or Docker,
  and the files ship inside the `app` package.
- **API client only.** The console calls the same public endpoints as any other client, so it
  adds no behaviour, no server-side state and no extra authorisation path. With API-key auth
  enabled, the key is sent as `X-API-Key` and kept in `sessionStorage` for the tab only.
- **Untrusted content is rendered as text.** Document text, snippets and answers can contain
  attacker-controlled strings (see the prompt-injection samples). The console builds DOM nodes
  and sets `textContent`; it never uses `innerHTML`. A test fails if `innerHTML`, `outerHTML`,
  `insertAdjacentHTML` or `document.write` appear in the script.
- **Strict headers on `/ui` only.** `Content-Security-Policy` with `default-src 'self'`, no
  inline script or style elements, `frame-ancestors 'none'`, plus `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. API responses are
  unchanged.
- **Optional.** `DOCINTEL_UI_ENABLED=false` removes the routes for API-only deployments.

## Alternatives considered

| Option | Why not |
|---|---|
| Next.js / React SPA | a second toolchain (Node, bundler, lockfile, CI job) for a handful of screens; worth it for a multi-user product, not for an operator console in a backend reference project |
| Streamlit / Gradio | a second Python server process with its own state model; harder to put behind the same auth, CSP and request-ID middleware |
| Server-rendered templates (Jinja) | mixes presentation into route handlers and duplicates the API's response shaping |

## Consequences

- The console is deliberately limited: single user, no saved views, no keyboard shortcuts, lists
  capped at the API's 500-row page. A production front end would be a separate application
  consuming the same API.
- Because it only uses the public API, anything shown in the console is reproducible with
  `curl`, and API changes that break the console are caught by the same contract.
