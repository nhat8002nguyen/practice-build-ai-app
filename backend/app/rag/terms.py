"""Shared content-word tokenization for sparse BM25 and the test HashEmbedder."""

import re

_WORD = re.compile(r"\w+")
STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i in is it my of on or "
    "our the to was we what when where which who why will with you your".split()
)


def content_tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in STOPWORDS]
