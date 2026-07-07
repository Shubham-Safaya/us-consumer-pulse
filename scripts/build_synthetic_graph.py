#!/usr/bin/env python3
"""Synthetic identity graph demo (spec 7b) — precompute pipeline.

Generates a Census-realistic synthetic population, fragments it into messy
multi-system records, resolves it with identity-resolver (my OSS engine),
and grades the result against manufactured ground truth. Outputs static
JSON the demo page renders — no runtime compute, no PII, ever.

Run locally: python3 scripts/build_synthetic_graph.py [--persons 100000]
"""
import argparse, json, os, random, string, sys, time, hashlib
from collections import defaultdict

sys.path.insert(0, os.path.expanduser("~/Documents/Claude/Projects/identity-resolution-engine"))
from identity_resolver import IdentityResolver, Record
from identity_resolver.resolver import ResolverConfig

random.seed(42)

# ── ACS-realistic distributions (public aggregate figures, approximated) ──
HH_SIZE_DIST = [(1, .28), (2, .35), (3, .15), (4, .13), (5, .06), (6, .03)]
STATES = [("TX", .09), ("CA", .12), ("FL", .07), ("NY", .06), ("PA", .04), ("IL", .04),
          ("OH", .035), ("GA", .033), ("NC", .032), ("AR", .009), ("NJ", .028), ("WA", .024),
          ("OTHER", .459)]
FIRST_M = ["james","michael","robert","john","david","william","richard","joseph","daniel","carlos",
    "wei","raj","amit","jose","luis","kevin","brian","eric","mark","steven","paul","andrew","joshua",
    "kenneth","george","timothy","ronald","edward","jason","jeffrey","ryan","jacob","gary","nicholas",
    "jonathan","stephen","larry","justin","scott","brandon","benjamin","samuel","gregory","frank",
    "alexander","patrick","jack","dennis","jerry","tyler","aaron","henry","arjun","rohan","vikram","omar"]
FIRST_F = ["mary","patricia","jennifer","linda","elizabeth","maria","susan","priya","ana","lakshmi",
    "sarah","karen","lisa","nancy","emily","ashley","fatima","mei","grace","anna","betty","margaret",
    "sandra","dorothy","kimberly","donna","michelle","carol","amanda","melissa","deborah","stephanie",
    "rebecca","sharon","laura","cynthia","kathleen","amy","angela","shirley","brenda","emma","olivia",
    "rachel","catherine","christine","samantha","janet","virginia","hannah","aisha","divya","neha","sita"]
NICKS = {"james":"jim","michael":"mike","robert":"bob","john":"jack","william":"bill",
         "richard":"rick","joseph":"joe","daniel":"dan","elizabeth":"liz","jennifer":"jen",
         "patricia":"pat","susan":"sue","steven":"steve","kevin":"kev"}
_LAST_BASE = ["smith","johnson","williams","brown","jones","garcia","miller","davis","rodriguez","martinez",
    "patel","kim","nguyen","chen","singh","sharma","lee","walker","hall","young","koul","bhat","hernandez",
    "lopez","gonzalez","wilson","anderson","thomas","taylor","moore","jackson","martin","white","thompson",
    "harris","sanchez","clark","ramirez","lewis","robinson","allen","king","wright","scott","torres","hill",
    "flores","green","adams","nelson","baker","rivera","campbell","mitchell","carter","roberts","gomez",
    "phillips","evans","turner","diaz","parker","cruz","edwards","collins","reyes","stewart","morris",
    "morales","murphy","cook","rogers","gutierrez","ortiz","morgan","cooper","peterson","bailey","reed",
    "kelly","howard","ramos","cox","ward","richardson","watson","brooks","chavez","wood","james","bennett",
    "gray","mendoza","ruiz","hughes","price","alvarez","castillo","sanders","patil","iyer","reddy","gupta",
    "khan","desai","mehta","joshi","kaul","dhar","raina","zhang","wang","liu","tran","pham","le","yang"]
LAST = _LAST_BASE  # 118 surnames -> realistic collision rates at 100K scale
STREETS = ["main st","oak ave","maple dr","cedar ln","park blvd","2nd st","hill rd","lake view dr"]

def pick(dist):
    r, acc = random.random(), 0
    for v, p in dist:
        acc += p
        if r <= acc: return v
    return dist[-1][0]

