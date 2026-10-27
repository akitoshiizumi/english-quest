"""Sentence boundaries that preserve common English abbreviations."""
import re

_STARTERS = re.compile(r'^(?:I|We|You|He|She|It|They|This|That|These|Those|The|A|An|However|Meanwhile|Next|Then)\b')


def abbreviation_continues(before: str, after: str) -> bool:
    before = before.rstrip().rstrip('\"\'”’)]')
    after = after.lstrip().lstrip('\"\'“‘(')
    if not after:
        return False
    if re.search(r'\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|No|Fig)\.$', before, re.I):
        return True
    if re.search(r'\b(?:e\.g|i\.e)\.$', before, re.I):
        return True
    if re.search(r'\b(?:[A-Za-z]\.){2,}$', before):
        return not bool(_STARTERS.match(after))
    return bool(re.search(r'(?:^|\s)[A-Z]\.$', before))


def split_english_sentences(text: str) -> list[str]:
    result = []
    start = 0
    for match in re.finditer(r'[.!?]+[\"\'”’)\]]*(?:\s+|$)|\n+', text):
        boundary = match.end()
        if abbreviation_continues(text[start:boundary], text[boundary:]):
            continue
        part = text[start:boundary].strip()
        if part:
            result.append(part)
        start = boundary
    tail = text[start:].strip()
    if tail:
        result.append(tail)
    return result
