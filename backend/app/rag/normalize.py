import re

_BLANK_RUNS = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    unified = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [line.rstrip() for line in unified.split("\n")]
    return _BLANK_RUNS.sub("\n\n", "\n".join(lines)).strip()
