"""Static policy/help doc retrieval for the FAQ agent (F17). Deliberately not
a real RAG pipeline — there's no vector store in this stack — just a small,
documented keyword-overlap ranker over a handful of markdown files. Doctor
and fee data is never answered from here; that's `get_doctor_info_tool`
(exact DB lookups), matching spec.md's split between structured tools and
static-doc RAG.
"""

import json
import re
from pathlib import Path

_DOCS_DIR = Path(__file__).parent
_WORD_RE = re.compile(r"[a-z']+")


def _load_docs() -> dict[str, str]:
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(_DOCS_DIR.glob("*.md"))
    }


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def search_policy_docs(query: str) -> str:
    docs = _load_docs()
    query_words = _words(query)

    best_name: str | None = None
    best_score = 0
    for name, content in docs.items():
        score = len(query_words & _words(content))
        if score > best_score:
            best_score = score
            best_name = name

    if best_name is None or best_score == 0:
        return json.dumps({"found": False, "message": "No matching policy document found."})

    return json.dumps({"found": True, "doc": best_name, "content": docs[best_name]})
