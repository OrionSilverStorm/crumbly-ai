# Claude Code handoff — Crumbly

## Read this first

Deadline is noon Europe/London. Preserve the working demo. Do not print, copy, overwrite or commit `.env`; it contains live credentials and is ignored by Git.

Current branch: `kushh/improvements`.

Start by running:

```bash
git status --short --branch
make test
make build
```

Read `README.md` and `DEMO_RUNBOOK.md`. Keep changes small, tested and reversible. Do not replace the deterministic demo path with an unverified external integration immediately before submission.

## Verified state

- 20 tests pass.
- All four local scenarios work end to end.
- Happy path with live Linkup completes in roughly 40 seconds at 60× demo time.
- Linkup now fetches the actual supplier source page before verifying claims.
- Help assistant handles status, cost, supplier choice, glossary and safety questions using read-only tools; action cards still require an owner click.
- One-click **Start demo (reset + trigger)** is in the Demo workspace menu.
- Databricks Free Edition is configured locally in ignored `.env`:
  - SQL warehouse connected.
  - `crumbly.bakery` catalog/schema created.
  - Delta tables and UC functions created and seeded.
  - Live acceptance check returned 200 needed, 40 on hand, 160 short, 7 bags.
- The Databricks PAT is short-lived. If authentication fails, ask the user to create a new token; never display it.

## Priority roadmap

### P0 — submission safety (do these first)

1. Run the happy scenario three times using the one-click launcher. Record duration and any failure.
2. Run `short_confirm` once and verify the six-bag mismatch plus one-bag top-up.
3. Record a clean two-minute backup video using `DEMO_RUNBOOK.md`.
4. Prepare the public repository/submission text and confirm the final Git commit is before noon.

### P1 — strongest remaining technical proof

1. Create or select a Databricks model-serving endpoint only if Free Edition exposes one without payment.
2. Test reply parsing with `LLM_PROVIDER=databricks` without changing the demo default.
3. If stable, run `backend/dbx/pipeline.sql` with the correct endpoint and show `silver_quotes_batch`.
4. Deploy as a Databricks App only after the existing local demo and backup video are safe.

### P2 — integrations if time remains

1. Lakebase resource and migrations.
2. Gmail IMAP/SMTP accounts and app passwords.
3. MLflow traces in UC.
4. Optional dashboard.

These are lower priority than a reliable video and submission. The current demo is honest about its deterministic inbox and local state while proving live Linkup and Databricks UC separately.

## Guardrails

- Never send real supplier emails; demo suppliers route to the scripted supplier mailbox.
- Never include customer names, order IDs or recipe data in Linkup queries.
- The assistant must not directly place orders, send emails or change rules.
- Purchase order and email sends must remain idempotent.
- Do not delete or reset user work. Do not rewrite Git history.
- After each change, run the narrow test plus the full suite before committing.

## Useful commands

```bash
make test
make build
make dev
make reset SCENARIO=happy
make send-cancellation
make reset SCENARIO=short_confirm
```

The local app is <http://127.0.0.1:8000>. The live Databricks connection is intentionally configured only in `.env`.
