"""Scrape all ICML 2026 accepted papers + full reply trees (reviews, rebuttals,
meta-review/decision) from OpenReview into a raw JSONL dump.

Output: data/icml2026_raw.jsonl — one line per paper:
  {"forum": ..., "number": ..., "content": {...}, "replies": [...]}
"""
import json
import os
import sys
import time

import openreview

VENUE = "ICML.cc/2026/Conference"
OUT = "data/icml2026_raw.jsonl"
PAGE = 500


def load_env(path=".env"):
    for line in open(path):
        k, _, v = line.strip().partition("=")
        if k:
            os.environ.setdefault(k, v)


def unwrap(content):
    """OpenReview v2 content values are {'value': X} wrappers."""
    out = {}
    for k, v in content.items():
        out[k] = v.get("value") if isinstance(v, dict) and "value" in v else v
    return out


def main():
    load_env()
    client = openreview.api.OpenReviewClient(
        baseurl="https://api2.openreview.net",
        username=os.environ["OPENREVIEW_USERNAME"],
        password=os.environ["OPENREVIEW_PASSWORD"],
    )
    os.makedirs("data", exist_ok=True)

    seen = set()
    if os.path.exists(OUT):  # resume support
        with open(OUT) as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["forum"])
                except json.JSONDecodeError:
                    pass
        print(f"resuming: {len(seen)} papers already dumped", flush=True)

    offset = 0
    total_written = len(seen)
    with open(OUT, "a") as out:
        while True:
            for attempt in range(5):
                try:
                    t0 = time.time()
                    notes = client.get_notes(
                        content={"venueid": VENUE},
                        details="replies",
                        limit=PAGE,
                        offset=offset,
                        sort="number:asc",
                    )
                    break
                except Exception as e:
                    wait = 2 ** attempt * 5
                    print(f"page offset={offset} failed ({e}); retry in {wait}s", flush=True)
                    time.sleep(wait)
            else:
                sys.exit(f"giving up at offset={offset}")

            if not notes:
                break
            for n in notes:
                if n.forum in seen:
                    continue
                row = {
                    "forum": n.forum,
                    "number": n.number,
                    "content": unwrap(n.content),
                    "replies": [
                        {
                            "id": r["id"],
                            "invitations": r["invitations"],
                            "signatures": r["signatures"],
                            "replyto": r.get("replyto"),
                            "cdate": r.get("cdate"),
                            "content": unwrap(r["content"]),
                        }
                        for r in n.details["replies"]
                    ],
                }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                total_written += 1
            out.flush()
            print(f"offset={offset} +{len(notes)} notes ({time.time()-t0:.1f}s) total={total_written}", flush=True)
            offset += PAGE
            time.sleep(1)

    print(f"DONE: {total_written} papers -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
