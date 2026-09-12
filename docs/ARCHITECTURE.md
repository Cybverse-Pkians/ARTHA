# Architecture

## The pipeline, in order

The ordering in `orchestrator.py` is itself a safety property.

```
transactions (CDC)
      │
      ▼
┌──────────────────┐  narration → typed values. The only place a narration
│ Bharat Ontology  │  string is read. Attacker-controlled text stops here.
└────────┬─────────┘
         ▼
┌──────────────────┐  income typing, recurrence, committed outflow.
│ Feature builder  │  Consent-scoped: a revoked purpose removes the feature.
└────────┬─────────┘
         ▼
┌──────────────────┐  1. FRAUD or DISTRESS?  Before anything is considered
│    Sentinel      │     for sale. A system that ranks products first will,
└────────┬─────────┘     on some unlucky day, offer a loan to someone mid-scam.
         ▼
┌──────────────────┐  2. Has anything materially changed?  Silence is a
│  Moment Engine   │     valid output and the common one.
└────────┬─────────┘
         ▼
┌──────────────────┐  3. Amount, tenure, EMI date by risk-adjusted lifetime
│  Profitability   │     value — subject to the Twin clearing the structure.
└────────┬─────────┘
         ▼
┌──────────────────┐  4. Six-month Monte-Carlo, with and without the
│ Financial Twin   │     obligation, stress-tested. Affordability is a
└────────┬─────────┘     property of a specific EMI on a specific date.
         ▼
┌──────────────────┐  5. Six checks. Can override everything above it.
│ Suitability Gate │     ACT · SUPPRESS · PROTECT · VERIFY
└────────┬─────────┘
         ▼
┌──────────────────┐  6. One object, two renderings that cannot diverge.
│ Decision Object  │     Regulator trace ── and ── one spoken sentence.
└────────┬─────────┘
         ▼
┌──────────────────┐  7. The model phrases it. Every numeral must be
│   AI Firewall    │     grounded or the response is blocked.
└──────────────────┘
```

## Why each boundary exists

**Ontology as a security boundary.** A payer controls their own VPA display name
and remarks string, so a narration is attacker-controlled text arriving through
the bank's own trusted transaction feed. The defence is structural: free text
enters `ontology/narration.py` and only enum members, numbers and tokenised keys
leave it. The injection scanner raises alerts and populates the audit log; it is
not load-bearing, because a filter that is load-bearing will eventually be
bypassed.

**The profile as a consent boundary.** Engines receive a `CustomerProfile` and
never reach past it to raw transactions. That is what makes purpose limitation
enforceable rather than aspirational — if a purpose is revoked, the feature is
absent and the engine cannot use what it cannot see.

**The Gate as a conduct boundary.** It runs last and can override the ranking
entirely. Every check runs even after one has failed, because a trace that stops
at the first failure cannot demonstrate that the remaining constraints were
evaluated.

**The firewall as a blast-radius boundary.** The model receives tokenised
references and pre-rendered amounts. Money enters its numeric ground in *rupees*,
never paise, because a paise figure is something it could only have invented —
and admitting both forms widens the ground enough that a hallucinated number can
land within tolerance of a legitimate one.

## Data model

Money is integer **paise** everywhere except inside the Twin's Monte-Carlo
interior, which converts at the boundary. Float rupees drift, and a drifting EMI
is a compliance incident rather than a rounding curiosity.

The single most consequential field is `CustomerProfile.income_type`. It scales
the Twin's safe buffer, changes which shock scenarios apply, determines whether a
monthly EMI is the right instrument at all, and discounts the Sentinel's stress
uplift for profiles where income-less months are normal. Its misclassification is
the system's top named limitation, which is why the human override is a parameter
of the classify call rather than an administrative afterthought.

## Deployment

Side-car, not replacement. Transactions are consumed through change-data-capture;
nothing is written back except decisions and audit records. The decision service
is stateless and horizontally scalable; the feature store and event bus scale
independently. Deployment is inside the bank's own VPC or data centre, which is
what makes the data-localisation posture true rather than asserted.

Three integration modes: a drop-in SDK widget inside the bank's existing app, a
REST API for the bank's own front end, and batch scoring for existing campaign
and collections systems.

## Known architectural gaps

- The capability broker's single-use nonce set is in-process. Behind a load
  balancer it needs a shared store with a TTL. This is the one place the module
  must change to run multi-node, and it is stated in the docstring.
- The tokenisation vault keeps its reverse map in memory. A deployment backs it
  with an HSM or managed key service; the interface is already shaped for that.
- `ArthaEngine` holds customer state in a process dictionary. Production reads
  from the feature store.
- The ML models named in report §7 and §8 (gradient-boosted ranker with uplift,
  PD model, supervised Sentinel classifier, narration n-gram classifier) have
  defined interfaces and injection points but are not trained. The shipped
  decision path is rules plus simulation.
