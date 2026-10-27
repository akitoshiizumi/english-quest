const starters = /^(?:I|We|You|He|She|It|They|This|That|These|Those|The|A|An|However|Meanwhile|Next|Then)\b/;

export function abbreviationContinues(before: string, after: string): boolean {
  before = before.trimEnd().replace(/["'”’)\]]+$/, '');
  after = after.trimStart().replace(/^["'“‘(]+/, '');
  if (!after) return false;
  if (/\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|No|Fig)\.$/i.test(before)) return true;
  if (/\b(?:e\.g|i\.e)\.$/i.test(before)) return true;
  if (/\b(?:[A-Za-z]\.){2,}$/.test(before)) return !starters.test(after);
  return /(?:^|\s)[A-Z]\.$/.test(before);
}

export function splitEnglishSentences(text: string): string[] {
  const result: string[] = [];
  let start = 0;
  for (const match of text.matchAll(/[.!?]+["'”’)\]]*(?:\s+|$)|\n+/g)) {
    const boundary = match.index + match[0].length;
    if (abbreviationContinues(text.slice(start,boundary),text.slice(boundary))) continue;
    const sentence = text.slice(start,boundary).trim();
    if (sentence) result.push(sentence);
    start = boundary;
  }
  const tail = text.slice(start).trim();
  if (tail) result.push(tail);
  return result;
}
