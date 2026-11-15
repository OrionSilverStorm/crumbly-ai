# Crumbly — two-minute submission video

This is the primary judging asset. The first-round judges watch this video, then ask questions for six minutes. There are no slides and no live demo in that round.

## Recording setup

- Resolution: 1920×1080, browser zoom 90–100%, cursor visible.
- Record the app at <http://127.0.0.1:8000> with the `happy` scenario.
- Keep the **60× demo time** badge visible. This compresses supplier-response timers; say so aloud.
- Hide notifications, bookmarks, passwords, `.env`, terminal history and unrelated tabs.
- Record one continuous successful run first. Edit only dead time; label any additional speed-up.
- Do not add a logo intro or music. Start with the problem and product on screen.
- Export at 1080p and keep the final duration at **1:55–1:58**, never 2:00 exactly.

## Exact script and shot list

| Time | What is on screen | Say this |
|---|---|---|
| 0:00–0:12 | Crumbly home page. Open **Demo workspace**, select `happy`. | “Independent bakeries do not have procurement teams. If tomorrow’s flour delivery is cancelled, customer orders can be lost before the owner even opens the shop. Crumbly is an autonomous recovery agent for that exact moment.” |
| 0:12–0:20 | Click **Start demo (reset + trigger)**. Keep the 60× badge in frame. | “This starts one real end-to-end run. Only the bakery data and supplier replies are controlled. Business-time response delays are running sixty times faster.” |
| 0:20–0:38 | Open `INC-0042` → **Impact**. Point to 200 kg required, 40 kg available, 160 kg short, 7 bags and the three affected orders. | “Crumbly reads the cancellation, matches the purchase order and queries production. Tomorrow needs two hundred kilos; forty are available, so it calculates a one-hundred-and-sixty-kilo shortage and rounds safely to seven twenty-five-kilo bags. Three customer commitments are exposed.” |
| 0:38–0:59 | **Sourcing**. Show approved supplier threads, Linkup card, source URLs and claim statuses. | “The sourcing agent contacts approved suppliers and uses live Linkup research to find alternatives. It fetches the supplier’s own page, runs an independent search, and labels each claim confirmed, conflicting or unverified. Only ingredient, pack size and postcode reach Linkup—never customers, recipes or order IDs.” |
| 0:59–1:15 | **Quotes**. Show Borough Mill’s incomplete first response and the follow-up thread. | “Borough Mill gives a price but omits delivery cost and a precise time. Crumbly detects those missing fields and follows up. A late cheap offer is rejected because fresh coverage checks show it would not save production.” |
| 1:15–1:33 | **Decision**, then **Confirmation**. Point to seven checks, £165, 05:00, PO-0087 and field matches. | “The execution service—not a language model—checks product, quantity, timing, total cost, the owner’s limit and duplicate protection. Borough Mill passes all seven rules at one hundred and sixty-five pounds, arriving at five. The order is sent once and its confirmation is matched field by field.” |
| 1:33–1:45 | **Summary** or **Full incident log**. Show 175 kg on order and all three bakes covered. | “One hundred and seventy-five kilos are now on order while physical stock stays unchanged until receipt. All three bakes are covered, with every decision replayable.” |
| 1:45–1:53 | Briefly show Databricks workspace result: `crumbly.bakery`, 200 needed, 40 on hand, 160 short, 7 bags. | “We verified the same governed tables and Unity Catalog functions in Databricks. This run uses the local schema mirror for repeatability.” |
| 1:53–1:58 | Return to Crumbly resolved screen. | “Crumbly is emergency recovery tied to production promises—not generic procurement.” |

## On-screen captions

Use only these short captions if editing:

- `One continuous incident · supplier timers at 60×`
- `Controlled bakery data and supplier replies`
- `Live Linkup search + source verification`
- `Databricks UC functions verified live · local mirror used in this recording`
- `21 automated tests · 4 end-to-end scenarios`

Do not caption the inbox, model or local warehouse as live external services.

## Numbers that must remain consistent

- Required: **200 kg**
- On hand: **40 kg**
- Shortage: **160 kg**
- Order: **7 × 25 kg = 175 kg**
- Winning supplier: **Borough Mill**
- Goods: **£147**
- Delivery: **£18**
- Total: **£165**
- Arrival: **05:00**
- Autonomy limit: **£250 per incident**
- Result: **3 of 3 bakes covered**
- Purchase order: **PO-0087**

## If the run misbehaves while recording

1. Stop recording; do not try to rescue a visibly broken take.
2. Confirm the footer says `live Linkup research` and the scenario is `happy`.
3. Click **Start demo (reset + trigger)** again.
4. If Linkup is slow, retain the most recent successful cache and rerun with `LINKUP_CACHE=1`.
5. If the network is unavailable, record with `LINKUP_MODE=fixture` and change the narration to “controlled Linkup research fixture.” Never call the fixture live.

