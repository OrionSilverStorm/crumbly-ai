# Crumbly — non-happy demo

Use **Confirmation mismatch — recommended**. It is the strongest failure-path demonstration because the agent completes the routine recovery autonomously, catches a consequential supplier error, refuses to accept it and brings the owner one safe recommendation.

## What happens

1. Millers Supply cancels tomorrow’s flour delivery.
2. Crumbly calculates the same 160 kg shortage and orders 7 × 25 kg from Borough Mill.
3. Borough Mill confirms only **6 bags** and reduces the total from £165 to £144.
4. Crumbly compares the confirmation field by field and does **not** accept it.
5. Six bags provide 150 kg, leaving a **10 kg shortfall** that affects Alder Hotel’s order.
6. Crumbly finds a qualifying **1 × 25 kg** Harrow early-van top-up arriving at **04:45** for **£26**.
7. The combined cost is **£170**, below the £250 incident limit, and every rule passes.
8. You click **Approve top-up**. Crumbly places the second PO, checks its confirmation and restores all three bakes.

## How to run it

1. Open <http://127.0.0.1:8000>.
2. Click **Demo workspace**.
3. Select **Confirmation mismatch — recommended**.
4. Click **Start Confirmation mismatch — recommended**.
5. Let the agents work until the red **Needs your decision** state appears.
6. Open the incident. Crumbly should take you to **Needs you** automatically.
7. Point out the agreed-versus-confirmed table: 7 bags agreed, 6 confirmed.
8. Point out the visible 10 kg shortfall and affected customer.
9. Show the three options, then click **Approve top-up** on the recommended Harrow card.
10. Wait for the Harrow confirmation and finish on **Summary**, showing all three bakes covered.

## 45-second narration

“Here is what happens when a supplier changes the deal after we order. Borough Mill agreed to seven bags, but its confirmation contains only six. Crumbly checks every confirmation field, so it refuses to treat that as success.

“Six bags leave us ten kilos short—enough to affect Alder Hotel’s production slot. The agent has already recalculated the alternatives and found a one-bag top-up on Harrow’s early van, arriving at 04:45. The combined cost is £170 and the top-up passes every purchasing rule.

“Because the original confirmation changed, Crumbly keeps the owner in control. I approve the recommended top-up; it sends the second purchase order once, verifies the reply, and restores coverage for all three bakes.”

## Judge points to emphasise

- This is not a prewritten error message: the shortfall, affected customer, top-up and new total are recomputed from state.
- A mismatch is never silently accepted.
- The owner sees three real choices: top up, request correction, or accept and adjust.
- Approval does not bypass safety checks; the top-up is rebuilt and revalidated immediately before execution.
- Purchase-order idempotency prevents a duplicate if the step is retried.

## Safe fallback

If time is short, stop at the red decision screen. That screen alone proves confirmation verification, impact recalculation, replanning and human-in-the-loop escalation. Keep a previously completed `short_confirm` incident open in another tab for the resolved result.

