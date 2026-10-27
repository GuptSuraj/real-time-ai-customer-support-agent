# Knowledge policy reconciliation

Reviewed before indexing on 27 October 2026 against FastAPI eligibility, confirmation, staff refund decisions, seeded catalog/policies, and handoff behavior. The corpus contains 23 policies, six FAQs and four generic product guides.

## Corrections applied to the supplied documents

| Topic | Supplied content | Reconciled content and authority |
| --- | --- | --- |
| Return window | 14 calendar days in policy 007 and FAQ 003 | **30 days**, matching `eligibility()` and the saved return policy |
| Standard shipping | 3–7 business days in policy 003 and FAQ 002 | **3–5 business days**, matching the existing saved shipping policy; an estimate, never a promised order date |
| Express shipping | Illustrative 1–3 day express option | No implemented express selection/upgrade tool; offer a confirmed support ticket without promising service |
| Return conditions | Unused condition, packaging and accessories presented as eligibility conditions | The API checks delivered status, 30-day window, all products' `returnable` flags and no existing return. Physical condition/packaging require human discussion; the API does not inspect them |
| Exclusions | Illustrative final-sale/digital/perishable category exclusions | The live catalog's `returnable` flag is authoritative; seeded Everyday Earbuds are excluded. No additional category flags or checks are claimed |
| Refund prerequisites | Generic “applicable rules” | A return marked **received** and **no existing refund** are required, plus customer verification/confirmation and human approval |
| Refund states | Historical failure omitted | Include the seeded `failed` refund; current state always comes from the authenticated backend |
| Refund timelines | No guaranteed date | Retain that limitation and clarify the saved policy's illustrative 5–7 business day bank estimate. There are no real payments |

The numeric business values were extracted into `support_api/business_rules.py` and reused by the existing handlers and seed text. Their values and allowed business actions were preserved.

## Other reviewed boundaries

- Whole-order returns only; partial returns and exchanges need human review.
- Customers cannot authorize a write by saying “yes.” Exact portal confirmation and one-use verification remain required.
- The challenge expires after 120 seconds; proposals and verified authority expire after 300 seconds.
- A refund request is not an approval, processing event or real bank payment.
- Cancellation, address changes, warranty replacement, checkout promotions, inventory lookup, and shipping upgrades have no autonomous tool. Conditional general advice does not introduce those capabilities.
- Prices and account/order/refund facts come from live backend records. Generic headphone/charger/monitor/care guides do not imply those products exist in the catalog or have a particular specification.
- Human escalation waits 60 seconds, permits a single assigned representative, stops AI authority on takeover, and does not silently restart AI after staff disconnect.
- Transcripts may arrive late; audio recording is off in the application. The documentation does not promise an unimplemented deletion or retention SLA.

## Indexing gate

`knowledge/policy_review.json` records reviewed document checksums, the policy contract, and an AST fingerprint of the business handlers and seed rules. Indexing validates the complete corpus **before any embedding request**, then validates it again before publication.

A changed, added, removed or malformed document, a duplicate document ID, or an altered backend rule blocks indexing until reviewed. Additional numeric checks reject the known return-window/shipping contradictions. These checks are not a general semantic theorem prover: arbitrary new policy prose still requires source review. Do not use the review command as an automatic approval step in CI or ingestion.

The active index is an immutable, reviewed snapshot. Editing files does not silently alter live answers. Failed or unreviewed reindexing leaves the prior snapshot active. Backend-rule drift disables answers from stale indexed policies until review and reindexing.
