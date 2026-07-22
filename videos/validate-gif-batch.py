#!/usr/bin/env python3
"""Validate managed Quiet Proof Loops sources and published binary baselines."""

from __future__ import annotations

import argparse
import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence

from quiet_proof_loops import (
    ContractError,
    ProjectSpec,
    build_baseline_data,
    check_baseline_file,
    discover_published_project_ids,
    display_path,
    load_brief_contract,
    load_fixture,
    load_frame_contract,
    load_json_document,
    load_project_registry,
    palette_values,
    sha256_file,
    source_ref_content_matches_baseline,
    validate_baseline_data,
    validate_repository_truth,
    verify_asset_manifest,
    write_baseline_file,
)


VIDEOS_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = VIDEOS_ROOT.parent
FIXTURE_ROOT = VIDEOS_ROOT / "fixtures" / "quiet-proof-loops-minimal"
TEMPLATE_ROOT = VIDEOS_ROOT / "_template"
TEMPLATE_REQUIRED_FILES = (
    "README.md",
    "BRIEF.md",
    "VERIFICATION.template.md",
    "adapter.json",
    "assets/manifest.json",
    "shot-plan.json",
    "package.json",
    "hyperframes.json",
    "meta.json",
    "index.html",
    "compositions/index.html",
    "index.motion.json",
    "compositions/index.motion.json",
)

# The pilot pre-dates the managed contract: it stays published and
# baseline-locked but intentionally has no registry entry (videos/README.md).
LEGACY_UNMANAGED_PROJECT_IDS = frozenset({"sleepradar-more-than-presence"})

REQUIRED_PACKAGE_SCRIPTS = ("dev", "check", "render", "publish")
REQUIRED_MOTION_ASSERTIONS = ("appearsBy", "before", "staysInFrame", "keepsMoving")
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}

