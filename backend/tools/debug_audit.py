import hashlib, json
from datetime import date
from artha.audit.log import AuditLog
from artha.consent.manager import ConsentManager
from artha.core.money import rupees
from artha.engines.twin import FinancialTwin
from artha.gate.conduct import EmpathyCalendar, NudgeBudget
from artha.gate.fairness import FairnessMonitor
from artha.gate.recovery import RecoveryMachine
from artha.orchestrator import ArthaEngine
from artha.synth.generator import ARCHETYPES, SyntheticGenerator

as_of = date(2026, 9, 12)
engine = ArthaEngine(twin=FinancialTwin(paths=200), recovery=RecoveryMachine(),
                     budget=NudgeBudget(), calendar=EmpathyCalendar(),
                     fairness=FairnessMonitor(), consent=ConsentManager(), audit=AuditLog())
arch = ARCHETYPES["stressed"]
token, txns = SyntheticGenerator().generate("stressed", months=14, end=as_of)
engine.consent.grant_defaults(token, as_of=as_of)
engine.ingest(token, txns, as_of=as_of, balance_paise=rupees(arch.opening_balance),
              age=arch.age, dependants=arch.dependants, district=arch.district,
              tenure_with_bank_months=36, on_time_emi_streak=14)
engine.decide(token, as_of=as_of)

log = engine.audit
print("records:", len(log))
prev = log.GENESIS
for r in log.records:
    body = {"seq": r.seq, "record_type": r.record_type.value,
            "customer_token": r.customer_token, "at": r.at,
            "payload": r.payload, "prev_hash": r.prev_hash, "actor": r.actor}
    try:
        blob = json.dumps(body, sort_keys=True, default=str)
    except Exception as e:
        print(f"  seq {r.seq} {r.record_type.value}: SERIALISATION ERROR {e}")
        continue
    expected = hashlib.sha256(blob.encode()).hexdigest()
    chain_ok = (r.prev_hash == prev)
    hash_ok = (expected == r.hash)
    if not (chain_ok and hash_ok):
        print(f"  seq {r.seq} {r.record_type.value}: chain_ok={chain_ok} hash_ok={hash_ok}")
        if not hash_ok:
            # find which part differs by re-serialising twice
            blob2 = json.dumps(body, sort_keys=True, default=str)
            print("    serialisation stable across calls:", blob == blob2)
            print("    payload types:", {k: type(v).__name__ for k, v in list(r.payload.items())[:12]})
            # look for float weirdness
            def walk(o, path=""):
                if isinstance(o, dict):
                    for k, v in o.items(): yield from walk(v, f"{path}.{k}")
                elif isinstance(o, (list, tuple)):
                    for i, v in enumerate(o): yield from walk(v, f"{path}[{i}]")
                else:
                    yield path, o
            odd = [(p, v) for p, v in walk(r.payload)
                   if not isinstance(v, (str, int, float, bool, type(None)))]
            print("    non-JSON-native leaves:", odd[:8])
    prev = r.hash

ok, detail = log.verify()
print("verify():", ok, detail)
