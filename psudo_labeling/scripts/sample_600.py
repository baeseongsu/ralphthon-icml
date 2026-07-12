"""Sample 600 papers (~10%) stratified jointly by primary_area AND score
distribution, then write per-paper labeler input payloads (reviews-only).

- Area quotas: largest-remainder proportional to area sizes.
- Within each area: allocation across global score-quartile bins follows that
  area's own bin distribution (largest remainder), so both the area marginal
  and the score marginal of the population are preserved.
- Score = mean reviewer overall_recommendation per paper.

Outputs:
  data/sample600.json            — sampled papers w/ area, decision, score bin
  data/label_inputs/<forum>.json — one payload per paper for the labeler agents
"""
import json
import os
import random
import statistics
from collections import Counter, defaultdict

from datasets import load_from_disk

N_TARGET = 600
SEED = 42

REVIEW_FIELDS = [
    "reviewer", "summary", "strengths_and_weaknesses",
    "soundness", "presentation", "significance", "originality",
    "key_questions_for_authors", "limitations",
    "overall_recommendation", "confidence",
]


def largest_remainder(quotas, total):
    alloc = {k: int(q) for k, q in quotas.items()}
    for k in sorted(quotas, key=lambda k: quotas[k] - alloc[k], reverse=True)[: total - sum(alloc.values())]:
        alloc[k] += 1
    return alloc


ds = load_from_disk("data/icml2026")

mean_rec = []
for r in ds:
    recs = [rv["overall_recommendation"] for rv in json.loads(r["reviews_json"])]
    mean_rec.append(statistics.mean(recs))

qs = statistics.quantiles(mean_rec, n=4)  # global quartile edges
print(f"score(mean overall_recommendation) 분위 경계: {[round(q,2) for q in qs]}")


def score_bin(x):
    return sum(x > q for q in qs)  # 0..3


bins = [score_bin(x) for x in mean_rec]
by_area = defaultdict(list)
for i, r in enumerate(ds):
    by_area[r["primary_area"]].append(i)

area_alloc = largest_remainder(
    {a: N_TARGET * len(idx) / len(ds) for a, idx in by_area.items()}, N_TARGET
)

rng = random.Random(SEED)
picked = []
for a, n in area_alloc.items():
    if n == 0:
        continue
    idxs = by_area[a]
    by_bin = defaultdict(list)
    for i in idxs:
        by_bin[bins[i]].append(i)
    bin_alloc = largest_remainder(
        {b: n * len(v) / len(idxs) for b, v in by_bin.items()}, n
    )
    # sample per bin; borrow from neighbours if a bin runs short
    short = 0
    for b, k in bin_alloc.items():
        take = min(k, len(by_bin[b]))
        short += k - take
        picked += rng.sample(by_bin[b], take)
    if short:
        pool = [i for i in idxs if i not in set(picked)]
        picked += rng.sample(pool, short)

assert len(picked) == N_TARGET, len(picked)
rng.shuffle(picked)

os.makedirs("data/label_inputs", exist_ok=True)
manifest = []
for i in picked:
    r = ds[i]
    reviews = [{f: rv.get(f) for f in REVIEW_FIELDS} for rv in json.loads(r["reviews_json"])]
    payload = {
        "forum_id": r["forum_id"],
        "title": r["title"],
        "abstract": r["abstract"],
        "primary_area": r["primary_area"],
        "decision": r["decision"],
        "decision_comment": r["decision_comment"],
        "reviews": reviews,
    }
    with open(f"data/label_inputs/{r['forum_id']}.json", "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    manifest.append({
        "forum_id": r["forum_id"], "primary_area": r["primary_area"],
        "decision": r["decision"], "num_reviews": len(reviews),
        "mean_overall_recommendation": round(mean_rec[i], 3),
        "score_bin": bins[i],
    })

with open("data/sample600.json", "w") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=1)

# distribution match report
pop_bins = Counter(bins)
smp_bins = Counter(m["score_bin"] for m in manifest)
print(f"\n{'score bin':>9s} {'모집단':>8s} {'샘플':>8s}")
for b in range(4):
    print(f"{b:9d} {pop_bins[b]/len(ds):8.1%} {smp_bins[b]/N_TARGET:8.1%}")
pop_mean = statistics.mean(mean_rec)
smp_mean = statistics.mean(m["mean_overall_recommendation"] for m in manifest)
print(f"평균 score: 모집단 {pop_mean:.3f} vs 샘플 {smp_mean:.3f}")
n_spot = sum(m["decision"] == "Accept (spotlight)" for m in manifest)
print(f"spotlight: 모집단 {536/len(ds):.1%} vs 샘플 {n_spot/N_TARGET:.1%} ({n_spot}편)")
print(f"areas: {len({m['primary_area'] for m in manifest})}개 | 총 {len(manifest)}편")
