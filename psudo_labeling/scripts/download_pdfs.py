"""Download the originally-submitted PDF for every ICML 2026 paper, in parallel.

Files land in data/pdfs/<forum_id>.pdf so they join the dataset on forum_id.
A manifest (data/pdfs_manifest.jsonl) records forum_id, submission_number,
file, bytes, source field, and any error. Safe to re-run: existing valid PDFs
are skipped.
"""
import json
import os
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import openreview

RAW = "data/icml2026_raw.jsonl"
OUT_DIR = "data/pdfs"
MANIFEST = "data/pdfs_manifest.jsonl"
WORKERS = 20
RETRIES = 3


def load_env(path=".env"):
    for line in open(path):
        k, _, v = line.strip().partition("=")
        if k:
            os.environ.setdefault(k, v)


def fetch(token, forum_id, field):
    url = f"https://api2.openreview.net/attachment?id={forum_id}&name={field}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    return urllib.request.urlopen(req, timeout=120).read()


def download_one(token, paper):
    forum_id = paper["forum"]
    path = os.path.join(OUT_DIR, f"{forum_id}.pdf")
    if os.path.exists(path) and os.path.getsize(path) > 10_000:
        return {"forum_id": forum_id, "submission_number": paper["number"],
                "file": path, "bytes": os.path.getsize(path), "source": "cached", "error": None}

    fields = [f for f in ("originally_submitted_PDF",) if paper["content"].get(f)]
    last_err = "no originally_submitted_PDF field"
    for field in fields:
        for attempt in range(RETRIES):
            try:
                data = fetch(token, forum_id, field)
                if data[:5] != b"%PDF-":
                    raise ValueError(f"not a PDF ({len(data)} bytes)")
                tmp = path + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
                return {"forum_id": forum_id, "submission_number": paper["number"],
                        "file": path, "bytes": len(data), "source": field, "error": None}
            except Exception as e:
                last_err = f"{field}: {e}"
                time.sleep(2 ** attempt)
    return {"forum_id": forum_id, "submission_number": paper["number"],
            "file": None, "bytes": 0, "source": None, "error": last_err}


def main():
    load_env()
    client = openreview.api.OpenReviewClient(
        baseurl="https://api2.openreview.net",
        username=os.environ["OPENREVIEW_USERNAME"],
        password=os.environ["OPENREVIEW_PASSWORD"],
    )
    os.makedirs(OUT_DIR, exist_ok=True)

    papers = []
    with open(RAW) as f:
        for line in f:
            p = json.loads(line)
            papers.append({"forum": p["forum"], "number": p["number"],
                           "content": {k: p["content"].get(k) for k in ("originally_submitted_PDF",)}})
    print(f"{len(papers)} papers to fetch -> {OUT_DIR}", flush=True)

    lock = threading.Lock()
    done = failed = 0
    t0 = time.time()
    with open(MANIFEST, "w") as mf, ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = [ex.submit(download_one, client.token, p) for p in papers]
        for fut in as_completed(futures):
            r = fut.result()
            with lock:
                mf.write(json.dumps(r, ensure_ascii=False) + "\n")
                done += 1
                if r["error"]:
                    failed += 1
                    print(f"FAIL {r['forum_id']}: {r['error']}", flush=True)
                if done % 250 == 0:
                    mf.flush()
                    rate = done / (time.time() - t0)
                    eta = (len(papers) - done) / rate / 60
                    print(f"{done}/{len(papers)} ({failed} failed) "
                          f"{rate:.1f}/s ETA {eta:.1f}min", flush=True)

    print(f"DONE: {done - failed} ok, {failed} failed, "
          f"{time.time() - t0:.0f}s total", flush=True)


if __name__ == "__main__":
    main()
