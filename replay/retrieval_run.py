"""Score retrieval.txt against the remote corpus. No chat model."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
sys.path.insert(0, str(SRC))

from dotenv import load_dotenv

load_dotenv(HERE.parent / ".env")

from copilot.corpus.remote import RemoteCorpus


def rows() -> list[tuple[str, set[str]]]:
    out: list[tuple[str, set[str]]] = []
    for raw in (HERE / "retrieval.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        query, ids = line.split("\t", 1)
        out.append((query.strip(), {item.strip() for item in ids.split(",") if item.strip()}))
    return out


def hit_at(hits: list[dict], want: set[str], k: int) -> bool:
    found = {str(row.get("document_id") or "") for row in hits[:k]}
    return bool(found & want)


def main() -> None:
    parser = argparse.ArgumentParser(description="Recall@k for replay/retrieval.txt")
    parser.add_argument("--k", type=int, default=8)
    args = parser.parse_args()
    corpus = RemoteCorpus()
    cases = rows()
    hit4 = hit8 = 0
    for query, want in cases:
        hits = corpus.search(query, k=max(args.k, 8))
        ok4 = hit_at(hits, want, 4)
        ok8 = hit_at(hits, want, 8)
        hit4 += ok4
        hit8 += ok8
        top = ",".join(str(row.get("document_id") or "") for row in hits[:4])
        print(f"{'ok' if ok4 else 'miss@4'} {'ok' if ok8 else 'miss@8'}  {query}  top4={top}")
    n = len(cases)
    print(f"hit@4={hit4 / n:.3f} ({hit4}/{n})  hit@8={hit8 / n:.3f} ({hit8}/{n})")


if __name__ == "__main__":
    main()