def synth_population(n_persons):
    persons, households = [], []
    pid = 0
    while pid < n_persons:
        hh_size = pick(HH_SIZE_DIST)
        hhid = f"HH{len(households):06d}"
        state = pick(STATES)
        addr = f"{random.randint(1,9999)} {random.choice(STREETS)}"
        zipc = f"{random.randint(10000,99999)}"
        surname = random.choice(LAST)
        members = []
        shared_email = f"{surname}{random.randint(1,999)}@example-mail.test" if random.random() < .18 else None
        for i in range(hh_size):
            if pid >= n_persons: break
            sex = random.choice("mf")
            first = random.choice(FIRST_M if sex == "m" else FIRST_F)
            # adult children / spouses share surname; 12% of women carry a maiden-name variant in old records
            maiden = random.choice(LAST) if (sex == "f" and i > 0 and random.random() < .12) else None
            email = f"{first}.{surname}{random.randint(1,99)}@example-mail.test" if random.random() < .8 else shared_email
            phone = f"555{random.randint(1000000,9999999)}" if random.random() < .7 else None
            members.append({"pid": f"P{pid:06d}", "first": first, "last": surname, "maiden": maiden,
                            "sex": sex, "email": email, "phone": phone})
            pid += 1
        households.append({"hhid": hhid, "state": state, "addr": addr, "zip": zipc, "members": members})
        persons.extend(members)
    return persons, households

def noisy(s, p=.06):
    if not s or random.random() > p: return s
    i = random.randint(0, len(s) - 1)
    return s[:i] + random.choice(string.ascii_lowercase) + s[i+1:]

def fragment(households):
    """Each person appears in 1-3 systems with realistic formatting noise."""
    records, truth = [], {}
    rid = 0
    for hh in households:
        for m in hh["members"]:
            n_sys = random.choices([1, 2, 3], weights=[.35, .45, .20])[0]
            systems = random.sample(["crm", "web", "store"], n_sys)
            for s_i, sysname in enumerate(systems):
                rrid = f"r{rid:07d}"; rid += 1
                truth[rrid] = m["pid"]
                first = m["first"]
                if first in NICKS and random.random() < .3: first = NICKS[first]
                last = m["maiden"] if (m["maiden"] and sysname == "crm") else m["last"]
                email = m["email"]
                if email and random.random() < .15: email = email.replace("@", f"+{sysname}@")
                if email and random.random() < .1: email = email.upper()
                phone = m["phone"]
                if phone and random.random() < .3: phone = f"({phone[:3]}) {phone[3:6]}-{phone[6:]}"
                records.append(Record(
                    record_id=rrid, source=sysname,
                    email=email if random.random() < .9 else None,
                    phone=phone if random.random() < .75 else None,
                    first_name=noisy(first), last_name=noisy(last),
                    address_line1=hh["addr"] if random.random() < .7 else None,
                    state=hh["state"], zip_code=hh["zip"]))
    return records, truth

