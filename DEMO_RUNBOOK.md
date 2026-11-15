# Crumbly demo runbook

## The one-line pitch

Crumbly is an autonomous recovery agent for small bakeries: when a supplier lets them down, it works out the production impact, researches and negotiates replacements, applies the owner's rules, places the safe order and verifies the confirmation.

## Two-minute judge demo

### 0:00–0:20 — The problem

Say: “A small bakery does not have a procurement team. One cancelled delivery at 4am can put tomorrow's customer orders at risk.”

Open **Demo workspace**, choose `happy`, then click **Start demo (reset + trigger)**. The cancellation email is inserted into the repeatable demo inbox and the agents begin immediately.

### 0:20–0:50 — Understand

Open `INC-0042` and show **Impact**.

- 200 kg required for tomorrow.
- 40 kg on hand.
- 160 kg short.
- Pack rounding produces 7 × 25 kg bags.
- Three customer commitments are at risk, each with a bake deadline.

Say: “These numbers come from the same Unity Catalog functions that we ran live in Databricks.”

### 0:50–1:15 — Investigate and coordinate

Show **Sourcing**, then **Quotes**.

- Approved suppliers are contacted first.
- Linkup discovers and verifies a new supplier using live web sources.
- The Linkup query contains only ingredient, pack size and postcode area—never customer or recipe data.
- Borough Mill's first reply is incomplete, so Crumbly asks for the delivery charge and exact arrival time.

Say: “This is not a chatbot choosing from a list. It researches, follows up and changes state as new evidence arrives.”

### 1:15–1:40 — Decide and execute

Show **Decision** and **Confirmation**.

- Reliability ranks before price.
- Borough Mill passes all seven rules at £165 and 05:00, within the £250 autonomy limit.
- PO-0087 is sent once.
- The confirmation is checked field by field; all three bakes regain coverage.

Say: “Anything outside the owner's rules stops for approval. New suppliers always require approval.”

### 1:40–2:00 — Explainability

Open **Ask Crumbly** and press **What happened?**

The answer should say Millers Supply cancelled, the shortage was 160 kg, 175 kg is arriving at 05:00 and all three bakes are covered. Point out the “actions need your click” safety boundary and the link back to the evidence screen.

Close with: “Crumbly turns a stressful inbox problem into a verified recovery plan before the baker has opened the shop.”

## Safe preflight

Run these from the repository root:

```bash
make test
make build
make dev
```

Then visit <http://127.0.0.1:8000>, use **Start demo (reset + trigger)** and wait about 40 seconds for the live-Linkup happy path.

Before recording:

1. Close unrelated browser tabs and notifications.
2. Use the `happy` scenario.
3. Confirm the footer says “Live Linkup research”.
4. Confirm the final summary shows 160 kg, 175 kg, 7 bags, £165 and 05:00.
5. Ask the assistant “What happened?” and “How much will this cost?”.
6. Record one clean backup video even if the live presentation is planned.

## If something external is slow

- Linkup: keep `LINKUP_CACHE=1` after one successful live run, then reset and record again.
- Databricks: show the successful `crumbly.bakery` SQL result and use the local mirror for the UI; the SQL semantics and acceptance figures are tested identically.
- Network: all four scenarios are deterministic with the bundled Linkup fixture, and all 21 tests are offline. With live Linkup, use `happy`, `short_confirm` or `owner_rejects`; the UI deliberately disables `new_supplier_wins` because a live search may discover a supplier the scripted responder does not represent.

## Submission wording

**Autonomy:** The system detects, understands, investigates, coordinates, decides, executes and verifies without a linear hard-coded script. Owner intervention is policy-driven.

**Databricks:** Delta tables hold operational evidence; Unity Catalog table functions are the agents' governed tools; the live acceptance check reproduces the 160 kg shortage and seven-bag decision.

**Linkup:** Live search discovers suppliers and source-page fetching verifies individual claims. Queries deliberately exclude customer, order and recipe data.

**Safety:** Values are parameterised, model output is schema-validated, purchase orders are idempotent, rules are explicit, and assistant actions require a separate owner click.
