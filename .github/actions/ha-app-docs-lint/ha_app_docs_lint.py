#!/usr/bin/env python3
"""ha-app-docs-lint — drift-proof install-docs linter for Home Assistant app/add-on repos.

Rules live in ha-app-docs-rules.json: beside this script when it is vendored,
otherwise under specs/ of the repository that maintains it.
Consumed as a GitHub Action (ha-app-docs-lint) or run directly.

Markdown-aware: it matches rendered prose, not raw markdown source. Fenced code (by
fence type), inline code, markdown link/image URL targets, link brackets, and HTML
comments/tags are stripped before phrase matching, so badge URLs and code blocks never
false-positive. CHANGELOG files are excluded (stale phrases live there as legitimate
history). Profile checks (install badge, required section markers) are REPO-LEVEL: they
consider all scanned docs together, and the install badge must be a My Home Assistant
redirect link whose slug is on the known-good list — a code-fenced, commented-out, or
dead-slug badge does not count. Fails closed on missing explicit paths and on a repo/dir
scan that turns up zero docs. Output uses the shared BLOCK/FIX/SPEC/OFFENDING format.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Fence opener: up to 3 spaces of indent (4+ is an indented code block, not a fence),
# then a run of >=3 backticks or tildes. Capture the marker char so ``` cannot close ~~~.
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"`[^`]*`")
LINK_TARGET = re.compile(r"\]\([^)]*\)")  # ](url) — drop the URL, keep display text
LINK_BRACKETS = re.compile(r"[\[\]]")  # [text] / ![alt] wrappers — keep the text
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)  # multi-line aware
HTML_TAG = re.compile(r"<[^>]+>")
DEFAULT_PATHS = ["README.md", "docs"]


class Finding:
    __slots__ = ("rule_id", "message", "fix_hint", "anchor", "location")

    def __init__(self, rule_id, message, fix_hint, anchor, location):
        self.rule_id = rule_id
        self.message = message
        self.fix_hint = fix_hint
        self.anchor = anchor
        self.location = location


def default_rules_path() -> Path:
    for cand in (
        HERE.parent.parent / "specs" / "ha-app-docs-rules.json",  # repo root/specs
        HERE / "ha-app-docs-rules.json",  # vendored beside action
    ):
        if cand.exists():
            return cand
    return HERE.parent.parent / "specs" / "ha-app-docs-rules.json"


def is_changelog(p: Path) -> bool:
    return p.name.upper().startswith("CHANGELOG")


def nonfenced_lines(text: str):
    """Yield (lineno, raw_line) for lines OUTSIDE fenced code blocks. A fence closes
    only on the same marker character it opened with (``` does not close ~~~)."""
    fence_char = None
    for i, raw in enumerate(text.splitlines(), 1):
        m = FENCE.match(raw)
        if m:
            marker = m.group(1)[0]
            if fence_char is None:
                fence_char = marker
            elif marker == fence_char:
                fence_char = None
            continue
        if fence_char is not None:
            continue
        yield i, raw


def scan_phrases(path: Path, rules: dict) -> list[Finding]:
    if is_changelog(path):
        return []
    compiled = [
        (b, re.compile(b["pattern"], re.I if "i" in b.get("flags", "") else 0))
        for b in rules["banned_phrases"]
    ]
    out: list[Finding] = []
    # Strip multi-line HTML comments up front so a comment spanning lines can't hide
    # (or split) a phrase. Section markers are matched separately on raw text.
    text = HTML_COMMENT.sub(" ", path.read_text(encoding="utf-8"))
    for lineno, raw in nonfenced_lines(text):
        line = INLINE_CODE.sub(" ", raw)
        line = LINK_TARGET.sub("] ", line)  # ](url) -> ] , kills badge URLs
        line = LINK_BRACKETS.sub(" ", line)  # [Add-ons] -> Add-ons (link-split nav)
        line = HTML_TAG.sub(" ", line)
        for b, rx in compiled:
            if rx.search(line):
                out.append(
                    Finding(
                        b["rule_id"],
                        b["message"],
                        b.get("fix_hint", ""),
                        b.get("spec_anchor", ""),
                        f"{path}:{lineno}",
                    )
                )
    return out


def redirect_slugs(text: str, badge_rx: re.Pattern) -> set[str]:
    """Return My Home Assistant redirect slugs that appear in real (rendered) content:
    outside fenced code and outside inline-code spans. A badge hidden in a code block or
    backticks does not count."""
    slugs: set[str] = set()
    text = HTML_COMMENT.sub(" ", text)
    for _lineno, raw in nonfenced_lines(text):
        line = INLINE_CODE.sub(" ", raw)  # keep URLs, drop inline-code samples
        for m in badge_rx.finditer(line):
            slugs.add(m.group(1).lower())
    return slugs


def check_profile_repo(
    files: list[Path], rules: dict, profile_name: str
) -> list[Finding]:
    prof = rules["profiles"].get(profile_name)
    if prof is None:
        return [
            Finding(
                "UNKNOWN_PROFILE",
                f"unknown profile {profile_name!r}",
                "use one of: " + ", ".join(rules["profiles"]),
                "profiles",
                "(config)",
            )
        ]
    out: list[Finding] = []
    texts = {f: f.read_text(encoding="utf-8") for f in files}

    if prof.get("requires_install_badge"):
        ib = rules["install_badge"]
        badge_rx = re.compile(ib["pattern"], re.I)
        known = {
            s.lower() for s in rules.get("redirect_slugs", {}).get("known_good", [])
        }
        found: set[str] = set()
        for t in texts.values():
            found |= redirect_slugs(t, badge_rx)
        if not (found & known):
            msg = ib["message"]
            if found:
                msg += (
                    f" (found redirect slug(s) {sorted(found)} but none are "
                    f"known-good: {sorted(known)})"
                )
            out.append(
                Finding(
                    ib["rule_id"],
                    msg,
                    ib.get("fix_hint", ""),
                    ib.get("spec_anchor", ""),
                    "(install docs)",
                )
            )

    for marker in prof.get("required_markers", []):
        present = any(
            (f"<!-- {marker} -->" in t or f"<!--{marker}-->" in t)
            for t in texts.values()
        )
        if not present:
            out.append(
                Finding(
                    "SECTION_MARKER",
                    f"missing required section marker <!-- {marker} --> "
                    f"for profile {profile_name!r}",
                    f"Add the marker above the relevant section: <!-- {marker} -->",
                    "profiles",
                    "(install docs)",
                )
            )
    return out


def gather(paths: list[str]):
    """Return (scanned, missing, excluded, did_repo_scan).

    scanned  = resolved, deduped README/docs markdown files to lint
    missing  = explicit paths that do not exist (fail closed)
    excluded = count of existing files skipped as CHANGELOG (a no-op, not an error)
    did_repo_scan = True if any input was a directory or the default set was used
    """
    scanned: list[Path] = []
    missing: list[str] = []
    excluded = 0
    did_repo_scan = paths is DEFAULT_PATHS
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            did_repo_scan = True
            for md in sorted(p.rglob("*.md")):
                if is_changelog(md):
                    excluded += 1
                else:
                    scanned.append(md)
        elif p.exists():
            if is_changelog(p):
                excluded += 1
            else:
                scanned.append(p)
        else:
            missing.append(raw)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for p in scanned:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            deduped.append(p)
    return deduped, missing, excluded, did_repo_scan


def emit(f: Finding, spec_url: str) -> None:
    print(f"BLOCK: {f.rule_id} {f.message}", file=sys.stderr)
    if f.fix_hint:
        print(f"FIX: {f.fix_hint}", file=sys.stderr)
    print(f"SPEC: {spec_url}#{f.anchor}", file=sys.stderr)
    print(f"OFFENDING: {f.location}", file=sys.stderr)
    print("", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="ha-app-docs-lint")
    ap.add_argument(
        "paths", nargs="*", help="files/dirs to scan (default: README.md docs)"
    )
    ap.add_argument("--profile", default="addon", help="repo-type profile")
    ap.add_argument("--rules", default=None, help="path to ha-app-docs-rules.json")
    args = ap.parse_args()

    rules_path = Path(args.rules) if args.rules else default_rules_path()
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    spec_url = rules.get("spec_url", "")

    paths = args.paths if args.paths else DEFAULT_PATHS
    scanned, missing, excluded, did_repo_scan = gather(paths)

    findings: list[Finding] = []
    for raw in missing:
        findings.append(
            Finding(
                "MISSING_PATH",
                f"path not found: {raw}",
                "check the `paths` input; a public standard fails closed on typos",
                "scope",
                raw,
            )
        )
    # Fail closed: a repo/dir/default scan that found no lintable docs is an error, not a
    # silent pass. An explicit CHANGELOG-only invocation (excluded>0) is a no-op, not a fail.
    if not scanned and not missing and excluded == 0 and did_repo_scan:
        findings.append(
            Finding(
                "NO_DOCS",
                "no install docs found to scan (README.md / docs/*.md)",
                "point --paths at the README/docs, or add a README",
                "scope",
                "(scope)",
            )
        )

    for p in scanned:
        findings += scan_phrases(p, rules)
    if scanned:
        findings += check_profile_repo(scanned, rules, args.profile)

    print(
        f"ha-app-docs-lint: scanned {len(scanned)} file(s), "
        f"{len(missing)} missing, {excluded} changelog(s) skipped",
        file=sys.stderr,
    )

    if findings:
        for f in findings:
            emit(f, spec_url)
        print(f"ha-app-docs-lint: {len(findings)} problem(s)", file=sys.stderr)
        sys.exit(1)
    print("ha-app-docs-lint OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
