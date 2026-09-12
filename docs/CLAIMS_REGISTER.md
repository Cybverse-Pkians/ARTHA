# Claims register

Report §11.2, carried into the codebase. A project of this kind can easily blur
the line between what is established and what is designed, so the distinction is
stated explicitly and the code is annotated to match.

## 1. Standard industry and regulatory concepts used as framing

**Status: widely documented. To be cited from current circulars before final
submission rather than quoted from memory.**

- Special Mention Account classification by days past due
- The treatment of restructuring granted for borrower financial difficulty under
  RBI's stressed-asset framework
- The Key Fact Statement requirement, and RBI digital-lending expectations
  including the cooling-off period and consent for credit-limit increases
- Payment-data localisation
- The Digital Personal Data Protection Act, 2023
- The Account Aggregator framework; DigiLocker, CKYC, UPI and NPCI
- Bhashini and AI4Bharat models

Where these appear in code they are marked. `intervention/ladder.py` carries a
`verify_against_circular` flag on every rung, and `language/kfs.py` carries a
`REGULATORY_NOTE` constant that is returned with every generated statement.

Special Mention Account classification is implemented in `core/asset_class.py`.
The day bands are reproduced there from secondary understanding, not quoted from
a circular, and every `AssetClassification` carries the caveat as data so no
surface can render a classification without it. Deliberately **not** modelled,
because modelling them badly would be worse than omitting them: provisioning
percentages, CRILC reporting (which applies at an aggregate-exposure threshold
retail loans do not reach), NPA sub-classification into doubtful and loss, and
the upgrade rules for an account already classified as an NPA. Claims about
those should not be made from this codebase.

## 2. Every quantitative figure

**Status: illustrative only. Generated from the synthetic dataset. Not measured
results, and labelled as such wherever shown.**

This includes every rupee amount, EMI figure, tenure, probability, count, lead
time and precision figure produced anywhere in this system — the correlated
employer alert, all dashboard counts, all Twin projections, all resilience
scores, and every figure in the demo.

Enforcement in code:

- `synth/generator.py` is the only data source; there is no path that reads real
  transaction data.
- API responses carry a `data_provenance` field.
- The console renders a `<Provenance>` banner on every page that shows a number.

## 3. Design hypotheses

**Status: stated as hypotheses. Each is testable and each is written as
something to be measured, not as a finding.**

| Hypothesis | How it would be tested |
|---|---|
| The suitability constraint binds on only a minority of customers | Holdout with guardrail metrics reported alongside benefit metrics |
| Early intervention yields a net positive return after regulatory cost | Migration rate into stressed categories, measured against a holdout |
| Shifting an EMI date is ordinarily a servicing change rather than a concession granted for financial difficulty | **Legal and supervisory confirmation required before relying on this.** It is the load-bearing assumption of the Intervention Ladder |
| Restructured customers generate higher lifetime value than defaulted ones | Cohort comparison over a full cycle |
| Refused customers who borrow elsewhere do worse than matched approved customers | The refusal study of report §7.8, using bureau and consented AA data — a natural experiment requiring no randomisation into harmful credit |

## 4. Known limitations

Carried from report §11.3, all of them visible in the code rather than only in
prose.

- **Censored training data.** Repayment is observed only for approved customers,
  and the Gate worsens this censoring by construction. Mitigations: standard
  corrections, plus the refusal study.
- **Scarce distress labels.** The hybrid supervised/unsupervised design in
  `engines/sentinel.py` is the mitigation, and the unsupervised layer scores
  against the customer's *own* baseline rather than a population average.
- **Income-detection dependency.** Misclassifying seasonal income as irregular
  would wrongly deny credit to the very population this concerns. The human
  override is a first-class parameter of
  `ontology/income_type.classify()`, wins unconditionally, and is recorded as
  the method in the decision log.
- **Language coverage.** Support across Indian languages is an integration
  claim. The stub provider in `language/adapters.py` deliberately does not fake
  translation, so a demo cannot accidentally present invented Tamil as real.

## 5. What is NOT claimed

- That any model here is trained on real data. The gradient-boosted ranker,
  PD-uplift model and supervised Sentinel classifier described in report §7 and
  §8 are **specified with their interfaces and not trained**; the shipped
  decision path uses deterministic rules and simulation, which is why it is
  auditable today.
- That the system has detected a single real instance of fraud or distress.
- That any figure shown has been validated against a real portfolio.