BANNED_SOURCE = {
    "audio element": re.compile(r"<audio\b", re.I),
    "video element": re.compile(r"<video\b", re.I),
    "randomness": re.compile(r"\b(?:Math\.random|crypto\.getRandomValues)\s*\("),
    "wall-clock time": re.compile(r"\b(?:Date\.now|performance\.now)\s*\("),
    "timer": re.compile(r"\b(?:setTimeout|setInterval|requestAnimationFrame)\s*\("),
    "network access": re.compile(r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\b"),
    "CSS animation": re.compile(r"(?:@keyframes|\banimation(?:-[a-z-]+)?\s*:)", re.I),
    "CSS transition": re.compile(r"\btransition(?:-[a-z-]+)?\s*:", re.I),
    "infinite GSAP repeat": re.compile(r"\brepeat\s*:\s*-1\b"),
    "imperative playback": re.compile(r"\.(?:play|restart|resume)\s*\("),
}
GRADIENT_SOURCE = re.compile(r"\b(?:linear|radial|conic)-gradient\s*\(", re.I)
EXTERNAL_RESOURCE = re.compile(
    r"(?:src|href)\s*=\s*[\"'](?:https?:)?//|@import\s+(?:url\s*\()?\s*[\"']?(?:https?:)?//",
    re.I,
)
LAYOUT_TWEEN = re.compile(
    r"\b(?:tl|gsap)\.(?:to|from|fromTo)\s*\([^;]*?"
    r"(?:\{|,)\s*(?:width|height|top|left|right|bottom|fontSize|letterSpacing|wordSpacing)\s*:",
    re.S,
)
MEDICAL_VISIBLE_LANGUAGE = re.compile(
    r"\b(?:medical|clinical|diagnos(?:e|is|tic)?|patient|doctor)\b", re.I
)
SAFETY_VISIBLE_LANGUAGE = re.compile(r"\b(?:emergency|safety(?:-critical)?)\b", re.I)
WELLNESS_VISIBLE_LANGUAGE = re.compile(
    r"\b(?:wellness|wellbeing|well-being|coaching)\b", re.I
)
NUMERICAL_TELEMETRY_PROHIBITION = re.compile(
    r"\bno\b[^.]{0,80}\b(?:numeric|numerical)\s+telemetry\b", re.I
)
HYPERFRAMES_VERSION = re.compile(
    r"\bhyperframes@([0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?)\b"
)


class VisibleTextParser(HTMLParser):
    """Collect authored renderable text while excluding non-rendering containers."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._non_rendering_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"style", "script", "template", "title", "noscript"}:
            self._non_rendering_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"style", "script", "template", "title", "noscript"}:
            self._non_rendering_depth = max(0, self._non_rendering_depth - 1)

    def handle_data(self, data: str) -> None:
        if not self._non_rendering_depth and data.strip():
            self.parts.append(data.strip())

    @property
    def text(self) -> str:
        return " ".join(self.parts)


def _append_contract(errors: list[str], exc: ContractError) -> None:
    errors.extend(exc.errors)


def _error(path: Path, field: str, message: str, repository_root: Path) -> str:
    return f"{display_path(path, repository_root)}:{field}: {message}"


def _read_bytes(path: Path, errors: list[str], repository_root: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError as exc:
        errors.append(_error(path, "file", f"cannot read: {exc}", repository_root))
        return None


def _load_json(path: Path, errors: list[str], repository_root: Path) -> Any:
    try:
        return load_json_document(path, repository_root)
    except ContractError as exc:
        _append_contract(errors, exc)
        return None


def _normalize_visible(text: str) -> str:
    return re.sub(r"\s+", " ", text).replace("’", "'").strip()


def _number_text(value: Any) -> str:
    if type(value) is int or (type(value) is float and value.is_integer()):
        return str(int(value))
    return format(float(value), ".12g")


def _contains_number(source: str, value: Any) -> bool:
    token = re.escape(_number_text(value))
    return re.search(rf"(?<![0-9.]){token}(?![0-9.])", source) is not None


def _css_block(html: str, selector: str) -> str | None:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}", html, re.S)
    return match.group("body") if match else None


def _css_property_matches(block: str, property_name: str, expected: str) -> bool:
    return (
        re.search(
            rf"(?:^|;)\s*{re.escape(property_name)}\s*:\s*{re.escape(expected)}\s*(?:!important\s*)?(?:;|$)",
            block,
            re.I | re.M,
        )
        is not None
    )


def _manifest_asset_references(html: str) -> set[str]:
    references: set[str] = set()
    patterns = (
        r"(?:src|href)\s*=\s*[\"'](?P<path>/assets/[^\"'#?]+)",
        r"url\(\s*[\"']?(?P<path>/assets/[^\"')#?]+)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, html, re.I):
            references.add(match.group("path").lstrip("/"))
    return references


def _validate_html(
    project: ProjectSpec,
    html: str,
    frame: Mapping[str, Any],
    brief: Mapping[str, Any],
    manifested_assets: set[str],
    errors: list[str],
    repository_root: Path,
) -> None:
    html_path = project.path("root_html_file")
    prefix = display_path(html_path, repository_root)
    parser = VisibleTextParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # HTMLParser can surface malformed entity/state errors.
        errors.append(f"{prefix}:html: cannot parse authored HTML: {exc}")
        return
    visible = _normalize_visible(parser.text)
    visible_folded = visible.casefold()

    language = brief["language"]
    if (
        re.search(
            rf"<html\b[^>]*\blang\s*=\s*[\"']{re.escape(language)}[\"']", html, re.I
        )
        is None
    ):
        errors.append(f"{prefix}:html.lang: expected {language!r}")

    canvas = frame["canvas"]
    attributes = {
        "data-composition-id": project.project_id,
        "data-start": "0",
        "data-duration": _number_text(frame["duration_s"]),
        "data-fps": _number_text(frame["source_fps"]),
        "data-width": _number_text(canvas["width_px"]),
        "data-height": _number_text(canvas["height_px"]),
    }
    for attribute, expected in attributes.items():
        if (
            re.search(
                rf"\b{re.escape(attribute)}\s*=\s*[\"']{re.escape(expected)}[\"']", html
            )
            is None
        ):
            errors.append(f"{prefix}:html.{attribute}: expected {expected!r}")
    if re.search(r"\bclass\s*=\s*[\"'][^\"']*\bclip\b", html) is None:
        errors.append(f"{prefix}:html.class: missing .clip timeline element")

    family = frame["typography"]["family"]
    family_pattern = rf"(?:[\"']{re.escape(family)}[\"']|{re.escape(family)})"
    if (
        re.search(rf"font-family\s*:\s*{family_pattern}\s*,\s*sans-serif", html, re.I)
        is None
    ):
        errors.append(
            f"{prefix}:typography.family: expected direct {family!r} sans-serif stack"
        )
    if (
        re.search(
            rf"@font-face\s*\{{[^}}]*font-family\s*:\s*{family_pattern}",
            html,
            re.I | re.S,
        )
        is None
    ):
        errors.append(
            f"{prefix}:typography.family: missing local @font-face declaration"
        )

    if '<script src="/assets/gsap.min.js"></script>' not in html and not re.search(
        r"<script\s+src\s*=\s*['\"]/assets/gsap\.min\.js['\"]\s*></script>", html, re.I
    ):
        errors.append(f"{prefix}:assets: must load the pinned local GSAP asset")
    if EXTERNAL_RESOURCE.search(html) or "http://" in html or "https://" in html:
        errors.append(
            f"{prefix}:assets: composition must not depend on external network resources"
        )
    for reference in sorted(_manifest_asset_references(html)):
        if reference not in manifested_assets:
            errors.append(
                f"{prefix}:assets: referenced local asset is absent from manifest: {reference}"
            )
    if "assets/gsap.min.js" not in manifested_assets:
        errors.append(f"{prefix}:assets: manifest must pin assets/gsap.min.js")
    if not any(path.endswith(".woff2") for path in manifested_assets):
        errors.append(f"{prefix}:assets: manifest must pin a local WOFF2 font")

    for token_name, token in frame["palette"].items():
        if token.casefold() not in html.casefold():
            errors.append(
                f"{prefix}:palette.{token_name}: missing projected token {token}"
            )

    hook = _css_block(html, "#hook")
    if hook is None:
        errors.append(f"{prefix}:hook: missing #hook CSS rule")
    else:
        hook_expectations = {
            "top": f"{frame['hook']['top_px']}px",
            "left": f"{frame['hook']['left_px']}px",
            "width": f"{frame['hook']['width_px']}px",
            "font-size": f"{frame['typography']['hook_size_px']}px",
            "font-weight": str(frame["typography"]["hook_weight"]),
            "line-height": _number_text(frame["typography"]["hook_line_height"]),
        }
        for property_name, expected in hook_expectations.items():
            if not _css_property_matches(hook, property_name, expected):
                errors.append(
                    f"{prefix}:hook.{property_name}: expected frame projection {expected}"
                )

    card_width = f"{frame['card']['width_px']}px"
    card_border = f"{frame['card']['border_px']}px"
    card_projection = False
    for selector, block in re.findall(r"([^{}]+)\{([^{}]*)\}", html, re.S):
        if "#hook" in selector:
            continue
        if _css_property_matches(block, "width", card_width) and re.search(
            rf"\bborder\s*:\s*{re.escape(card_border)}\s+solid\b", block, re.I
        ):
            card_projection = True
            break
    if not card_projection:
        errors.append(
            f"{prefix}:card: missing proof-card projection with width {card_width} and border {card_border}"
        )

    treatments = set(frame["forbidden_treatments"])
    for label, pattern in BANNED_SOURCE.items():
        if pattern.search(html):
            errors.append(f"{prefix}:html.safety: prohibited {label}")
    if "gradients" in treatments and GRADIENT_SOURCE.search(html):
        errors.append(f"{prefix}:html.safety: prohibited gradient")
    script_text = "\n".join(
        re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.I | re.S)
    )
    if LAYOUT_TWEEN.search(script_text):
        errors.append(f"{prefix}:html.safety: prohibited layout tween")
    if "medical_language" in treatments and MEDICAL_VISIBLE_LANGUAGE.search(visible):
        errors.append(f"{prefix}:visible_copy: prohibited medical language")
    if "safety_language" in treatments and SAFETY_VISIBLE_LANGUAGE.search(visible):
        errors.append(f"{prefix}:visible_copy: prohibited safety language")
    if "generic_wellness_imagery" in treatments and WELLNESS_VISIBLE_LANGUAGE.search(
        visible
    ):
        errors.append(f"{prefix}:visible_copy: prohibited generic wellness language")

    truth = brief["truth"]
    for index, phrase in enumerate(truth["visible_required"]):
        normalized = _normalize_visible(phrase).casefold()
        if normalized not in visible_folded:
            errors.append(
                f"{prefix}:visible_copy: missing required phrase {phrase!r} "
                f"(BRIEF.md truth.visible_required[{index}])"
            )
    for index, phrase in enumerate(truth["visible_forbidden"]):
        normalized = _normalize_visible(phrase).casefold()
        if normalized in visible_folded:
            errors.append(
                f"{prefix}:visible_copy: prohibited phrase {phrase!r} "
                f"(BRIEF.md truth.visible_forbidden[{index}])"
            )
    if NUMERICAL_TELEMETRY_PROHIBITION.search(
        " ".join(truth["qualifiers"])
    ) and re.search(r"\b\d+(?:[.,]\d+)?\b", visible):
        errors.append(
            f"{prefix}:visible_copy: numerical telemetry is prohibited by the episode qualifier"
        )

    if "gsap.timeline" not in html or re.search(r"paused\s*:\s*true", html) is None:
        errors.append(f"{prefix}:timeline: timeline must be a paused GSAP timeline")
    direct_registry = (
        f'window.__timelines["{project.project_id}"]' in script_text
        or f"window.__timelines['{project.project_id}']" in script_text
    )
    variable_registry = re.search(
        rf"\bconst\s+([A-Za-z_$][\w$]*)\s*=\s*[\"']{re.escape(project.project_id)}[\"']",
        script_text,
    )
    variable_registry_ok = bool(
        variable_registry
        and f"window.__timelines[{variable_registry.group(1)}]" in script_text
    )
    if not (direct_registry or variable_registry_ok):
        errors.append(
            f"{prefix}:timeline.registry: key must equal composition id {project.project_id!r}"
        )
    if re.search(r"\.seek\s*\(\s*0(?:\.0+)?\s*\)", script_text) is None:
        errors.append(
            f"{prefix}:timeline.seek: timeline must be normalized with seek(0)"
        )
    for field in ("motion_start_s", "return_start_s", "return_complete_by_s"):
        marker = frame["timing"][field]
        if not _contains_number(script_text, marker):
            errors.append(
                f"{prefix}:timing.{field}: missing projected marker {_number_text(marker)}s"
            )


def _validate_manifested_text_assets(
    project: ProjectSpec,
    manifested_assets: set[str],
    frame: Mapping[str, Any],
    errors: list[str],
    repository_root: Path,
) -> None:
    treatments = set(frame["forbidden_treatments"])
    for relative in sorted(manifested_assets):
        path = project.base_dir / relative
        if path.suffix.lower() in AUDIO_SUFFIXES and frame["silent"]:
            errors.append(
                _error(
                    path,
                    "asset",
                    "audio asset is prohibited by silent profile",
                    repository_root,
                )
            )
        if path.suffix.lower() == ".svg" and "gradients" in treatments:
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                errors.append(
                    _error(path, "asset", f"cannot inspect SVG: {exc}", repository_root)
                )
                continue
            if re.search(r"<(?:linear|radial)Gradient\b|\burl\s*\(", source, re.I):
                errors.append(
                    _error(
                        path,
                        "asset",
                        "SVG uses prohibited gradient or paint URL",
                        repository_root,
                    )
                )


def _validate_shot_plan(
    project: ProjectSpec,
    frame: Mapping[str, Any],
    errors: list[str],
    repository_root: Path,
) -> None:
    path = project.path("shot_plan_file")
    shot = _load_json(path, errors, repository_root)
    if not isinstance(shot, dict):
        if shot is not None:
            errors.append(
                _error(path, "document", "expected JSON object", repository_root)
            )
        return
    # Shot plans intentionally remain heterogeneous.  Only these common
    # projections are contractual; episode-specific beats/content stay free.
    expected = {
        "category": "kinetic-type",
        "duration_s": frame["duration_s"],
        "fps": frame["source_fps"],
        "canvas": {
            "w": frame["canvas"]["width_px"],
            "h": frame["canvas"]["height_px"],
            "aspect": frame["canvas"]["aspect"],
        },
        "palette": palette_values(frame),
        "font": frame["typography"]["family"],
    }
    for field, value in expected.items():
        if shot.get(field) != value:
            errors.append(
                _error(
                    path, field, f"expected frame projection {value!r}", repository_root
                )
            )


def _validate_motion(
    project: ProjectSpec,
    frame: Mapping[str, Any],
    errors: list[str],
    repository_root: Path,
) -> None:
    path = project.path("root_motion_file")
    motion = _load_json(path, errors, repository_root)
    if not isinstance(motion, dict):
        if motion is not None:
            errors.append(
                _error(path, "document", "expected JSON object", repository_root)
            )
        return
    if motion.get("duration") != frame["duration_s"]:
        errors.append(
            _error(
                path, "duration", f"expected {frame['duration_s']!r}", repository_root
            )
        )
    assertions = motion.get("assertions")
    if not isinstance(assertions, list):
        errors.append(_error(path, "assertions", "expected list", repository_root))
        return
    entries = [entry for entry in assertions if isinstance(entry, dict)]
    if len(entries) != len(assertions):
        errors.append(
            _error(
                path, "assertions", "every assertion must be an object", repository_root
            )
        )
    kinds = [entry.get("kind") for entry in entries]
    for kind in REQUIRED_MOTION_ASSERTIONS:
        if kind not in kinds:
            errors.append(
                _error(
                    path,
                    "assertions",
                    f"missing motion assertion {kind!r}",
                    repository_root,
                )
            )

    appears = [entry for entry in entries if entry.get("kind") == "appearsBy"]

    def numeric(value: Any) -> bool:
        return (
            type(value) in {int, float}
            and value == value
            and value not in {float("inf"), float("-inf")}
        )

    hook_ok = any(
        entry.get("selector") == "#hook"
        and numeric(entry.get("bySec"))
        and 0 <= float(entry["bySec"]) <= float(frame["timing"]["opening_hold_s"])
        for entry in appears
    )
    if not hook_ok:
        errors.append(
            _error(
                path,
                "assertions.appearsBy",
                f"#hook must appear by {frame['timing']['opening_hold_s']}s",
                repository_root,
            )
        )
    payoff_ok = any(
        entry.get("selector") != "#hook"
        and isinstance(entry.get("selector"), str)
        and numeric(entry.get("bySec"))
        and 0 <= float(entry["bySec"]) <= float(frame["timing"]["payoff_by_s"])
        for entry in appears
    )
    if not payoff_ok:
        errors.append(
            _error(
                path,
                "assertions.appearsBy",
                f"a non-hook payoff must appear by {frame['timing']['payoff_by_s']}s",
                repository_root,
            )
        )
    moving = [entry for entry in entries if entry.get("kind") == "keepsMoving"]
    hold_window = float(frame["timing"]["return_start_s"]) - float(
        frame["timing"]["payoff_by_s"]
    )
    motion_ok = any(
        numeric(entry.get("maxStaticSec"))
        and hold_window - 1e-9
        <= float(entry["maxStaticSec"])
        <= hold_window + 0.25 + 1e-9
        for entry in moving
    )
    if not motion_ok:
        errors.append(
            _error(
                path,
                "assertions.keepsMoving.maxStaticSec",
                f"expected {hold_window:g}..{hold_window + 0.25:g}s for the deliberate payoff hold",
                repository_root,
            )
        )


def _validate_package_and_metadata(
    project: ProjectSpec,
    errors: list[str],
    repository_root: Path,
) -> None:
    meta_path = project.path("meta_file")
    meta = _load_json(meta_path, errors, repository_root)
    if isinstance(meta, dict):
        if meta.get("id") != project.project_id:
            errors.append(
                _error(
                    meta_path, "id", f"expected {project.project_id!r}", repository_root
                )
            )
        if not isinstance(meta.get("name"), str) or not meta["name"].strip():
            errors.append(
                _error(meta_path, "name", "expected non-empty string", repository_root)
            )
    elif meta is not None:
        errors.append(
            _error(meta_path, "document", "expected JSON object", repository_root)
        )

    package_path = project.path("package_file")
    package = _load_json(package_path, errors, repository_root)
    if isinstance(package, dict):
        if package.get("name") != project.project_id:
            errors.append(
                _error(
                    package_path,
                    "name",
                    f"expected {project.project_id!r}",
                    repository_root,
                )
            )
        scripts = package.get("scripts")
        if not isinstance(scripts, dict):
            errors.append(
                _error(package_path, "scripts", "expected object", repository_root)
            )
        else:
            versions: set[str] = set()
            for name in REQUIRED_PACKAGE_SCRIPTS:
                command = scripts.get(name)
                match = (
                    HYPERFRAMES_VERSION.search(command)
                    if isinstance(command, str)
                    else None
                )
                if match is None:
                    errors.append(
                        _error(
                            package_path,
                            f"scripts.{name}",
                            "must pin hyperframes@<semantic-version>",
                            repository_root,
                        )
                    )
                else:
                    versions.add(match.group(1))
            if len(versions) > 1:
                errors.append(
                    _error(
                        package_path,
                        "scripts",
                        f"HyperFrames pins disagree: {sorted(versions)!r}",
                        repository_root,
                    )
                )
    elif package is not None:
        errors.append(
            _error(package_path, "document", "expected JSON object", repository_root)
        )

    hyperframes_path = project.path("hyperframes_file")
    hyperframes = _load_json(hyperframes_path, errors, repository_root)
    if not isinstance(hyperframes, dict) and hyperframes is not None:
        errors.append(
            _error(
                hyperframes_path, "document", "expected JSON object", repository_root
            )
        )


def validate_project_source(
    project: ProjectSpec,
    repository_root: Path,
    *,
    allow_empty_visible_forbidden: bool = False,
    verify_git_truth: bool = True,
) -> list[str]:
    """Validate one project without requiring or writing generated output."""

    root = repository_root.resolve(strict=False)
    errors: list[str] = []
    frame: Mapping[str, Any] | None = None
    brief: Mapping[str, Any] | None = None
    manifested_assets: set[str] = set()

    try:
        frame = load_frame_contract(project.path("profile_file"), root)
    except ContractError as exc:
        _append_contract(errors, exc)
    if frame is not None:
        try:
            brief = load_brief_contract(project.path("brief_file"), root, frame)
        except ContractError as exc:
            _append_contract(errors, exc)
    try:
        manifested_assets = verify_asset_manifest(project, root)
    except ContractError as exc:
        _append_contract(errors, exc)

    if brief is not None and not allow_empty_visible_forbidden:
        if not brief["truth"]["visible_forbidden"]:
            errors.append(
                _error(
                    project.path("brief_file"),
                    "truth.visible_forbidden",
                    "managed episodes require a non-empty list; only standalone fixtures may use []",
                    root,
                )
            )

    if brief is not None and verify_git_truth:
        try:
            validate_repository_truth(brief, project.path("brief_file"), root)
        except ContractError as exc:
            _append_contract(errors, exc)

    root_html = _read_bytes(project.path("root_html_file"), errors, root)
    composition_html = _read_bytes(project.path("composition_html_file"), errors, root)
    if (
        root_html is not None
        and composition_html is not None
        and root_html != composition_html
    ):
        errors.append(
            _error(
                project.path("composition_html_file"),
                "parity",
                f"must be byte-identical to {display_path(project.path('root_html_file'), root)}",
                root,
            )
        )
    root_motion = _read_bytes(project.path("root_motion_file"), errors, root)
    composition_motion = _read_bytes(
        project.path("composition_motion_file"), errors, root
    )
    if (
        root_motion is not None
        and composition_motion is not None
        and root_motion != composition_motion
    ):
        errors.append(
            _error(
                project.path("composition_motion_file"),
                "parity",
                f"must be byte-identical to {display_path(project.path('root_motion_file'), root)}",
                root,
            )
        )

    html: str | None = None
    if root_html is not None:
        try:
            html = root_html.decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(
                _error(
                    project.path("root_html_file"),
                    "encoding",
                    f"expected UTF-8: {exc}",
                    root,
                )
            )
    if html is not None and frame is not None and brief is not None:
        _validate_html(project, html, frame, brief, manifested_assets, errors, root)
    if frame is not None:
        _validate_manifested_text_assets(
            project, manifested_assets, frame, errors, root
        )
        _validate_shot_plan(project, frame, errors, root)
        _validate_motion(project, frame, errors, root)
    _validate_package_and_metadata(project, errors, root)
    return errors


def validate_template_source(repository_root: Path) -> list[str]:
    """Guard the copyable shell without treating placeholders as an episode."""

    root = repository_root.resolve(strict=False)
    errors: list[str] = []
    for relative in TEMPLATE_REQUIRED_FILES:
        path = TEMPLATE_ROOT / relative
        if not path.is_file():
            errors.append(
                _error(path, "file", "required template file is missing", root)
            )

    for source_relative, projection_relative in (
        ("index.html", "compositions/index.html"),
        ("index.motion.json", "compositions/index.motion.json"),
    ):
        source = TEMPLATE_ROOT / source_relative
        projection = TEMPLATE_ROOT / projection_relative
        if source.is_file() and projection.is_file():
            if source.read_bytes() != projection.read_bytes():
                errors.append(
                    _error(
                        projection,
                        "parity",
                        f"must be byte-identical to {display_path(source, root)}",
                        root,
                    )
                )

    text_paths = [
        TEMPLATE_ROOT / relative
        for relative in TEMPLATE_REQUIRED_FILES
        if Path(relative).suffix.lower() in {".md", ".json", ".html"}
    ]
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in text_paths if path.is_file()
    )
    for placeholder in (
        "replace-me",
        "claim:",
        "opening_state:",
        "payoff_state:",
        "motion_verb:",
        "uncertainty:",
        "source_refs:",
    ):
        if placeholder not in combined:
            errors.append(
                _error(
                    TEMPLATE_ROOT,
                    "placeholders",
                    f"copyable template is missing {placeholder!r}",
                    root,
                )
            )
    if re.search(r"\b(?:SleepRadar|Aqara)\b", combined, re.I):
        errors.append(
            _error(
                TEMPLATE_ROOT,
                "portability",
                "generic template must not contain product-specific claims",
                root,
            )
        )
    return errors


def _copy_fixture(repository_root: Path) -> tuple[Path, Path]:
    fixture = repository_root / "videos" / "fixtures" / "quiet-proof-loops-minimal"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURE_ROOT, fixture)
    return repository_root, fixture


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _exercise_fixture(
    label: str,
    mutate: Callable[[Path, Path], None] | None,
    *,
    expected_failure: str | None = None,
    allow_empty_visible_forbidden: bool = True,
) -> None:
    with tempfile.TemporaryDirectory(
        prefix="quiet-proof-loops-self-test-"
    ) as temporary:
        root, fixture = _copy_fixture(Path(temporary))
        if mutate is not None:
            mutate(root, fixture)
        failures: list[str] = []
        try:
            project = load_fixture(root, fixture)
        except ContractError as exc:
            failures.extend(exc.errors)
        else:
            failures.extend(
                validate_project_source(
                    project,
                    root,
                    allow_empty_visible_forbidden=allow_empty_visible_forbidden,
                    verify_git_truth=False,
                )
            )
        joined = "\n".join(failures)
        if expected_failure is None and failures:
            raise RuntimeError(f"self-test {label!r} unexpectedly failed:\n{joined}")
        if (
            expected_failure is not None
            and expected_failure.casefold() not in joined.casefold()
        ):
            raise RuntimeError(
                f"self-test {label!r} did not catch {expected_failure!r}; failures were:\n{joined or '<none>'}"
            )


def _replace_text(path: Path, old: str, new: str) -> None:
    source = path.read_text(encoding="utf-8")
    if old not in source:
        raise RuntimeError(f"self-test mutation anchor missing in {path}: {old!r}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def check_published_registration(
    published_ids: Sequence[str], registered_ids: Sequence[str]
) -> list[str]:
    """Every published pair must be a registered project or a pinned legacy id."""

    registered = set(registered_ids)
    return [
        f"assets/feature-gifs/{project_id}: published pair has no entry in "
        "videos/projects.json and is not a pinned legacy project"
        for project_id in sorted(set(published_ids))
        if project_id not in registered
        and project_id not in LEGACY_UNMANAGED_PROJECT_IDS
    ]


def self_test() -> None:
    """Run positive and mutation tests over the portable fixture."""

    baseline_lines = ["heading", "evidence one", "evidence two", "footer"]
    moved_lines = ["new introduction", *baseline_lines]
    if not source_ref_content_matches_baseline(moved_lines, baseline_lines, "3", "4"):
        raise RuntimeError(
            "source-reference self-test rejected unchanged evidence after a line move"
        )
    changed_lines = moved_lines.copy()
    changed_lines[3] = "changed evidence"
    if source_ref_content_matches_baseline(changed_lines, baseline_lines, "3", "4"):
        raise RuntimeError(
            "source-reference self-test accepted changed evidence after a line move"
        )
    rebound_lines = ["evidence two", "footer"]
    if source_ref_content_matches_baseline(rebound_lines, baseline_lines, "1", "2"):
        raise RuntimeError(
            "source-reference self-test accepted a citation rebound to other "
            "baseline content after the cited evidence was removed"
        )

    if not check_published_registration(
        ["sleepradar-rogue-clip"], ["sleepradar-live-now-card"]
    ):
        raise RuntimeError(
            "published-registration self-test accepted an unregistered pair"
        )
    if check_published_registration(
        ["sleepradar-live-now-card", *LEGACY_UNMANAGED_PROJECT_IDS],
        ["sleepradar-live-now-card"],
    ):
        raise RuntimeError(
            "published-registration self-test rejected registered and legacy pairs"
        )

    template_errors = validate_template_source(REPOSITORY_ROOT)
    if template_errors:
        raise RuntimeError(
            "copyable template self-test failed:\n" + "\n".join(template_errors)
        )
    if not FIXTURE_ROOT.is_dir():
        raise RuntimeError(f"self-test fixture is missing: {FIXTURE_ROOT}")

    _exercise_fixture("clean portable fixture", None)
    _exercise_fixture(
        "managed empty forbidden list",
        None,
        expected_failure="managed episodes require a non-empty list",
        allow_empty_visible_forbidden=False,
    )

    def duplicate_frame_key(root: Path, fixture: Path) -> None:
        del root
        _replace_text(
            fixture / "frame.md", "duration_s: 6\n", "duration_s: 6\nduration_s: 6\n"
        )

    _exercise_fixture(
        "duplicate YAML key", duplicate_frame_key, expected_failure="duplicate key"
    )

    def unknown_nested_frame_key(root: Path, fixture: Path) -> None:
        del root
        _replace_text(
            fixture / "frame.md",
            '  aspect: "9:16"\n',
            '  aspect: "9:16"\n  invented_dimension: 1\n',
        )

    _exercise_fixture(
        "unknown nested frame key",
        unknown_nested_frame_key,
        expected_failure="unknown key",
    )

    def missing_frontmatter_close(root: Path, fixture: Path) -> None:
        del root
        _replace_text(
            fixture / "frame.md", "\n---\n\n# Fixture profile", "\n\n# Fixture profile"
        )

    _exercise_fixture(
        "malformed front matter",
        missing_frontmatter_close,
        expected_failure="missing closing",
    )

    def timing_contradiction(root: Path, fixture: Path) -> None:
        del root
        _replace_text(
            fixture / "frame.md", "  return_start_s: 5.2", "  return_start_s: 2.0"
        )

    _exercise_fixture(
        "timing contradiction", timing_contradiction, expected_failure="timing"
    )

    def budget_contradiction(root: Path, fixture: Path) -> None:
        del root
        _replace_text(
            fixture / "frame.md",
            "  hard_ceiling_bytes: 1000000",
            "  hard_ceiling_bytes: 600000",
        )

    _exercise_fixture(
        "budget contradiction", budget_contradiction, expected_failure="target_bytes"
    )

    def yaml_alias(root: Path, fixture: Path) -> None:
        del root
        _replace_text(
            fixture / "frame.md",
            "profile: midnight-console",
            "profile: &profile midnight-console\nsystem_copy: *profile",
        )

    _exercise_fixture(
        "YAML alias", yaml_alias, expected_failure="aliases are not allowed"
    )

    def duplicate_brief_key(root: Path, fixture: Path) -> None:
        del root
        _replace_text(
            fixture / "BRIEF.md",
            'claim: "A deterministic source can reveal one concrete state and return exactly."\n',
            'claim: "A deterministic source can reveal one concrete state and return exactly."\n'
            'claim: "Duplicate claim."\n',
        )

    _exercise_fixture(
        "duplicate brief key", duplicate_brief_key, expected_failure="duplicate key"
    )

    def unknown_truth_key(root: Path, fixture: Path) -> None:
        del root
        _replace_text(
            fixture / "BRIEF.md",
            '  release_tag: "fixture-v1"\n',
            '  release_tag: "fixture-v1"\n  claim_override: "not allowed"\n',
        )

    _exercise_fixture(
        "unknown brief truth key", unknown_truth_key, expected_failure="unknown key"
    )

    def invalid_truth_source(root: Path, fixture: Path) -> None:
        del root
        _replace_text(
            fixture / "BRIEF.md",
            '    - "videos/fixtures/quiet-proof-loops-minimal/README.md:1-8"',
            '    - "../outside.md:1"',
        )

    _exercise_fixture(
        "truth source containment",
        invalid_truth_source,
        expected_failure="repository-root-relative",
    )

    def truth_line_overflow(root: Path, fixture: Path) -> None:
        del root
        _replace_text(
            fixture / "BRIEF.md",
            '    - "videos/fixtures/quiet-proof-loops-minimal/README.md:1-8"',
            '    - "videos/fixtures/quiet-proof-loops-minimal/README.md:1-999"',
        )

    _exercise_fixture(
        "truth source line range",
        truth_line_overflow,
        expected_failure="exceeds",
    )

    def adapter_escape(root: Path, fixture: Path) -> None:
        del root
        adapter = json.loads((fixture / "adapter.json").read_text(encoding="utf-8"))
        adapter["root_html_file"] = "../../../../outside.html"
        _write_json(fixture / "adapter.json", adapter)

    _exercise_fixture(
        "adapter path containment", adapter_escape, expected_failure="escapes"
    )

    def adapter_source_overwrite(root: Path, fixture: Path) -> None:
        del root
        adapter = json.loads((fixture / "adapter.json").read_text(encoding="utf-8"))
        adapter["verification_file"] = "BRIEF.md"
        _write_json(fixture / "adapter.json", adapter)

    _exercise_fixture(
        "adapter output source overwrite",
        adapter_source_overwrite,
        expected_failure="must not overwrite a source file",
    )

    def adapter_generated_output_collision(root: Path, fixture: Path) -> None:
        del root
        adapter = json.loads((fixture / "adapter.json").read_text(encoding="utf-8"))
        adapter["verification_file"] = "renders/quiet-proof-loops-minimal.gif"
        _write_json(fixture / "adapter.json", adapter)

    _exercise_fixture(
        "adapter generated-output collision",
        adapter_generated_output_collision,
        expected_failure="generated-output collisions",
    )

    def adapter_source_root_output(root: Path, fixture: Path) -> None:
        del root
        adapter = json.loads((fixture / "adapter.json").read_text(encoding="utf-8"))
        adapter["render_dir"] = "."
        _write_json(fixture / "adapter.json", adapter)

    _exercise_fixture(
        "adapter source root output",
        adapter_source_root_output,
        expected_failure="must not be the project source root",
    )

    def stale_asset_digest(root: Path, fixture: Path) -> None:
        del root
        manifest = json.loads(
            (fixture / "assets/manifest.json").read_text(encoding="utf-8")
        )
        manifest["assets"][0]["sha256"] = "0" * 64
        _write_json(fixture / "assets/manifest.json", manifest)

    _exercise_fixture(
        "stale asset digest", stale_asset_digest, expected_failure="digest mismatch"
    )

    def duplicate_json_key(root: Path, fixture: Path) -> None:
        del root
        _replace_text(
            fixture / "assets/manifest.json",
            '  "schema_version": 1,',
            '  "schema_version": 1,\n  "schema_version": 1,',
        )

    _exercise_fixture(
        "duplicate JSON key", duplicate_json_key, expected_failure="duplicate key"
    )

    def html_parity(root: Path, fixture: Path) -> None:
        del root
        path = fixture / "compositions/index.html"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    _exercise_fixture("HTML parity", html_parity, expected_failure="byte-identical")

    def token_drift(root: Path, fixture: Path) -> None:
        del root
        for relative in ("index.html", "compositions/index.html"):
            _replace_text(fixture / relative, "font-size: 54px", "font-size: 55px")

    _exercise_fixture(
        "frame token drift", token_drift, expected_failure="hook.font-size"
    )

    def missing_visible_copy(root: Path, fixture: Path) -> None:
        del root
        for relative in ("index.html", "compositions/index.html"):
            path = fixture / relative
            source = path.read_text(encoding="utf-8")
            path.write_text(source.replace(">Ready<", ">Done<"), encoding="utf-8")

    _exercise_fixture(
        "visible copy mutation",
        missing_visible_copy,
        expected_failure="missing required phrase 'Ready'",
    )

    def unsafe_randomness(root: Path, fixture: Path) -> None:
        del root
        for relative in ("index.html", "compositions/index.html"):
            path = fixture / relative
            source = path.read_text(encoding="utf-8")
            path.write_text(
                source.replace("tl.seek(0);", "Math.random();\n      tl.seek(0);"),
                encoding="utf-8",
            )

    _exercise_fixture(
        "unsafe source mutation",
        unsafe_randomness,
        expected_failure="prohibited randomness",
    )

    def motion_payoff_drift(root: Path, fixture: Path) -> None:
        del root
        for relative in ("index.motion.json", "compositions/index.motion.json"):
            path = fixture / relative
            motion = json.loads(path.read_text(encoding="utf-8"))
            next(
                entry
                for entry in motion["assertions"]
                if entry.get("kind") == "appearsBy"
                and entry.get("selector") == "#payoff"
            )["bySec"] = 5
            _write_json(path, motion)

    _exercise_fixture(
        "motion assertion drift",
        motion_payoff_drift,
        expected_failure="payoff must appear",
    )

    managed_registry = load_project_registry(REPOSITORY_ROOT)
    managed_project = managed_registry.projects[0]
    managed_frame = load_frame_contract(
        managed_project.path("profile_file"), REPOSITORY_ROOT
    )
    managed_brief = load_brief_contract(
        managed_project.path("brief_file"), REPOSITORY_ROOT, managed_frame
    )
    validate_repository_truth(
        managed_brief, managed_project.path("brief_file"), REPOSITORY_ROOT
    )

    def expect_truth_failure(
        label: str, brief: Mapping[str, Any], expected: str
    ) -> None:
        try:
            validate_repository_truth(
                brief, managed_project.path("brief_file"), REPOSITORY_ROOT
            )
        except ContractError as exc:
            if expected.casefold() not in str(exc).casefold():
                raise RuntimeError(
                    f"repository truth self-test {label!r} returned wrong failure: {exc}"
                ) from exc
        else:
            raise RuntimeError(
                f"repository truth self-test {label!r} did not fail closed"
            )

    fabricated_commit = copy.deepcopy(managed_brief)
    fabricated_commit["truth"]["baseline_commit"] = "f" * 40
    expect_truth_failure(
        "fabricated baseline commit", fabricated_commit, "does not exist"
    )
    fabricated_tag = copy.deepcopy(managed_brief)
    fabricated_tag["truth"]["release_tag"] = "not-a-real-release-tag"
    expect_truth_failure("fabricated release tag", fabricated_tag, "does not exist")
    stale_evidence = copy.deepcopy(managed_brief)
    stale_evidence["truth"]["source_refs"] = ["videos/README.md:1"]
    expect_truth_failure(
        "evidence absent from baseline", stale_evidence, "did not exist at baseline"
    )

    with tempfile.TemporaryDirectory(
        prefix="quiet-proof-loops-baseline-test-"
    ) as temporary:
        root, fixture = _copy_fixture(Path(temporary))
        project = load_fixture(root, fixture)
        published = root / "assets" / "feature-gifs"
        published.mkdir(parents=True)
        gif = published / f"{project.project_id}.gif"
        mp4 = published / f"{project.project_id}.mp4"
        gif.write_bytes(b"GIF89a-self-test")
        mp4.write_bytes(b"mp4-self-test")
        baseline = {
            "schema_version": 1,
            "projects": {
                project.project_id: {
                    "gif_path": gif.relative_to(root).as_posix(),
                    "gif_sha256": sha256_file(gif),
                    "mp4_path": mp4.relative_to(root).as_posix(),
                    "mp4_sha256": sha256_file(mp4),
                }
            },
        }
        published_ids = discover_published_project_ids(
            root,
            binary_root=published,
        )
        if published_ids != (project.project_id,):
            raise RuntimeError(
                "published-binary discovery self-test returned the wrong project set"
            )
        generated_baseline = build_baseline_data(
            published_ids,
            root,
            binary_root=published,
        )
        if generated_baseline != baseline:
            raise RuntimeError(
                "published-binary baseline generation self-test returned the wrong paths"
            )
        validate_baseline_data(
            baseline,
            root / "baseline.json",
            root,
            allowed_project_ids=[project.project_id],
            required_project_ids=[project.project_id],
        )
        stale = copy.deepcopy(baseline)
        stale["projects"][project.project_id]["gif_sha256"] = "0" * 64
        try:
            validate_baseline_data(
                stale,
                root / "baseline.json",
                root,
                allowed_project_ids=[project.project_id],
                required_project_ids=[project.project_id],
            )
        except ContractError as exc:
            if "digest mismatch" not in str(exc):
                raise RuntimeError(
                    f"baseline stale-digest self-test returned wrong failure: {exc}"
                ) from exc
        else:
            raise RuntimeError("baseline stale-digest self-test did not fail")

        extra = copy.deepcopy(baseline)
        extra["projects"]["unregistered-project"] = copy.deepcopy(
            baseline["projects"][project.project_id]
        )
        try:
            validate_baseline_data(
                extra,
                root / "baseline.json",
                root,
                allowed_project_ids=[project.project_id],
                required_project_ids=[project.project_id],
                verify_files=False,
            )
        except ContractError as exc:
            if "not in the approved published binary set" not in str(exc):
                raise RuntimeError(
                    f"baseline extra-project self-test returned wrong failure: {exc}"
                ) from exc
        else:
            raise RuntimeError("baseline extra-project self-test did not fail")

        baseline_path = root / "baseline.json"
        write_baseline_file(baseline_path, baseline)
        try:
            write_baseline_file(baseline_path, baseline)
        except ContractError as exc:
            if "--replace" not in str(exc):
                raise RuntimeError(
                    f"baseline replacement self-test returned wrong failure: {exc}"
                ) from exc
        else:
            raise RuntimeError("baseline replacement self-test did not fail closed")
        write_baseline_file(baseline_path, baseline, replace=True)

    print("Quiet Proof Loops validator self-test OK")


def _print_failures(errors: Sequence[str]) -> int:
    for error in errors:
        print(f"ERROR: {error}")
    print(f"Quiet Proof Loops validation failed with {len(errors)} error(s)")
    return 1


def _baseline_path(raw: Path) -> Path:
    return raw if raw.is_absolute() else Path.cwd() / raw


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--project", metavar="SLUG", help="validate one registered project"
    )
    selection.add_argument(
        "--fixture", type=Path, metavar="PATH", help="validate one standalone fixture"
    )
    parser.add_argument(
        "--self-test", action="store_true", help="run positive and mutation tests"
    )
    baseline = parser.add_mutually_exclusive_group()
    baseline.add_argument("--write-baseline", type=Path, metavar="PATH")
    baseline.add_argument("--check-baseline", type=Path, metavar="PATH")
    parser.add_argument(
        "--replace", action="store_true", help="allow --write-baseline to replace PATH"
    )
    options = parser.parse_args(argv)

    if options.replace and options.write_baseline is None:
        parser.error("--replace requires --write-baseline")
    if options.fixture is not None and (
        options.write_baseline or options.check_baseline
    ):
        parser.error("--fixture cannot be combined with baseline modes")
    if options.project is not None and (
        options.write_baseline or options.check_baseline
    ):
        parser.error("--project cannot be combined with baseline modes")
    if options.self_test and any(
        (
            options.project,
            options.fixture,
            options.write_baseline,
            options.check_baseline,
            options.replace,
        )
    ):
        parser.error(
            "--self-test cannot be combined with selection or baseline options"
        )

    if options.self_test:
        try:
            self_test()
        except (ContractError, OSError, RuntimeError) as exc:
            return _print_failures(getattr(exc, "errors", (str(exc),)))
        return 0

    if options.fixture is not None:
        try:
            project = load_fixture(REPOSITORY_ROOT, options.fixture)
        except ContractError as exc:
            return _print_failures(exc.errors)
        errors = validate_project_source(
            project,
            REPOSITORY_ROOT,
            allow_empty_visible_forbidden=True,
            verify_git_truth=False,
        )
        if errors:
            return _print_failures(errors)
        print(f"Quiet Proof Loops fixture source validation OK ({project.project_id})")
        return 0

    try:
        registry = load_project_registry(REPOSITORY_ROOT)
        if options.project is not None:
            projects = registry.select(options.project)
        else:
            projects = registry.projects
    except ContractError as exc:
        return _print_failures(exc.errors)

    if options.write_baseline is not None:
        try:
            published_ids = discover_published_project_ids(REPOSITORY_ROOT)
            data = build_baseline_data(published_ids, REPOSITORY_ROOT)
            path = _baseline_path(options.write_baseline)
            write_baseline_file(path, data, replace=options.replace)
        except ContractError as exc:
            return _print_failures(exc.errors)
        print(
            f"Quiet Proof Loops binary baseline written ({len(published_ids)} projects): "
            f"{display_path(path, REPOSITORY_ROOT)}"
        )
        return 0

    if options.check_baseline is not None:
        try:
            published_ids = discover_published_project_ids(REPOSITORY_ROOT)
            registration_errors = check_published_registration(
                published_ids, tuple(registry.by_id)
            )
            if registration_errors:
                return _print_failures(registration_errors)
            path = _baseline_path(options.check_baseline)
            checked = check_baseline_file(
                path,
                REPOSITORY_ROOT,
                allowed_project_ids=published_ids,
                required_project_ids=published_ids,
            )
        except ContractError as exc:
            return _print_failures(exc.errors)
        print(
            f"Quiet Proof Loops binary baseline OK ({len(checked['projects'])} projects): "
            f"{display_path(path, REPOSITORY_ROOT)}"
        )
        return 0

    errors = validate_template_source(REPOSITORY_ROOT)
    for project in projects:
        errors.extend(validate_project_source(project, REPOSITORY_ROOT))
    if errors:
        return _print_failures(errors)
    if options.project:
        print(f"Quiet Proof Loops source validation OK ({options.project})")
    else:
        print(
            f"Quiet Proof Loops managed source validation OK ({len(projects)} projects)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
