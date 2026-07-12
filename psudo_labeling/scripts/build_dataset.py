"""Build a ReviewArena-style HF dataset from the raw ICML 2026 OpenReview dump.

Row = one paper. reviews_json holds the per-reviewer 2026 form fields
(review content only — author rebuttals/discussion are excluded; they remain
available in the raw dump if ever needed).

Output: data/icml2026 (HF datasets format) + data/icml2026_papers.jsonl
"""
import json
import os

from datasets import Dataset

RAW = "data/icml2026_raw.jsonl"
REVIEW_FIELDS = [
    "summary",
    "strengths_and_weaknesses",
    "soundness",
    "presentation",
    "significance",
    "originality",
    "key_questions_for_authors",
    "limitations",
    "overall_recommendation",
    "confidence",
    "final_justification",
]


def inv_endswith(reply, suffix):
    return any(i.endswith(suffix) for i in reply["invitations"])


def build_row(p):
    replies = p["replies"]
    reviews = {}
    for r in replies:
        if inv_endswith(r, "/-/Official_Review"):
            c = r["content"]
            reviews[r["id"]] = {
                "review_id": r["id"],
                "reviewer": r["signatures"][0].split("/")[-1],
                **{f: c.get(f) for f in REVIEW_FIELDS},
            }

    dec = next((r for r in replies if inv_endswith(r, "/-/Decision")), None)
    c = p["content"]
    return {
        "forum_id": p["forum"],
        "submission_number": p["number"],
        "title": c.get("title"),
        "abstract": c.get("abstract"),
        "authors": c.get("authors") or [],
        "keywords": c.get("keywords") or [],
        "primary_area": c.get("primary_area"),
        "tldr": c.get("TLDR"),
        "decision": dec["content"].get("decision") if dec else None,
        "decision_comment": dec["content"].get("comment") if dec else None,
        "num_reviews": len(reviews),
        "reviews_json": json.dumps(list(reviews.values()), ensure_ascii=False),
        "paper_url": f"https://openreview.net/forum?id={p['forum']}",
    }


def main():
    rows = []
    with open(RAW) as f:
        for line in f:
            p = json.loads(line)
            rows.append(build_row(p))

    print(f"papers: {len(rows)}")
    os.makedirs("data", exist_ok=True)
    with open("data/icml2026_papers.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    ds = Dataset.from_list(rows)
    ds.save_to_disk("data/icml2026")
    print(ds)


if __name__ == "__main__":
    main()
