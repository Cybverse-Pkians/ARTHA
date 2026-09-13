# API notes

Interactive documentation is at `/docs` once the service is running. This file
covers the endpoints that are not self-explanatory.

## Decision flow

### `POST /seed`
Ingest one synthetic archetype. The fastest way to get a populated demo.

```json
{ "archetype": "salaried_stable", "months": 14 }
```

Archetype keys: `GET /archetypes`.

### `POST /ingest`
Ingest a real transaction history. `gender` is accepted but is a **fairness slice
only** — it is removed before the profile the engines see is constructed, so it
cannot enter a decision. `income_type_override` is the human correction path of
report §5.1 and wins unconditionally.

### `POST /decide`
The main endpoint. Returns the Decision Object in both renderings, plus the Twin
paths for charting, the Key Fact Statement, the Sentinel assessment, the
Intervention Ladder where one applies, and the privacy ledger.

The `outcome` field is one of:

| Outcome | Meaning |
|---|---|
| `ACT` | speak to the customer |
| `SUPPRESS` | say nothing — **this is a success, not a failure** |
| `PROTECT` | stress or fraud detected; assist, never sell |
| `VERIFY` | step-up authentication or human review first |

`suppressed_candidates` feeds two surfaces: the customer's "what we are not
offering, and why" panel, and the product-design feedback loop that tells the
bank which terms most often cause suitability rejections.

### `POST /render`
Submit a candidate model phrasing for firewall validation. This is how a language
model participates at all — it proposes text and the firewall decides whether the
customer ever hears it. Returns the outcome, the text actually delivered (the
template on any block), and the model context, which is the *only* thing a model
is given.

## Journey

`POST /journey/slot` is the confidence-gated slot filler. Below the confidence
floor the assistant re-asks rather than guessing; any amount at or above ₹50,000
is read back regardless of confidence, because ASR confidence is a statement
about acoustics and not about consequence.

`POST /journey/video-kyc/preflight` runs the thirty-second readiness test before
a slot is booked. Every blocker carries a remedy.

`GET /journey/consent/{token}` and `POST /journey/consent` drive the consent
screen. Revocation is real: the purpose goes dead and the associated features are
excluded at inference time.

## Banker

| Endpoint | Notes |
|---|---|
| `GET /banker/queue` | Ranked at the bank's actual daily contact capacity, not at a score threshold. `excluded` lists customers for whom contact changes nothing |
| `GET /banker/correlated` | Employer-level payroll delay clusters. The demo lowers the cluster threshold so a small synthetic portfolio produces a visible alert |
| `GET /banker/arrears` | The book by Special Mention Account stage, with days past due and the evidence per account. Read-only: it runs no decision, so opening it cannot change what any customer is offered |
| `POST /banker/demo/reset` | Rebuilds the seeded demo portfolio. Demo affordance only — it discards contact history, Recovery-Mode records and the audit log, which no deployment would do |
| `GET /banker/fairness` | Benefit distribution by slice, plus the published exclusion list |
| `GET /banker/suppression` | Suppressions as a success metric, and which constraint blocked each offer |
| `GET /banker/dual-ledger` | Customer benefit and bank value, from the same decision log |
| `POST /banker/override-income-type` | Human correction; re-ingests with the label pinned and writes a `HUMAN_OVERRIDE` audit record naming the actor |
| `POST /banker/intervention-response` | Records acceptance or decline. **Declining is explicitly not a risk signal** |

## Audit

`GET /audit/evidence/{token}` builds the evidence pack. Stress observations and
interventions are separate sections because the question a supervisor asks is not
only "what did you do" but "what did you know, and when".

`GET /audit/verify` re-walks the hash chain.

## A note on every response

Responses that contain figures carry a `data_provenance` field. Everything this
service returns is generated from synthetic data and is illustrative.
