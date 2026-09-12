from datetime import date
from artha.ontology.enrich import DEFAULT_PIPELINE
from artha.synth.generator import DEFAULT_GENERATOR
from artha.core.money import format_inr
from collections import Counter

as_of = date(2026, 9, 12)
for key in ("thin_file_woman", "agricultural"):
    token, txns = DEFAULT_GENERATOR.generate(key, months=14, end=as_of)
    enr = DEFAULT_PIPELINE.run(txns, as_of=as_of)
    print(f"\n=== {key}: got {enr.income.income_type.value} conf={enr.income.confidence}")
    for k, v in sorted(enr.income.features.items()):
        print(f"    {k:28} {v}")
    print("    evidence:")
    for e in enr.income.evidence:
        print(f"      - {e}")
    from artha.core.types import Direction, INCOME_CATEGORIES
    credits = [x for x in enr.enriched if x.direction is Direction.CREDIT and x.category in INCOME_CATEGORIES]
    print(f"    income credits={len(credits)} by category:",
          dict(Counter(c.category.value for c in credits)))
    months = sorted({(c.value_date.year, c.value_date.month) for c in credits})
    print(f"    income months ({len(months)}):", [f"{y}-{m:02d}" for y, m in months])
    print("    detected series:")
    for s in enr.series:
        print(f"      {s.direction.value:6} {s.category.value:18} period={s.period_days:3} "
              f"dom={s.day_of_month} n={s.occurrences} median={format_inr(s.median_amount_paise)}")
