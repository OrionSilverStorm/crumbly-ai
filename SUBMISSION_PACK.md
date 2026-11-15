# Crumbly — submission and judging pack

## Submission configuration

- **Track:** Autonomous Agents
- **Bounties:** Databricks and Best use of Linkup
- **Project:** Crumbly
- **Tagline:** When a delivery fails, Crumbly protects tomorrow’s bakes.
- **Repository:** <https://github.com/OrionSilverStorm/crumbly-ai>
- **Video:** maximum two minutes; use `VIDEO_SCRIPT.md`

The [official rules](https://imperial-ai-hackathon.devpost.com/rules) weight Autonomous Agents as: does it work 30%, technical depth 25%, usefulness 20%, video and answers 15%, originality 10%. Optimise the video for visible completion first, not architecture slides.

## Ready-to-paste Devpost copy

### One-line description

Crumbly is an autonomous ingredient-recovery agent that turns a cancelled bakery delivery into a safe, confirmed replacement before production starts.

### Short description

When a supplier lets an independent bakery down, Crumbly reads the disruption, calculates which bakes are at risk, researches and contacts replacements, follows up on incomplete quotes, applies the owner’s purchasing rules, places a safe order and checks the confirmation field by field.

### Inspiration

Independent bakeries supply cafés, shops and hotels on tight morning schedules, but most do not have a procurement team. A single cancelled flour delivery can force an owner to search inboxes, call suppliers and recalculate production while the clock is already running. We wanted to automate that stressful recovery without giving an AI unrestricted purchasing power.

### What it does

Crumbly manages a supply incident from the first cancellation message through to restored production coverage:

1. It matches the disruption to a supplier and purchase order.
2. It calculates the shortage and identifies the customer commitments at risk.
3. It contacts approved suppliers and researches new ones with Linkup.
4. It extracts structured offers, detects missing fields and follows up automatically.
5. It recalculates time-phased production coverage whenever an offer changes.
6. It validates product, pack size, quantity, arrival, total cost, approval status and duplicate protection in deterministic code.
7. It orders automatically only inside the owner’s rules; exceptions require approval.
8. It matches the supplier confirmation field by field and replans if anything changed.

The owner can replay the evidence trail and ask a constrained help assistant what happened, what it cost and whether tomorrow’s production is safe.

### How we built it

Crumbly uses a Python/FastAPI orchestration service, React interface and three specialist agents sharing one persistent incident record. Models are used for interpretation; deterministic code controls arithmetic and consequential actions.

Databricks provides the governed operational-data design. We created Delta tables and Unity Catalog functions for shortage calculation, affected orders, approved alternatives, time-phased coverage and supplier reliability. The live Databricks acceptance check reproduces the demo decision: 200 kg required minus 40 kg on hand equals 160 kg short, rounded to seven 25 kg bags. The recording uses a local Postgres mirror of the same schema and function semantics for repeatability; Databricks deployment, Lakebase, `ai_query` and model serving are implemented paths but are not claimed as live in the recorded run.

Linkup is the external research layer. Structured live search discovers candidates; the supplier’s own page is fetched and compared with an independent search excluding that domain. Claims are stored with URLs and retrieval time, then marked confirmed, conflicting or unverified. Queries are constructed only from ingredient, pack size and postcode area, and an automated privacy test prevents customer names, recipes and order IDs from reaching Linkup.

The execution service performs seven deterministic checks, ranks qualifying offers by reliability and cost, creates idempotent purchase orders and matches confirmations. An append-only event log supports crash recovery, replay and MLflow tracing.

### Challenges

- Separating probabilistic interpretation from safe purchasing actions.
- Recalculating coverage against individual bake times instead of treating stock as one daily total.
- Handling incomplete multi-message quotes without inventing missing values.
- Demonstrating live web research while keeping customer and recipe data private.
- Making the demo repeatable without pretending controlled supplier replies are real businesses.

### Accomplishments

- Four end-to-end scenarios: normal recovery, short confirmation and top-up, new-supplier approval, and owner rejection with split ordering.
- A complete awkward supplier exchange: incomplete quote, automatic follow-up, completed quote, order and confirmation.
- Field-by-field confirmation matching and idempotent purchase orders.
- Live Linkup discovery plus two-source claim verification.
- Databricks Delta tables and Unity Catalog functions verified against the core acceptance case.
- Twenty-one automated tests covering business rules, privacy, safety, crash resume and full scenarios.

### What we learned

Useful autonomy comes from combining flexible interpretation with narrow permissions and deterministic validation. The strongest part of an agent is not how many model calls it makes; it is whether it can finish the task, explain its evidence, recover after failure and stop when policy requires a person.

### What is next

Next we would connect bakery inventory and POS systems, run the operational state on Lakebase, move reply parsing and traces fully into Databricks, pilot Gmail transport with controlled supplier accounts, and validate willingness to pay with independent bakeries. Longer term, Crumbly could learn supplier fulfilment patterns while keeping every purchasing rule owner-controlled.

### Built with

Python, FastAPI, React, TypeScript, PostgreSQL, Databricks SQL Warehouse, Delta Lake, Unity Catalog functions, MLflow tracing, Linkup Search and Fetch APIs, Pydantic, Gmail IMAP/SMTP adapter, pytest.

## Honest claims sheet

| Area | Safe statement | Do not claim |
|---|---|---|
| End-to-end workflow | The complete incident workflow is real application code and passes four controlled scenarios. | Every external service is live in the recording. |
| Databricks | Delta tables and UC functions are deployed and the acceptance query was verified live. The UI run uses a local semantic mirror. | The recorded UI is currently executing every decision in Databricks. |
| Linkup | Search and supplier-page verification run live, with cached results available for repeatability. | Linkup establishes live price, stock or delivery availability. |
| Email | Gmail IMAP/SMTP transport is implemented; the recording uses a deterministic inbox and scripted replies. | The demo emails real suppliers. |
| Model | The architecture supports Databricks/OpenAI-compatible models; the recording uses deterministic extraction. | A live foundation model interpreted every recorded email. |
| Tracing | Agent steps generate MLflow trace IDs in the local experiment store. | Recorded traces are stored in Unity Catalog. |
| Supplier research | Published claims are verified from two web paths and then confirmed by a controlled quote exchange. | Web claims alone authorize a purchase. |

## Six-minute judge Q&A

Answer the question first, then give one piece of evidence. Keep each answer under 30 seconds unless the judge asks for depth.

### “Why is this an agent rather than a workflow?”

It observes changing messages and state, chooses the next investigation, uses multiple tools, waits and follows up, replans when evidence changes, and continues until production coverage is restored. The safety-critical checks remain deterministic by design.

### “What actually runs autonomously?”

Detection, shortage calculation, supplier outreach, Linkup research, missing-field follow-up, chase and drop timers, offer validation, ranking, in-policy ordering and confirmation checking. A new supplier, overspend or mismatch stops for owner approval.

### “What did Databricks do?”

We deployed the operational Delta tables and governed Unity Catalog functions used for shortage, affected orders, coverage and reliability, and verified the 160 kg acceptance case in the live SQL warehouse. The video UI uses the matching local implementation for repeatability, which we disclose on screen.

### “Is Databricks central if the UI uses a mirror?”

Yes to the data and decision design, but we are not claiming the recorded request path is fully hosted there. The governed functions are the contract the agents call; the remaining production step is switching the configured warehouse and deploying the app after service credentials are stable.

### “What did Linkup do beyond ordinary search?”

It returns structured supplier candidates and source URLs, fetches the candidate’s own page, then runs an independent search excluding that domain. Crumbly compares individual claims and keeps conflicts rather than collapsing them into a confident summary.

### “How do you prevent hallucinated purchases?”

Extracted fields are schema-validated, missing values remain missing, arithmetic is Decimal-based, and seven deterministic checks gate execution. The assistant cannot order, email or change rules; it can only prepare a confirmation card.

### “What happens if the confirmation is different?”

It is never silently accepted. In our short-confirmation scenario, six bags creates a mismatch decision; Crumbly validates a one-bag early-van top-up, or the owner can request correction or accept the visible shortfall.

### “How do you protect private business data?”

Linkup queries are built only from ingredient, pack size and postcode area. A test checks every outgoing query for customer names, order IDs and recipe data. New suppliers never receive customer information.

### “How reliable is it?”

Twenty-one automated tests pass, including four end-to-end scenarios, idempotency and crash resume. Before submission we run the happy scenario three times and retain a successful two-minute recording as the judged artefact.

### “What is original?”

The closest category is general restaurant procurement software. Crumbly is narrower: emergency ingredient recovery tied to the exact production commitments and bake deadlines that a failed delivery threatens.

### “Why reliability before lowest price?”

A cheap delivery arriving after the first bake has no operational value. Reliability is calculated from delivery history, then cost breaks ties among offers that actually protect production.

### “Would a bakery trust automatic purchasing?”

Only within rules the owner set: approved products and suppliers, delivery window and a per-incident limit. New suppliers and exceptions always require a click, and every action has an evidence trail.

### “What is mocked?”

The bakery data and supplier replies are fictional and controlled, the recorded inbox is in memory, and extraction is deterministic. Live Linkup research and the Databricks acceptance check are real; the interface labels the active modes.

### “What would you build next?”

First, real inventory and POS integrations and a small bakery pilot. Technically, Lakebase state, live Gmail transport, Databricks model serving and UC-hosted MLflow traces are the next deployment steps.

## Final-round live demo plan

If selected for the Autonomous Agents final:

1. Keep a finished `happy` incident open before going on stage.
2. Start a fresh `happy` run only after the app, network and Linkup cache are checked.
3. Narrate the same sequence as the video, but spend more time on the incomplete quote and evidence log.
4. Keep the finished incident available in another tab as an immediate fallback.
5. Have the Databricks acceptance result open in a separate tab.
6. If asked for a failure path, show the already-completed `short_confirm` incident or run it only if time permits.
7. Never choose `new_supplier_wins` while Linkup mode is live; that controlled scenario requires the fixture and the UI deliberately disables it.

The exact failure-path clicks and 45-second narration are in `NON_HAPPY_DEMO.md`.

## Submission checklist

### Product proof

- [ ] `make test` reports 21 passed.
- [ ] `make build` succeeds.
- [ ] Three clean `happy` runs completed.
- [ ] One `short_confirm` run completed and the one-bag top-up resolved it.
- [ ] Final video checked from beginning to end with headphones.
- [ ] Video is under two minutes and any speed-up is labelled.
- [ ] Finished incident remains open on the presentation laptop.

### Devpost requirements

- [ ] Project submitted before **12:00 GMT on Sunday 15 November 2026**.
- [ ] Track is **Autonomous Agents**.
- [ ] Bounties are **Databricks** and **Best use of Linkup**.
- [ ] Public repository URL added.
- [ ] Video URL added and publicly viewable without requesting access.
- [ ] Every team member added to the Devpost project.
- [ ] Team-member answer contains each full name, Luma signup email and university email.
- [ ] All submission text saved before the deadline.
- [ ] Public GitHub’s last commit remains before 12:00.

### Presentation bag

- [ ] Laptop and charger.
- [ ] Backup video stored locally as well as online.
- [ ] Headphones or confirmed room-audio plan.
- [ ] Browser notifications disabled.
- [ ] Mobile hotspot available.
- [ ] Databricks proof tab open but secrets hidden.
- [ ] No `.env`, tokens, email passwords or terminal history visible.

## Deadline plan

Work in this order; stop adding product features once the judged video is safe.

1. **Reliability block — 45 minutes:** run `happy` three times and `short_confirm` once. Write down duration and any failure.
2. **Recording rehearsal — 20 minutes:** read `VIDEO_SCRIPT.md` aloud twice while navigating a completed incident.
3. **Record — 45 minutes:** capture up to three takes. Keep the first complete take as insurance.
4. **Edit and export — 45 minutes:** remove dead time, add only the approved captions, export 1080p.
5. **Quality check — 15 minutes:** watch the exported file without touching the timeline; confirm audio, legibility, duration and honest wording.
6. **Devpost — 30 minutes:** paste the copy, add members, repository, track, two bounties and video.
7. **Submission buffer — at least 60 minutes:** submit early, open the public submission in a private/incognito window and verify every link.
8. **After submission:** no code or video changes count. Prepare the six-minute Q&A and keep the completed app open for judges.