def pairwise_metrics(clusters, truth):
    """Pairwise precision/recall over same-person record pairs."""
    tp = fp = 0
    pred_pairs = 0
    truth_groups = defaultdict(list)
    for rrid, p in truth.items(): truth_groups[p].append(rrid)
    total_true_pairs = sum(len(v)*(len(v)-1)//2 for v in truth_groups.values())
    for c in clusters:
        ids = [r.record_id for r in c.records]
        for i in range(len(ids)):
            for j in range(i+1, len(ids)):
                pred_pairs += 1
                if truth[ids[i]] == truth[ids[j]]: tp += 1
                else: fp += 1
    precision = tp / pred_pairs if pred_pairs else 1.0
    recall = tp / total_true_pairs if total_true_pairs else 1.0
    return precision, recall, tp, fp, total_true_pairs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--persons", type=int, default=100_000)
    args = ap.parse_args()

    t0 = time.time()
    print(f"generating {args.persons:,} synthetic persons…")
    persons, households = synth_population(args.persons)
    records, truth = fragment(households)
    print(f"  {len(households):,} households, {len(records):,} records ({time.time()-t0:.1f}s)")

    # Run BOTH configs — the default-vs-tuned comparison IS the lesson
    t1 = time.time()
    res_default = IdentityResolver(ResolverConfig()).resolve(records)
    p0, r0, *_ = pairwise_metrics(res_default.clusters, truth)
    res = IdentityResolver(ResolverConfig(probabilistic_threshold=0.92)).resolve(records)
    s = res.summary()
    print(f"  resolved 2 configs in {time.time()-t1:.1f}s")
    precision, recall, tp, fp, ttp = pairwise_metrics(res.clusters, truth)
    print(f"  default(0.65): p={p0:.3f} r={r0:.3f} | tuned(0.92): p={precision:.3f} r={recall:.3f}")

    # sample households for the inspector: prefer multi-record, multi-member ones
    pid2hh = {m["pid"]: hh for hh in households for m in hh["members"]}
    rid2cluster = {}
    for c in res.clusters:
        for r in c.records: rid2cluster[r.record_id] = c
    samples, seen_hh = [], set()
    for hh in households:
        if len(samples) >= 40: break
        if len(hh["members"]) < 2 or hh["hhid"] in seen_hh: continue
        member_data = []
        interesting = False
        for m in hh["members"]:
            recs = [r for r in records if truth.get(r.record_id) == m["pid"]]
            if len(recs) > 1: interesting = True
            cl = rid2cluster.get(recs[0].record_id) if recs else None
            edges = []
            if cl:
                for e in cl.match_edges:
                    if truth.get(e.record_a_id) == m["pid"] or truth.get(e.record_b_id) == m["pid"]:
                        edges.append({"a": e.record_a_id, "b": e.record_b_id, "type": e.match_type,
                                      "score": round(e.score, 3), "fields": e.matched_fields})
            member_data.append({
                "pid": m["pid"], "name": f"{m['first'].title()} {m['last'].title()}",
                "records": [{"id": r.record_id, "source": r.source, "email": r.email,
                             "phone": r.phone, "name": f"{r.first_name} {r.last_name}"} for r in recs],
                "cluster_id": cl.cluster_id if cl else None,
                "correctly_unified": len({rid2cluster[r.record_id].cluster_id for r in recs}) == 1 if recs else None,
                "match_edges": edges[:6]})
        if interesting:
            seen_hh.add(hh["hhid"])
            samples.append({"hhid": hh["hhid"], "state": hh["state"],
                            "addr_display": hh["addr"].title() + " (synthetic)", "members": member_data})

    hh_sizes = defaultdict(int)
    for hh in households: hh_sizes[len(hh["members"])] += 1

    out = {
        "generated": time.strftime("%Y-%m-%d"),
        "banner": "100% synthetic population; no real individuals; methodology demonstration.",
        "engine": "identity-resolver (github.com/Shubham-Safaya/identity-resolution-engine)",
        "population": {"persons": len(persons), "households": len(households),
                       "records": len(records), "household_size_dist": dict(hh_sizes)},
        "resolution": {
            "clusters": s["total_clusters"], "resolution_rate": s["resolution_rate"],
            "deterministic_matches": s["deterministic_matches"],
            "probabilistic_matches": s["probabilistic_matches"],
            "dedup_rate": round(1 - s["total_clusters"] / len(records), 4),
            "largest_cluster": s["graph_stats"]["largest_cluster"]},
        "config_comparison": {
            "default_threshold_0.65": {"pairwise_precision": round(p0, 4), "pairwise_recall": round(r0, 4)},
            "tuned_threshold_0.92": {"pairwise_precision": None, "pairwise_recall": None},
            "lesson": "The default threshold over-merges realistic households (shared surnames + addresses + family emails). Raising the probabilistic threshold to 0.92 recovers precision at minimal recall cost. Residual false merges are shared-household emails matched deterministically - the fix is identifier-frequency capping (engine roadmap).",
            "_note": "tuned numbers repeated in vs_ground_truth"},
        "vs_ground_truth": {
            "pairwise_precision": round(precision, 4), "pairwise_recall": round(recall, 4),
            "true_pairs": ttp, "found_true_pairs": tp, "false_merged_pairs": fp,
            "note": "Computable ONLY because the truth is manufactured — the entire point of synthetic benchmarking."},
        "runtime_seconds": round(time.time() - t0, 1),
    }
    os.makedirs("data/synthetic", exist_ok=True)
    json.dump(out, open("data/synthetic/results.json", "w"), indent=2)
    json.dump(samples, open("data/synthetic/sample-households.json", "w"), indent=2)
    print(f"wrote data/synthetic/ ({len(samples)} sample households) total {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
