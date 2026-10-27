"""Deterministic vocabulary ranking, matching, and embedding utilities."""

from __future__ import annotations

import math
import re
import unicodedata


def normalize_headword(value: str) -> str:
    return ' '.join(unicodedata.normalize('NFKC', value or '').casefold().split())


def cosine_similarity(left, right) -> float:
    if len(left) != len(right) or not left:
        raise ValueError('Vectors must have the same nonzero dimension')
    left = [float(x) for x in left]
    right = [float(x) for x in right]
    denominator = math.sqrt(sum(x*x for x in left)) * math.sqrt(sum(x*x for x in right))
    if denominator == 0:
        return 0.0
    return sum(a*b for a,b in zip(left,right)) / denominator


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:['’-][a-z0-9]+)*", (text or '').casefold())


def word_forms(word: str) -> set[str]:
    normalized = normalize_headword(word)
    forms = {normalized}
    if not normalized.isascii():
        return forms
    words = normalized.split()
    first = words[0]
    irregular = {'be':['am','is','are','was','were','been'],'go':['went','gone'],'take':['took','taken'],'make':['made'],'have':['has','had'],'do':['does','did','done'],'run':['ran'],'write':['wrote','written'],'speak':['spoke','spoken'],'get':['got'],'come':['came'],'see':['saw','seen']}
    first_forms={first, *irregular.get(first, [])}
    if first.endswith('y') and len(first)>2: first_forms.add(first[:-1]+'ies')
    first_forms.update((first+'s', first+'es', first+'ed', first+'ing'))
    if first.endswith('e'): first_forms.update((first[:-1]+'ed',first[:-1]+'ing'))
    if not first.endswith('e') and len(first)>2: first_forms.add(first[:-1]+'ing')
    forms.update(' '.join([form, *words[1:]]) for form in first_forms)
    return forms


_TRAILING_PHRASE_PLACEHOLDER = re.compile(r"(?:\s*(?:～|〜|~|…|\.\.\.)\s*)+$")


def phrase_match_text(headword: str) -> str:
    """Remove recognized trailing open-phrase markers before English coverage matching."""
    return _TRAILING_PHRASE_PLACEHOLDER.sub('', (headword or '').strip()).strip()


def find_usage(text: str, headword: str) -> list[dict]:
    """Return offsets for literal headwords and common inflections.

    A recognized trailing placeholder denotes an open phrase, so match the
    English stem while leaving the placeholder out of generated prose.
    """
    match_text = phrase_match_text(headword)
    forms = sorted(word_forms(match_text), key=len, reverse=True)
    if not forms:
        return []
    pattern = r'(?<![A-Za-z0-9])(' + '|'.join(re.escape(form) for form in forms) + r')(?![A-Za-z0-9])'
    return [{'text': match.group(1), 'start': match.start(), 'end': match.end()} for match in re.finditer(pattern, text, re.IGNORECASE)]


def cosine_disposition(score: float, threshold: float) -> str:
    return 'similar' if score >= threshold else 'distinct'


def select_weak_vocabulary(items: list[dict], direction: str, limit: int, include_unstudied: bool = True) -> list[dict]:
    """Rank unknown first, then low self-report rates, with a stable vocab ID tie break."""
    if direction not in ('en_to_ja', 'ja_to_en'):
        raise ValueError('Unsupported learning direction')
    ranked = []
    for item in items:
        events = [event for event in item.get('events', []) if event.get('direction') == direction]
        if not events:
            if include_unstudied:
                ranked.append(((0, 0.0, str(item.get('vocab_id', ''))), { 'score': 0.0, 'reason': '未学習・方向別履歴なし' }, item))
            continue
        known = sum(event.get('rating') == 'known' for event in events)
        score = known / len(events)
        ranked.append(((1, score, str(item.get('vocab_id', ''))), { 'score': score, 'reason': f'覚えていた {known}/{len(events)} 件（方向別）' }, item))
    ranked.sort(key=lambda entry: entry[0])
    return [{**item, 'weakness_score': score['score'], 'selection_reason': score['reason']} for _,score,item in ranked[:max(0,limit)]]

