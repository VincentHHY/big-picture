"""Score one decision-layer reply against the rules a script can actually settle.

    python score_mechanical.py <reply-file> --boundary on|off [--json]

Only the mechanical half lives here. Whether a reply is any GOOD is graded by
the blind grader (see grader.md), because a reply can pass every rule below and
still be useless - "there is a choice here, I recommend the first option" has no
path, no symbol and a correct footer.

Two tiers, on purpose:

  strict    Patterns with effectively no false positives - backticks, fenced
            blocks, paths, call syntax, snake_case, line references. These carry
            the score.
  advisory  camelCase and PascalCase identifiers. English proper nouns look the
            same as code identifiers, so this tier reports and never scores. A
            check that cries wolf would quietly poison the baseline it is meant
            to measure.

The reply is split at a line reading exactly `--- where ---`. Everything above it
is prose and must be clean; everything below is the anchor block and is exempt,
which is the entire point of having the line.
"""

import argparse
import json
import re
import sys
from pathlib import Path

FOOTER = "\u25aa decision-layer"
DIVIDER = "--- where ---"

CODE_EXTENSIONS = (
    "py|cs|js|ts|tsx|jsx|json|md|txt|ya?ml|csv|xml|ini|cfg|sh|ps1|toml|sql|html|css|java|go|rb|rs"
)

STRICT_PATTERNS = {
    "fenced_code_block": re.compile(r"```"),
    "inline_backticks": re.compile(r"`"),
    "path_with_separator": re.compile(r"[\w.\-]+[/\\][\w./\\-]*\.\w{1,6}"),
    "bare_filename": re.compile(rf"\b[\w\-]+\.(?:{CODE_EXTENSIONS})\b", re.I),
    "line_reference": re.compile(r"\S:\d+\b|\blines?\s+\d+\b", re.I),
    "call_syntax": re.compile(r"\b[A-Za-z_]\w*\(\s*\)|\b\w+\.\w+\(|\b[A-Za-z_]\w*\(['\"]"),
    "snake_case": re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b"),
}

ADVISORY_PATTERNS = {
    "camel_or_pascal_case": re.compile(r"\b[a-z]+[A-Z]\w*\b|\b[A-Z][a-z]+[A-Z][a-z]\w*\b"),
}

# Ordinary English and product names that look exactly like identifiers.
# Add your own organisation's product names here. To your reader they are proper
# nouns, not jargon, so flagging them would be a false positive.
ADVISORY_ALLOWLIST = {
    "javascript", "typescript", "powershell", "github", "gitlab", "devops",
    "kubernetes", "postgresql", "mysql", "sqlite", "openai", "anthropic",
    "claudecode", "youtube", "linkedin", "iphone", "macos", "ios", "npm",
    "vscode", "jetbrains", "webassembly",
}

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def split_reply(text):
    """Prose above the divider, anchors below. The footer belongs to neither."""
    lines = text.splitlines()
    footer_present = False
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].strip() == FOOTER:
        footer_present = True
        lines.pop()

    divider_at = None
    for index, line in enumerate(lines):
        if line.strip() == DIVIDER:
            divider_at = index
            break

    if divider_at is None:
        return "\n".join(lines), "", footer_present
    return "\n".join(lines[:divider_at]), "\n".join(lines[divider_at + 1:]), footer_present


def strip_allowed(matches):
    return [m for m in matches if m.lower().strip() not in ADVISORY_ALLOWLIST]


def leaking_sentences(prose):
    """Which sentences mix plain English with a raw token - the founding complaint."""
    leaks = []
    for sentence in SENTENCE_SPLIT.split(prose):
        flat = " ".join(sentence.split())
        if not flat:
            continue
        words = [w for w in re.findall(r"\b[a-z]{2,}\b", flat.lower())]
        hits = []
        for name, pattern in STRICT_PATTERNS.items():
            found = pattern.findall(flat)
            if found:
                hits.append(name)
        if hits and len(words) >= 4:
            leaks.append({"sentence": flat[:200], "triggered": sorted(set(hits))})
    return leaks


def score(text, boundary):
    prose, anchors, footer_present = split_reply(text)
    checks = []

    def record(name, passed, evidence="", tier="strict"):
        checks.append({"text": name, "passed": passed, "evidence": evidence, "tier": tier})

    if boundary == "on":
        record("footer is present and last", footer_present,
               "" if footer_present else "the reply does not end with the footer line")
        for name, pattern in STRICT_PATTERNS.items():
            found = pattern.findall(prose)
            found = [f if isinstance(f, str) else f[0] for f in found]
            record(f"no {name.replace('_', ' ')} above the line", not found,
                   "; ".join(sorted(set(found))[:6]))
        for name, pattern in ADVISORY_PATTERNS.items():
            found = strip_allowed(pattern.findall(prose))
            record(f"no {name.replace('_', ' ')} above the line", not found,
                   "; ".join(sorted(set(found))[:6]), tier="advisory")
        leaks = leaking_sentences(prose)
        record("no sentence mixes plain English with a raw token", not leaks,
               json.dumps(leaks[:3]) if leaks else "")
    else:
        record("footer is absent", not footer_present,
               "the reply carries the footer but this turn was not armed")

    scored = [c for c in checks if c["tier"] == "strict"]
    passed = sum(1 for c in scored if c["passed"])
    return {
        "boundary": boundary,
        "has_anchor_block": bool(anchors.strip()),
        "prose_chars": len(prose),
        "anchor_chars": len(anchors),
        "passed": passed,
        "total": len(scored),
        "pass_rate": round(passed / len(scored), 3) if scored else 0.0,
        "checks": checks,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reply")
    parser.add_argument("--boundary", choices=["on", "off"], default="on")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = score(Path(args.reply).read_text(encoding="utf-8"), args.boundary)

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"{result['passed']}/{result['total']} strict checks  "
          f"(anchor block: {'yes' if result['has_anchor_block'] else 'no'})")
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        tag = "" if check["tier"] == "strict" else " [advisory]"
        print(f"  {mark}{tag}  {check['text']}")
        if check["evidence"]:
            print(f"        {check['evidence'][:300]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
