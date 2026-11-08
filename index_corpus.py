#!/usr/bin/env python3
"""Chunk the policy corpus, embed it locally, and search it.

The corpus is the analysis repo's corpus/ directory: 500 documents, split at
800 characters with a 120-character overlap (1,446 chunks). eval/ is not read.

Build writes index/chunks.jsonl and index/vectors.npy. Search embeds the
question with the same local model, searches that vector list and a keyword
list, merges the two, and drops any chunk under not-in-force/.

    python index_corpus.py build --corpus /path/to/corpus
    python index_corpus.py search "why is bank proof required"
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

CHUNK = 800
OVERLAP = 120
MODEL = "all-MiniLM-L6-v2"
TOKEN = re.compile(r"[a-z0-9§]+(?:-[a-z0-9§]+)*")
HERE = Path(__file__).resolve().parent
DEFAULT_INDEX = HERE / "index"


def chunk_text(text: str) -> list[str]:
    if len(text) <= CHUNK:
        return [text]
    step = CHUNK - OVERLAP
    pieces = []
    start = 0
    while start < len(text):
        pieces.append(text[start : start + CHUNK])
        if start + CHUNK >= len(text):
            break
        start += step
    return pieces


def expected_chunks(text: str) -> int:
    if len(text) <= CHUNK:
        return 1
    return 1 + math.ceil((len(text) - CHUNK) / (CHUNK - OVERLAP))


def document_id(text: str, path: Path) -> str:
    for line in text.splitlines():
        if "Document ID" not in line or "|" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] == "Document ID" and cells[1]:
            return cells[1]
    return path.stem


def load_chunks(corpus: Path) -> list[dict]:
    documents = corpus / "documents"
    files = sorted(path for path in documents.rglob("*.md") if path.is_file())
    rows = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(corpus).as_posix()
        in_force = "not-in-force" not in path.parts
        pieces = chunk_text(text)
        if len(pieces) != expected_chunks(text):
            raise RuntimeError(f"chunk count drifted for {relative}")
        doc_id = document_id(text, path)
        for piece in pieces:
            rows.append(
                {
                    "document_id": doc_id,
                    "path": relative,
                    "text": piece,
                    "in_force": in_force,
                }
            )
    return rows


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def build(corpus: Path, out: Path) -> None:
    from sentence_transformers import SentenceTransformer
    import numpy as np

    rows = load_chunks(corpus)
    model = SentenceTransformer(MODEL)
    vectors = model.encode(
        [row["text"] for row in rows],
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    out.mkdir(parents=True, exist_ok=True)
    with (out / "chunks.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    np.save(out / "vectors.npy", vectors)
    documents = len({row["path"] for row in rows})
    held_back = sum(1 for row in rows if not row["in_force"])
    print(f"documents {documents}")
    print(f"chunks {len(rows)}")
    print(f"not-in-force chunks {held_back}")
    print(f"wrote {out}")


def load_index(index: Path) -> tuple[list[dict], object]:
    import numpy as np

    rows = [
        json.loads(line)
        for line in (index / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    vectors = np.load(index / "vectors.npy")
    if len(rows) != len(vectors):
        raise RuntimeError("chunks.jsonl and vectors.npy are different lengths")
    return rows, vectors


def merge(vector_order: list[int], keyword_order: list[int]) -> list[int]:
    scores: dict[int, float] = {}
    for order in (vector_order, keyword_order):
        for rank, row_id in enumerate(order):
            scores[row_id] = scores.get(row_id, 0.0) + 1.0 / (60 + rank + 1)
    return sorted(scores, key=lambda row_id: scores[row_id], reverse=True)


def search(query: str, index: Path, k: int) -> list[dict]:
    from rank_bm25 import BM25Okapi
    from sentence_transformers import SentenceTransformer
    import numpy as np

    rows, vectors = load_index(index)
    query_vector = SentenceTransformer(MODEL, local_files_only=True).encode(
        [query],
        normalize_embeddings=True,
    )[0]
    vector_scores = vectors @ query_vector
    vector_order = np.argsort(-vector_scores).tolist()

    keyword = BM25Okapi([tokens(row["text"]) for row in rows])
    keyword_scores = keyword.get_scores(tokens(query))
    keyword_order = np.argsort(-keyword_scores).tolist()

    found = []
    for row_id in merge(vector_order, keyword_order):
        row = rows[row_id]
        if not row["in_force"]:
            continue
        found.append(row)
        if len(found) == k:
            break
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="Index the policy corpus and search it.")
    commands = parser.add_subparsers(dest="command", required=True)

    build_command = commands.add_parser("build")
    build_command.add_argument("--corpus", type=Path, required=True)
    build_command.add_argument("--out", type=Path, default=DEFAULT_INDEX)

    search_command = commands.add_parser("search")
    search_command.add_argument("query")
    search_command.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    search_command.add_argument("--k", type=int, default=5)

    args = parser.parse_args()
    if args.command == "build":
        build(args.corpus, args.out)
        return
    for row in search(args.query, args.index, args.k):
        print(f"{row['document_id']}  {row['path']}")


if __name__ == "__main__":
    main()
