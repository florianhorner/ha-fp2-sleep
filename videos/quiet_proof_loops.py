#!/usr/bin/env python3
"""Reusable Quiet Proof Loops contract, registry, and digest primitives.

The module deliberately owns data validation rather than product claims.  A
profile supplies shared video tokens, an episode brief supplies visible truth,
and an adapter supplies contained repository paths.  Callers can therefore
validate a registered episode or a standalone fixture without importing a
SleepRadar-specific Python map.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

import yaml
from yaml.composer import ComposerError
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent
from yaml.nodes import MappingNode


SCHEMA_VERSION = 1
SYSTEM_NAME = "quiet-proof-loops"

FRAME_KEYS = {
    "schema_version",
    "system",
    "profile",
    "canvas",
    "duration_s",
    "source_fps",
    "silent",
    "gif",
    "mp4",
    "palette",
    "typography",
    "hook",
    "card",
    "timing",
    "forbidden_treatments",
}
FRAME_NESTED_KEYS = {
    "canvas": {"width_px", "height_px", "aspect"},
    "gif": {"fps", "target_bytes", "hard_ceiling_bytes", "loop_mode", "endpoint"},
    "mp4": {"fps", "endpoint_ssim_min"},
    "palette": {
        "background",
        "surface",
        "border",
        "text",
        "muted",
        "radar_blue",
        "deep_blue",
        "heart_red",
        "estimate_amber",
        "unknown_gray",
    },
    "typography": {"family", "hook_weight", "hook_size_px", "hook_line_height"},
    "hook": {"left_px", "top_px", "width_px", "max_lines"},
    "card": {"width_px", "radius_px", "border_px"},
    "timing": {
        "motion_start_s",
        "payoff_by_s",
        "payoff_hold_s",
        "return_start_s",
        "return_complete_by_s",
        "opening_hold_s",
    },
}
FORBIDDEN_TREATMENTS = {
    "gradients",
    "invented_telemetry",
    "medical_language",
    "safety_language",
    "generic_wellness_imagery",
    "random_motion",
    "camera_theatrics",
}

BRIEF_KEYS = {
    "schema_version",
    "workflow",
    "flow",
    "storyboard",
    "message",
    "destination",
    "aspect",
    "language",
    "audience",
    "length",
    "angle",
    "narration",
    "claim",
    "opening_state",
    "payoff_state",
    "motion_verb",
    "uncertainty",
    "truth",
}
BRIEF_TRUTH_KEYS = {
    "source_refs",
    "checked_at",
    "baseline_commit",
    "release_tag",
    "qualifiers",
    "visible_required",
    "visible_forbidden",
}
MOTION_VERBS = {"expand", "activate", "resolve", "flow", "cycle"}

REGISTRY_KEYS = {"schema_version", "projects"}
REGISTRY_PROJECT_KEYS = {"id", "adapter", "batch_default"}
ADAPTER_KEYS = {
    "schema_version",
    "project_id",
    "base_dir",
    "profile_file",
    "brief_file",
    "shot_plan_file",
    "root_html_file",
    "composition_html_file",
    "root_motion_file",
    "composition_motion_file",
    "meta_file",
    "package_file",
    "hyperframes_file",
    "asset_manifest",
    "render_dir",
    "verification_file",
}
ADAPTER_PATH_KEYS = ADAPTER_KEYS - {"schema_version", "project_id", "base_dir"}
SOURCE_FILE_KEYS = {
    "profile_file",
    "brief_file",
    "shot_plan_file",
    "root_html_file",
    "composition_html_file",
    "root_motion_file",
    "composition_motion_file",
    "meta_file",
    "package_file",
    "hyperframes_file",
    "asset_manifest",
}
EPISODE_CONTAINED_KEYS = ADAPTER_PATH_KEYS - {"profile_file"}

ASSET_MANIFEST_KEYS = {"schema_version", "assets"}
ASSET_ENTRY_KEYS = {"path", "sha256"}

BASELINE_KEYS = {"schema_version", "projects"}
BASELINE_ENTRY_KEYS = {"gif_path", "gif_sha256", "mp4_path", "mp4_sha256"}

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SOURCE_REF_RE = re.compile(
    r"^(?P<path>[^:\n]+?)(?::(?P<start>[1-9]\d*)(?:-(?P<end>[1-9]\d*))?)?$"
)


class ContractError(ValueError):
    """One or more path-qualified contract failures."""

    def __init__(self, errors: str | Sequence[str]) -> None:
        if isinstance(errors, str):
            errors = [errors]
        self.errors = tuple(str(error) for error in errors)
        super().__init__("\n".join(self.errors))


class DuplicateKeyError(ValueError):
    """Raised internally when JSON contains a repeated object key."""


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects aliases, merges, and duplicate keys."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            event = self.peek_event()
            raise ComposerError(
                None,
                None,
                "YAML aliases are not allowed in contract front matter",
                event.start_mark,
            )
        return super().compose_node(parent, index)


def _construct_unique_mapping(
    loader: UniqueKeyLoader, node: MappingNode, deep: bool = False
) -> dict[Any, Any]:
    if not isinstance(node, MappingNode):
        raise ConstructorError(
            None,
            None,
            f"expected a mapping node, got {node.id}",
            node.start_mark,
        )
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        if getattr(key_node, "value", None) == "<<":
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "YAML merge keys are not allowed in contract front matter",
                key_node.start_mark,
            )
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def display_path(path: Path, repository_root: Path | None = None) -> str:
    """Return a stable repository-relative path when possible."""

    candidate = path.resolve(strict=False)
    if repository_root is not None:
        root = repository_root.resolve(strict=False)
        try:
            return candidate.relative_to(root).as_posix()
        except ValueError:
            pass
    return str(path)


def location(
    source: Path | str, field: str | None = None, repository_root: Path | None = None
) -> str:
    label = (
        display_path(source, repository_root) if isinstance(source, Path) else source
    )
    return f"{label}:{field}" if field else label


def _raise_errors(errors: list[str]) -> None:
    if errors:
        raise ContractError(errors)


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")


def load_json_document(path: Path, repository_root: Path | None = None) -> Any:
    """Load strict JSON, rejecting duplicate keys and non-finite numbers."""

    label = display_path(path, repository_root)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"{label}: cannot read JSON: {exc}") from exc
    try:
        return json.loads(
            raw,
            object_pairs_hook=_json_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, DuplicateKeyError, ValueError) as exc:
        raise ContractError(f"{label}: invalid JSON: {exc}") from exc


def load_frontmatter(path: Path, repository_root: Path | None = None) -> dict[str, Any]:
    """Load only a Markdown document's strict YAML front matter."""

    label = display_path(path, repository_root)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"{label}: cannot read front matter: {exc}") from exc

    lines = text.splitlines()
    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first is None or lines[first].strip() != "---":
        raise ContractError(
            f"{label}: first non-empty line must be the '---' front matter delimiter"
        )
    closing = next(
        (
            index
            for index in range(first + 1, len(lines))
            if lines[index].strip() == "---"
        ),
        None,
    )
    if closing is None:
        raise ContractError(f"{label}: missing closing '---' front matter delimiter")
    payload = "\n".join(lines[first + 1 : closing])
    if not payload.strip():
        raise ContractError(f"{label}: front matter must not be empty")
    try:
        loaded = yaml.load(payload, Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        mark = getattr(exc, "problem_mark", None)
        suffix = (
            f" at front matter line {mark.line + 1}, column {mark.column + 1}"
            if mark
            else ""
        )
        raise ContractError(f"{label}: invalid YAML: {problem}{suffix}") from exc
    if not isinstance(loaded, dict):
        raise ContractError(f"{label}: front matter must be a mapping")
    return loaded


def _closed_mapping(
    value: Any,
    expected: set[str],
    source: Path,
    field: str,
    errors: list[str],
    repository_root: Path,
) -> dict[str, Any]:
    where = location(source, field, repository_root)
    if not isinstance(value, dict):
        errors.append(f"{where}: expected mapping")
        return {}
    string_keys = {key for key in value if isinstance(key, str)}
    non_string = [key for key in value if not isinstance(key, str)]
    if non_string:
        errors.append(f"{where}: keys must be strings, got {non_string!r}")
    for key in sorted(expected - string_keys):
        errors.append(f"{where}.{key}: missing required key")
    for key in sorted(string_keys - expected):
        errors.append(f"{where}.{key}: unknown key")
    return value


def _is_int(value: Any) -> bool:
    return type(value) is int


def _is_number(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(float(value))


def _require_nonempty_string(
    value: Any, source: Path, field: str, errors: list[str], repository_root: Path
) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(
            f"{location(source, field, repository_root)}: expected non-empty string"
        )


def _require_positive_int(
    value: Any, source: Path, field: str, errors: list[str], repository_root: Path
) -> None:
    if not _is_int(value) or value <= 0:
        errors.append(
            f"{location(source, field, repository_root)}: expected positive integer"
        )


def _require_positive_number(
    value: Any, source: Path, field: str, errors: list[str], repository_root: Path
) -> None:
    if not _is_number(value) or float(value) <= 0:
        errors.append(
            f"{location(source, field, repository_root)}: expected finite positive number"
        )


def _string_list(
    value: Any,
    source: Path,
    field: str,
    errors: list[str],
    repository_root: Path,
    *,
    allow_empty: bool = False,
) -> list[str]:
    where = location(source, field, repository_root)
    if not isinstance(value, list):
        errors.append(f"{where}: expected list")
        return []
    if not value and not allow_empty:
        errors.append(f"{where}: list must not be empty")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        item_where = location(source, f"{field}[{index}]", repository_root)
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{item_where}: expected non-empty string")
            continue
        if item in seen:
            errors.append(f"{item_where}: duplicate value {item!r}")
        seen.add(item)
        result.append(item)
    return result


def validate_frame_data(
    data: Any, source: Path, repository_root: Path
) -> dict[str, Any]:
    """Validate the complete closed v1 frame schema and relationships."""

    errors: list[str] = []
    frame = _closed_mapping(
        data, FRAME_KEYS, source, "frontmatter", errors, repository_root
    )
    for section, keys in FRAME_NESTED_KEYS.items():
        _closed_mapping(
            frame.get(section), keys, source, section, errors, repository_root
        )

    if frame.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"{location(source, 'schema_version', repository_root)}: expected integer 1"
        )
    if frame.get("system") != SYSTEM_NAME:
        errors.append(
            f"{location(source, 'system', repository_root)}: expected {SYSTEM_NAME!r}"
        )
    _require_nonempty_string(
        frame.get("profile"), source, "profile", errors, repository_root
    )

    canvas = frame.get("canvas") if isinstance(frame.get("canvas"), dict) else {}
    for key in ("width_px", "height_px"):
        _require_positive_int(
            canvas.get(key), source, f"canvas.{key}", errors, repository_root
        )
    if canvas.get("width_px") != 720 or canvas.get("height_px") != 1280:
        errors.append(
            f"{location(source, 'canvas', repository_root)}: v1 canvas must be 720x1280"
        )
    if canvas.get("aspect") != "9:16":
        errors.append(
            f"{location(source, 'canvas.aspect', repository_root)}: expected '9:16'"
        )

    _require_positive_int(
        frame.get("duration_s"), source, "duration_s", errors, repository_root
    )
    if frame.get("duration_s") != 6:
        errors.append(
            f"{location(source, 'duration_s', repository_root)}: v1 duration must be 6"
        )
    _require_positive_int(
        frame.get("source_fps"), source, "source_fps", errors, repository_root
    )
    if frame.get("source_fps") != 30:
        errors.append(
            f"{location(source, 'source_fps', repository_root)}: v1 source fps must be 30"
        )
    if frame.get("silent") is not True:
        errors.append(
            f"{location(source, 'silent', repository_root)}: expected boolean true"
        )

    gif = frame.get("gif") if isinstance(frame.get("gif"), dict) else {}
    for key in ("fps", "target_bytes", "hard_ceiling_bytes"):
        _require_positive_int(
            gif.get(key), source, f"gif.{key}", errors, repository_root
        )
    if gif.get("fps") != 15:
        errors.append(
            f"{location(source, 'gif.fps', repository_root)}: v1 GIF fps must be 15"
        )
    if gif.get("loop_mode") != "infinite":
        errors.append(
            f"{location(source, 'gif.loop_mode', repository_root)}: expected 'infinite'"
        )
    if gif.get("endpoint") != "pixel-identical":
        errors.append(
            f"{location(source, 'gif.endpoint', repository_root)}: expected 'pixel-identical'"
        )
    if _is_int(gif.get("target_bytes")) and _is_int(gif.get("hard_ceiling_bytes")):
        if gif["hard_ceiling_bytes"] < gif["target_bytes"]:
            errors.append(
                f"{location(source, 'gif.hard_ceiling_bytes', repository_root)}: "
                "must be greater than or equal to gif.target_bytes"
            )

    mp4 = frame.get("mp4") if isinstance(frame.get("mp4"), dict) else {}
    _require_positive_int(mp4.get("fps"), source, "mp4.fps", errors, repository_root)
    if mp4.get("fps") != 30:
        errors.append(
            f"{location(source, 'mp4.fps', repository_root)}: v1 MP4 fps must be 30"
        )
    ssim = mp4.get("endpoint_ssim_min")
    if not _is_number(ssim) or not 0 <= float(ssim) <= 1:
        errors.append(
            f"{location(source, 'mp4.endpoint_ssim_min', repository_root)}: expected finite number from 0 to 1"
        )

    palette = frame.get("palette") if isinstance(frame.get("palette"), dict) else {}
    for key in FRAME_NESTED_KEYS["palette"]:
        value = palette.get(key)
        if not isinstance(value, str) or not HEX_COLOR_RE.fullmatch(value):
            errors.append(
                f"{location(source, f'palette.{key}', repository_root)}: expected six-digit hex color"
            )

    typography = (
        frame.get("typography") if isinstance(frame.get("typography"), dict) else {}
    )
    _require_nonempty_string(
        typography.get("family"), source, "typography.family", errors, repository_root
    )
    for key in ("hook_weight", "hook_size_px"):
        _require_positive_int(
            typography.get(key), source, f"typography.{key}", errors, repository_root
        )
    _require_positive_number(
        typography.get("hook_line_height"),
        source,
        "typography.hook_line_height",
        errors,
        repository_root,
    )

    hook = frame.get("hook") if isinstance(frame.get("hook"), dict) else {}
    card = frame.get("card") if isinstance(frame.get("card"), dict) else {}
    for section_name, section in (("hook", hook), ("card", card)):
        for key in FRAME_NESTED_KEYS[section_name]:
            _require_positive_int(
                section.get(key),
                source,
                f"{section_name}.{key}",
                errors,
                repository_root,
            )
    if all(_is_int(hook.get(key)) for key in ("left_px", "width_px")) and _is_int(
        canvas.get("width_px")
    ):
        if hook["left_px"] + hook["width_px"] > canvas["width_px"]:
            errors.append(
                f"{location(source, 'hook', repository_root)}: horizontal geometry exceeds canvas"
            )
    if (
        _is_int(hook.get("top_px"))
        and _is_int(canvas.get("height_px"))
        and hook["top_px"] >= canvas["height_px"]
    ):
        errors.append(
            f"{location(source, 'hook.top_px', repository_root)}: must be inside canvas"
        )
    if (
        _is_int(card.get("width_px"))
        and _is_int(canvas.get("width_px"))
        and card["width_px"] > canvas["width_px"]
    ):
        errors.append(
            f"{location(source, 'card.width_px', repository_root)}: must fit inside canvas"
        )
    if (
        all(_is_int(card.get(key)) for key in ("radius_px", "width_px"))
        and card["radius_px"] * 2 > card["width_px"]
    ):
        errors.append(
            f"{location(source, 'card.radius_px', repository_root)}: radius cannot exceed half the card width"
        )

    timing = frame.get("timing") if isinstance(frame.get("timing"), dict) else {}
    for key in FRAME_NESTED_KEYS["timing"]:
        _require_positive_number(
            timing.get(key), source, f"timing.{key}", errors, repository_root
        )
    timing_values = [
        timing.get("motion_start_s"),
        timing.get("payoff_by_s"),
        timing.get("return_start_s"),
        frame.get("duration_s"),
    ]
    if all(_is_number(value) for value in timing_values):
        if (
            not 0
            < timing_values[0]
            < timing_values[1]
            < timing_values[2]
            < timing_values[3]
        ):
            errors.append(
                f"{location(source, 'timing', repository_root)}: expected "
                "0 < motion_start_s < payoff_by_s < return_start_s < duration_s"
            )
    if all(
        _is_number(timing.get(key))
        for key in ("payoff_by_s", "payoff_hold_s", "return_start_s")
    ):
        if timing["payoff_by_s"] + timing["payoff_hold_s"] > timing["return_start_s"]:
            errors.append(
                f"{location(source, 'timing.payoff_hold_s', repository_root)}: payoff hold extends past return start"
            )
    if _is_number(timing.get("payoff_hold_s")) and timing["payoff_hold_s"] < 1.5:
        errors.append(
            f"{location(source, 'timing.payoff_hold_s', repository_root)}: must be at least 1.5"
        )
    if _is_number(timing.get("opening_hold_s")) and timing["opening_hold_s"] < 0.1:
        errors.append(
            f"{location(source, 'timing.opening_hold_s', repository_root)}: must be at least 0.1"
        )
    return_values = [
        timing.get("return_start_s"),
        timing.get("return_complete_by_s"),
        frame.get("duration_s"),
        timing.get("opening_hold_s"),
    ]
    if all(_is_number(value) for value in return_values):
        if (
            not return_values[0]
            < return_values[1]
            <= return_values[2] - return_values[3]
        ):
            errors.append(
                f"{location(source, 'timing.return_complete_by_s', repository_root)}: "
                "must be after return_start_s and no later than duration_s - opening_hold_s"
            )

    treatments = _string_list(
        frame.get("forbidden_treatments"),
        source,
        "forbidden_treatments",
        errors,
        repository_root,
    )
    for index, treatment in enumerate(treatments):
        if treatment not in FORBIDDEN_TREATMENTS:
            errors.append(
                f"{location(source, f'forbidden_treatments[{index}]', repository_root)}: "
                f"unknown treatment {treatment!r}"
            )

    _raise_errors(errors)
    return frame


def load_frame_contract(path: Path, repository_root: Path) -> dict[str, Any]:
    return validate_frame_data(
        load_frontmatter(path, repository_root), path, repository_root
    )


def _validate_source_ref(
    value: str,
    source: Path,
    field: str,
    repository_root: Path,
    errors: list[str],
) -> None:
    where = location(source, field, repository_root)
    if value.startswith("https://"):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            errors.append(f"{where}: invalid https URL")
        return
    if "://" in value:
        errors.append(f"{where}: only https URLs are allowed")
        return
    match = SOURCE_REF_RE.fullmatch(value)
    if not match:
        errors.append(
            f"{where}: expected repository-relative path with optional :line or :start-end suffix"
        )
        return
    raw_path = match.group("path")
    if "\\" in raw_path:
        errors.append(f"{where}: repository paths must use '/' separators")
        return
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts or raw_path.startswith("~"):
        errors.append(
            f"{where}: source path must be repository-root-relative and contained"
        )
        return
    candidate = (repository_root / relative).resolve(strict=False)
    root = repository_root.resolve(strict=False)
    if not _is_relative_to(candidate, root):
        errors.append(f"{where}: source path escapes repository root")
        return
    if not candidate.is_file():
        errors.append(f"{where}: source file does not exist: {raw_path}")
        return
    start = match.group("start")
    end = match.group("end")
    if start and end and int(end) < int(start):
        errors.append(f"{where}: source line range ends before it starts")
        return
    if start:
        try:
            line_count = len(candidate.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeError) as exc:
            errors.append(f"{where}: cannot read source lines: {exc}")
            return
        final_line = int(end or start)
        if final_line > line_count:
            errors.append(
                f"{where}: source line {final_line} exceeds {raw_path}'s {line_count} lines"
            )


def validate_brief_data(
    data: Any,
    source: Path,
    repository_root: Path,
    frame: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the complete closed v1 episode BRIEF front matter."""

    errors: list[str] = []
    brief = _closed_mapping(
        data, BRIEF_KEYS, source, "frontmatter", errors, repository_root
    )
    truth = _closed_mapping(
        brief.get("truth"), BRIEF_TRUTH_KEYS, source, "truth", errors, repository_root
    )

    if brief.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"{location(source, 'schema_version', repository_root)}: expected integer 1"
        )
    scalar_fields = BRIEF_KEYS - {"schema_version", "storyboard", "narration", "truth"}
    for field in sorted(scalar_fields):
        _require_nonempty_string(
            brief.get(field), source, field, errors, repository_root
        )
    for field in ("storyboard", "narration"):
        if type(brief.get(field)) is not bool:
            errors.append(
                f"{location(source, field, repository_root)}: expected boolean"
            )
    if brief.get("motion_verb") not in MOTION_VERBS:
        errors.append(
            f"{location(source, 'motion_verb', repository_root)}: expected one of {sorted(MOTION_VERBS)!r}"
        )

    if brief.get("workflow") != "motion-graphics":
        errors.append(
            f"{location(source, 'workflow', repository_root)}: expected 'motion-graphics'"
        )
    if brief.get("flow") != "automation":
        errors.append(
            f"{location(source, 'flow', repository_root)}: expected 'automation'"
        )
    if brief.get("storyboard") is not False:
        errors.append(
            f"{location(source, 'storyboard', repository_root)}: Quiet Proof Loops require false"
        )
    if brief.get("narration") is not False:
        errors.append(
            f"{location(source, 'narration', repository_root)}: silent profile requires false"
        )

    source_refs = _string_list(
        truth.get("source_refs"), source, "truth.source_refs", errors, repository_root
    )
    qualifiers = _string_list(
        truth.get("qualifiers"), source, "truth.qualifiers", errors, repository_root
    )
    visible_required = _string_list(
        truth.get("visible_required"),
        source,
        "truth.visible_required",
        errors,
        repository_root,
    )
    visible_forbidden = _string_list(
        truth.get("visible_forbidden"),
        source,
        "truth.visible_forbidden",
        errors,
        repository_root,
        allow_empty=True,
    )
    del qualifiers, visible_required, visible_forbidden
    for index, source_ref in enumerate(source_refs):
        _validate_source_ref(
            source_ref,
            source,
            f"truth.source_refs[{index}]",
            repository_root,
            errors,
        )

    checked_at = truth.get("checked_at")
    if not isinstance(checked_at, str) or not ISO_DATE_RE.fullmatch(checked_at):
        errors.append(
            f"{location(source, 'truth.checked_at', repository_root)}: expected ISO date YYYY-MM-DD"
        )
    else:
        try:
            checked_date = date.fromisoformat(checked_at)
        except ValueError:
            errors.append(
                f"{location(source, 'truth.checked_at', repository_root)}: invalid calendar date"
            )
        else:
            if checked_date > date.today():
                errors.append(
                    f"{location(source, 'truth.checked_at', repository_root)}: cannot be in the future"
                )
    if not isinstance(truth.get("baseline_commit"), str) or not COMMIT_RE.fullmatch(
        truth.get("baseline_commit", "")
    ):
        errors.append(
            f"{location(source, 'truth.baseline_commit', repository_root)}: expected 40 hexadecimal characters"
        )
    _require_nonempty_string(
        truth.get("release_tag"), source, "truth.release_tag", errors, repository_root
    )

    if frame is not None:
        canvas = frame.get("canvas", {})
        expected_aspect = f"{canvas.get('width_px')}x{canvas.get('height_px')}"
        expected_length = f"{frame.get('duration_s')}s"
        if brief.get("aspect") != expected_aspect:
            errors.append(
                f"{location(source, 'aspect', repository_root)}: expected frame projection {expected_aspect!r}"
            )
        if brief.get("length") != expected_length:
            errors.append(
                f"{location(source, 'length', repository_root)}: expected frame projection {expected_length!r}"
            )
        if frame.get("silent") is True and brief.get("narration") is not False:
            errors.append(
                f"{location(source, 'narration', repository_root)}: must be false for silent profile"
            )

    _raise_errors(errors)
    return brief


def load_brief_contract(
    path: Path, repository_root: Path, frame: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    return validate_brief_data(
        load_frontmatter(path, repository_root), path, repository_root, frame
    )


def _git(
    repository_root: Path, arguments: Sequence[str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _source_ref_slice(
    lines: list[str], start: str | None, end: str | None
) -> list[str]:
    if start is None:
        return lines
    first = int(start) - 1
    final = int(end or start)
    return lines[first:final]


def source_ref_content_matches_baseline(
    current_lines: list[str],
    snapshot_lines: list[str],
    start: str | None,
    end: str | None,
) -> bool:
    """Return whether the cited baseline evidence still exists verbatim.

    Line numbers identify the evidence as cited against the baseline commit.
    A nearby documentation insertion may move that evidence without changing
    it, so a ranged reference also accepts the baseline slice appearing as the
    same contiguous lines elsewhere in the current file.  Matching in this
    direction means a shift that lands different (but baseline-present)
    content at the cited range cannot silently rebind the citation.
    Whole-file references remain byte-for-line strict.
    """

    current_slice = _source_ref_slice(current_lines, start, end)
    if start is None:
        return current_slice == snapshot_lines
    if not current_slice:
        return False

    snapshot_slice = _source_ref_slice(snapshot_lines, start, end)
    if current_slice == snapshot_slice:
        return True
    if not snapshot_slice:
        return False

    width = len(snapshot_slice)
    return any(
        current_lines[offset : offset + width] == snapshot_slice
        for offset in range(len(current_lines) - width + 1)
    )


def validate_repository_truth(
    brief: Mapping[str, Any], source: Path, repository_root: Path
) -> None:
    """Pin managed-episode evidence to a real, reachable repository snapshot.

    Local source references must still contain the exact cited lines from the
    recorded baseline commit. This permits workflow-only commits while forcing
    a fresh truth check whenever the evidence itself changes.
    """

    root = repository_root.resolve(strict=False)
    errors: list[str] = []
    truth = brief.get("truth")
    if not isinstance(truth, Mapping):
        raise ContractError(
            f"{location(source, 'truth', root)}: expected validated truth mapping"
        )
    baseline = truth.get("baseline_commit")
    if not isinstance(baseline, str) or not COMMIT_RE.fullmatch(baseline):
        raise ContractError(
            f"{location(source, 'truth.baseline_commit', root)}: expected validated commit id"
        )

    commit_check = _git(root, ("cat-file", "-e", f"{baseline}^{{commit}}"))
    if commit_check.returncode:
        errors.append(
            f"{location(source, 'truth.baseline_commit', root)}: commit does not exist in this repository"
        )
    else:
        ancestry = _git(root, ("merge-base", "--is-ancestor", baseline, "HEAD"))
        if ancestry.returncode:
            errors.append(
                f"{location(source, 'truth.baseline_commit', root)}: commit is not an ancestor of HEAD"
            )

        checked_at = truth.get("checked_at")
        commit_date_result = _git(root, ("show", "-s", "--format=%cs", baseline))
        if (
            commit_date_result.returncode == 0
            and isinstance(checked_at, str)
            and ISO_DATE_RE.fullmatch(checked_at)
        ):
            try:
                checked_date = date.fromisoformat(checked_at)
                baseline_date = date.fromisoformat(commit_date_result.stdout.strip())
            except ValueError:
                pass
            else:
                if checked_date < baseline_date:
                    errors.append(
                        f"{location(source, 'truth.checked_at', root)}: predates the baseline commit ({baseline_date.isoformat()})"
                    )

        release_tag = truth.get("release_tag")
        if isinstance(release_tag, str) and release_tag != "unreleased":
            ref = f"refs/tags/{release_tag}"
            ref_format = _git(root, ("check-ref-format", ref))
            tag_commit = _git(root, ("rev-parse", "--verify", f"{ref}^{{commit}}"))
            if ref_format.returncode or tag_commit.returncode:
                errors.append(
                    f"{location(source, 'truth.release_tag', root)}: tag does not exist in this repository"
                )
            else:
                tag_hash = tag_commit.stdout.strip()
                tag_ancestry = _git(
                    root, ("merge-base", "--is-ancestor", tag_hash, baseline)
                )
                if tag_ancestry.returncode:
                    errors.append(
                        f"{location(source, 'truth.release_tag', root)}: tag is not reachable from the baseline commit"
                    )

        refs = truth.get("source_refs")
        if isinstance(refs, list):
            for index, value in enumerate(refs):
                if not isinstance(value, str) or value.startswith("https://"):
                    continue
                match = SOURCE_REF_RE.fullmatch(value)
                if match is None:
                    continue
                raw_path = match.group("path")
                snapshot = _git(root, ("show", f"{baseline}:{raw_path}"))
                where = location(source, f"truth.source_refs[{index}]", root)
                if snapshot.returncode:
                    errors.append(
                        f"{where}: source did not exist at baseline commit {baseline[:12]}"
                    )
                    continue
                try:
                    current_lines = (
                        (root / raw_path).read_text(encoding="utf-8").splitlines()
                    )
                except (OSError, UnicodeError) as exc:
                    errors.append(f"{where}: cannot read current source: {exc}")
                    continue
                snapshot_lines = snapshot.stdout.splitlines()
                start = match.group("start")
                end = match.group("end")
                final_line = int(end or start) if start else None
                if final_line is not None and final_line > len(current_lines):
                    errors.append(
                        f"{where}: cited line {final_line} does not exist in current source"
                    )
                    continue
                if final_line is not None and final_line > len(snapshot_lines):
                    errors.append(
                        f"{where}: cited line {final_line} did not exist at baseline commit {baseline[:12]}"
                    )
                    continue
                if not source_ref_content_matches_baseline(
                    current_lines, snapshot_lines, start, end
                ):
                    qualifier = f"lines {start}-{end or start}" if start else "file"
                    errors.append(
                        f"{where}: cited {qualifier} changed since baseline commit {baseline[:12]}; re-check the claim"
                    )

    _raise_errors(errors)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_contained_path(
    raw: Any,
    *,
    base: Path,
    boundary: Path,
    source: Path,
    field: str,
    repository_root: Path,
) -> Path:
    """Resolve one non-empty relative path and enforce its real boundary."""

    where = location(source, field, repository_root)
    if not isinstance(raw, str) or not raw.strip():
        raise ContractError(f"{where}: expected non-empty relative path")
    if "\x00" in raw:
        raise ContractError(f"{where}: path contains a NUL byte")
    relative = Path(raw)
    if relative.is_absolute() or raw.startswith("~"):
        raise ContractError(
            f"{where}: absolute and home-relative paths are not allowed"
        )
    candidate = (base / relative).resolve(strict=False)
    resolved_boundary = boundary.resolve(strict=False)
    if not _is_relative_to(candidate, resolved_boundary):
        raise ContractError(
            f"{where}: resolved path escapes {display_path(resolved_boundary, repository_root)}"
        )
    return candidate


@dataclass(frozen=True)
class ProjectSpec:
    project_id: str
    batch_default: bool
    adapter_path: Path
    base_dir: Path
    paths: Mapping[str, Path]

    def path(self, key: str) -> Path:
        return self.paths[key]


@dataclass(frozen=True)
class ProjectRegistry:
    repository_root: Path
    registry_path: Path
    projects: tuple[ProjectSpec, ...]

    @property
    def by_id(self) -> dict[str, ProjectSpec]:
        return {project.project_id: project for project in self.projects}

    @property
    def default_projects(self) -> tuple[ProjectSpec, ...]:
        return tuple(project for project in self.projects if project.batch_default)

    def select(self, project_id: str | None = None) -> tuple[ProjectSpec, ...]:
        if project_id is None:
            selected = self.default_projects
            if not selected:
                raise ContractError(
                    f"{display_path(self.registry_path, self.repository_root)}: no batch_default projects"
                )
            return selected
        project = self.by_id.get(project_id)
        if project is None:
            choices = ", ".join(sorted(self.by_id))
            raise ContractError(
                f"{display_path(self.registry_path, self.repository_root)}: unknown project {project_id!r}; "
                f"registered projects: {choices}"
            )
        return (project,)


def _validate_adapter_shape(
    data: Any, adapter_path: Path, repository_root: Path
) -> dict[str, Any]:
    errors: list[str] = []
    adapter = _closed_mapping(
        data, ADAPTER_KEYS, adapter_path, "adapter", errors, repository_root
    )
    if adapter.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"{location(adapter_path, 'schema_version', repository_root)}: expected integer 1"
        )
    project_id = adapter.get("project_id")
    if not isinstance(project_id, str) or not SLUG_RE.fullmatch(project_id):
        errors.append(
            f"{location(adapter_path, 'project_id', repository_root)}: expected lowercase kebab-case slug"
        )
    for key in {"base_dir"} | ADAPTER_PATH_KEYS:
        value = adapter.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(
                f"{location(adapter_path, key, repository_root)}: expected non-empty relative path"
            )
    _raise_errors(errors)
    return adapter


def load_adapter(
    adapter_path: Path,
    repository_root: Path,
    *,
    expected_project_id: str | None = None,
    batch_default: bool = False,
) -> ProjectSpec:
    """Load one closed adapter and resolve all paths with containment."""

    root = repository_root.resolve(strict=False)
    resolved_adapter = adapter_path.resolve(strict=False)
    if not _is_relative_to(resolved_adapter, root):
        raise ContractError(f"{adapter_path}: adapter path escapes repository root")
    if not resolved_adapter.is_file():
        raise ContractError(
            f"{display_path(resolved_adapter, root)}: managed episode is missing adapter.json"
        )
    adapter = _validate_adapter_shape(
        load_json_document(resolved_adapter, root), resolved_adapter, root
    )
    project_id = adapter["project_id"]
    if expected_project_id is not None and project_id != expected_project_id:
        raise ContractError(
            f"{location(resolved_adapter, 'project_id', root)}: expected {expected_project_id!r}, got {project_id!r}"
        )

    base_dir = resolve_contained_path(
        adapter["base_dir"],
        base=resolved_adapter.parent,
        boundary=root,
        source=resolved_adapter,
        field="base_dir",
        repository_root=root,
    )
    if not base_dir.is_dir():
        raise ContractError(
            f"{location(resolved_adapter, 'base_dir', root)}: directory does not exist"
        )

    errors: list[str] = []
    paths: dict[str, Path] = {}
    for key in sorted(ADAPTER_PATH_KEYS):
        boundary = root if key == "profile_file" else base_dir
        try:
            paths[key] = resolve_contained_path(
                adapter[key],
                base=base_dir,
                boundary=boundary,
                source=resolved_adapter,
                field=key,
                repository_root=root,
            )
        except ContractError as exc:
            errors.extend(exc.errors)
    for key in sorted(SOURCE_FILE_KEYS):
        target = paths.get(key)
        if target is not None and not target.is_file():
            errors.append(
                f"{location(resolved_adapter, key, root)}: source file does not exist: "
                f"{display_path(target, root)}"
            )

    source_paths = {target for key, target in paths.items() if key in SOURCE_FILE_KEYS}
    render_dir = paths.get("render_dir")
    verification_file = paths.get("verification_file")
    if render_dir == base_dir:
        errors.append(
            f"{location(resolved_adapter, 'render_dir', root)}: output directory must not be the project source root"
        )
    if render_dir is not None:
        for source_key in sorted(SOURCE_FILE_KEYS):
            target = paths.get(source_key)
            if target is not None and _is_relative_to(target, render_dir):
                errors.append(
                    f"{location(resolved_adapter, 'render_dir', root)}: output directory contains source path from {source_key}"
                )
    if verification_file in source_paths:
        errors.append(
            f"{location(resolved_adapter, 'verification_file', root)}: output must not overwrite a source file"
        )
    if (
        render_dir is not None
        and verification_file is not None
        and _is_relative_to(verification_file, render_dir)
    ):
        errors.append(
            f"{location(resolved_adapter, 'verification_file', root)}: receipt must stay outside render_dir to avoid generated-output collisions"
        )

    # render_dir and verification_file are generated output locations. Clean
    # source validation intentionally does not require either to exist.
    _raise_errors(errors)
    return ProjectSpec(project_id, batch_default, resolved_adapter, base_dir, paths)


def load_project_registry(
    repository_root: Path, registry_path: Path | None = None
) -> ProjectRegistry:
    """Load the sole managed-project registry and every referenced adapter."""

    root = repository_root.resolve(strict=False)
    registry = (registry_path or root / "videos" / "projects.json").resolve(
        strict=False
    )
    if not _is_relative_to(registry, root):
        raise ContractError(f"{registry}: registry path escapes repository root")
    data = load_json_document(registry, root)
    errors: list[str] = []
    document = _closed_mapping(data, REGISTRY_KEYS, registry, "registry", errors, root)
    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"{location(registry, 'schema_version', root)}: expected integer 1"
        )
    rows = document.get("projects")
    if not isinstance(rows, list) or not rows:
        errors.append(
            f"{location(registry, 'projects', root)}: expected non-empty list"
        )
        rows = []

    parsed_rows: list[tuple[str, Path, bool]] = []
    seen_ids: set[str] = set()
    seen_adapters: set[Path] = set()
    for index, row_value in enumerate(rows):
        row = _closed_mapping(
            row_value,
            REGISTRY_PROJECT_KEYS,
            registry,
            f"projects[{index}]",
            errors,
            root,
        )
        project_id = row.get("id")
        if not isinstance(project_id, str) or not SLUG_RE.fullmatch(project_id):
            errors.append(
                f"{location(registry, f'projects[{index}].id', root)}: expected lowercase kebab-case slug"
            )
            continue
        if project_id in seen_ids:
            errors.append(
                f"{location(registry, f'projects[{index}].id', root)}: duplicate project {project_id!r}"
            )
        seen_ids.add(project_id)
        if type(row.get("batch_default")) is not bool:
            errors.append(
                f"{location(registry, f'projects[{index}].batch_default', root)}: expected boolean"
            )
            continue
        try:
            adapter_path = resolve_contained_path(
                row.get("adapter"),
                base=registry.parent,
                boundary=root,
                source=registry,
                field=f"projects[{index}].adapter",
                repository_root=root,
            )
        except ContractError as exc:
            errors.extend(exc.errors)
            continue
        if adapter_path in seen_adapters:
            errors.append(
                f"{location(registry, f'projects[{index}].adapter', root)}: duplicate adapter path"
            )
        seen_adapters.add(adapter_path)
        parsed_rows.append((project_id, adapter_path, row["batch_default"]))
    _raise_errors(errors)

    projects: list[ProjectSpec] = []
    adapter_errors: list[str] = []
    for project_id, adapter_path, batch_default in parsed_rows:
        try:
            projects.append(
                load_adapter(
                    adapter_path,
                    root,
                    expected_project_id=project_id,
                    batch_default=batch_default,
                )
            )
        except ContractError as exc:
            adapter_errors.extend(exc.errors)
    _raise_errors(adapter_errors)
    return ProjectRegistry(root, registry, tuple(projects))


def load_fixture(repository_root: Path, fixture: Path) -> ProjectSpec:
    """Load a standalone fixture directory or adapter path without managing it."""

    root = repository_root.resolve(strict=False)
    candidate = fixture if fixture.is_absolute() else Path.cwd() / fixture
    candidate = candidate.resolve(strict=False)
    if not _is_relative_to(candidate, root):
        raise ContractError(f"{fixture}: fixture must be contained in repository root")
    adapter_path = candidate / "adapter.json" if candidate.is_dir() else candidate
    return load_adapter(adapter_path, root, batch_default=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_asset_manifest(project: ProjectSpec, repository_root: Path) -> set[str]:
    """Validate the closed asset manifest and every recorded SHA-256 digest."""

    root = repository_root.resolve(strict=False)
    manifest_path = project.path("asset_manifest")
    data = load_json_document(manifest_path, root)
    errors: list[str] = []
    manifest = _closed_mapping(
        data, ASSET_MANIFEST_KEYS, manifest_path, "manifest", errors, root
    )
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"{location(manifest_path, 'schema_version', root)}: expected integer 1"
        )
    rows = manifest.get("assets")
    if not isinstance(rows, list) or not rows:
        errors.append(
            f"{location(manifest_path, 'assets', root)}: expected non-empty list"
        )
        rows = []

    recorded: set[str] = set()
    for index, row_value in enumerate(rows):
        row = _closed_mapping(
            row_value,
            ASSET_ENTRY_KEYS,
            manifest_path,
            f"assets[{index}]",
            errors,
            root,
        )
        raw_path = row.get("path")
        digest = row.get("sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            errors.append(
                f"{location(manifest_path, f'assets[{index}].sha256', root)}: expected 64 hexadecimal characters"
            )
        try:
            asset = resolve_contained_path(
                raw_path,
                base=project.base_dir,
                boundary=project.base_dir,
                source=manifest_path,
                field=f"assets[{index}].path",
                repository_root=root,
            )
        except ContractError as exc:
            errors.extend(exc.errors)
            continue
        relative = asset.relative_to(project.base_dir).as_posix()
        if relative in recorded:
            errors.append(
                f"{location(manifest_path, f'assets[{index}].path', root)}: duplicate asset path {relative!r}"
            )
        recorded.add(relative)
        if not asset.is_file():
            errors.append(
                f"{location(manifest_path, f'assets[{index}].path', root)}: asset does not exist: {relative}"
            )
            continue
        if isinstance(digest, str) and SHA256_RE.fullmatch(digest):
            try:
                actual = sha256_file(asset)
            except OSError as exc:
                errors.append(
                    f"{location(manifest_path, f'assets[{index}].path', root)}: cannot hash asset: {exc}"
                )
            else:
                if actual != digest.lower():
                    errors.append(
                        f"{location(manifest_path, f'assets[{index}].sha256', root)}: digest mismatch for "
                        f"{relative}; expected {digest.lower()}, got {actual}"
                    )
    _raise_errors(errors)
    return recorded


def _baseline_binary_path(
    raw: Any,
    source: Path,
    field: str,
    repository_root: Path,
) -> Path:
    return resolve_contained_path(
        raw,
        base=repository_root,
        boundary=repository_root,
        source=source,
        field=field,
        repository_root=repository_root,
    )


def validate_baseline_data(
    data: Any,
    source: Path,
    repository_root: Path,
    *,
    allowed_project_ids: Iterable[str],
    required_project_ids: Iterable[str] = (),
    verify_files: bool = True,
) -> dict[str, Any]:
    """Validate a closed, approved-published-set binary SHA-256 baseline."""

    root = repository_root.resolve(strict=False)
    allowed = set(allowed_project_ids)
    required = set(required_project_ids)
    errors: list[str] = []
    baseline = _closed_mapping(data, BASELINE_KEYS, source, "baseline", errors, root)
    if baseline.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"{location(source, 'schema_version', root)}: expected integer 1")
    projects = baseline.get("projects")
    if not isinstance(projects, dict) or not projects:
        errors.append(
            f"{location(source, 'projects', root)}: expected non-empty project mapping"
        )
        projects = {}
    for missing in sorted(required - set(projects)):
        errors.append(
            f"{location(source, f'projects.{missing}', root)}: missing required published binary pair"
        )
    seen_paths: dict[Path, str] = {}
    for project_id, entry_value in projects.items():
        project_field = f"projects.{project_id}"
        if not isinstance(project_id, str) or not SLUG_RE.fullmatch(project_id):
            errors.append(
                f"{location(source, project_field, root)}: invalid project id"
            )
            continue
        if project_id not in allowed:
            errors.append(
                f"{location(source, project_field, root)}: project is not in the approved published binary set"
            )
        entry = _closed_mapping(
            entry_value, BASELINE_ENTRY_KEYS, source, project_field, errors, root
        )
        resolved: dict[str, Path] = {}
        for kind in ("gif", "mp4"):
            path_field = f"{project_field}.{kind}_path"
            digest_field = f"{project_field}.{kind}_sha256"
            digest = entry.get(f"{kind}_sha256")
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                errors.append(
                    f"{location(source, digest_field, root)}: expected 64 hexadecimal characters"
                )
            try:
                binary = _baseline_binary_path(
                    entry.get(f"{kind}_path"), source, path_field, root
                )
            except ContractError as exc:
                errors.extend(exc.errors)
                continue
            resolved[kind] = binary
            if binary.suffix.lower() != f".{kind}":
                errors.append(
                    f"{location(source, path_field, root)}: expected .{kind} file"
                )
            if binary.name != f"{project_id}.{kind}":
                errors.append(
                    f"{location(source, path_field, root)}: expected basename {project_id}.{kind}"
                )
            if binary in seen_paths:
                errors.append(
                    f"{location(source, path_field, root)}: path is already used by {seen_paths[binary]}"
                )
            seen_paths[binary] = path_field
            if verify_files:
                if not binary.is_file():
                    errors.append(
                        f"{location(source, path_field, root)}: baseline binary does not exist: "
                        f"{display_path(binary, root)}"
                    )
                    continue
                if isinstance(digest, str) and SHA256_RE.fullmatch(digest):
                    actual = sha256_file(binary)
                    if actual != digest.lower():
                        errors.append(
                            f"{location(source, digest_field, root)}: digest mismatch for "
                            f"{display_path(binary, root)}; expected {digest.lower()}, got {actual}"
                        )
        if resolved.get("gif") == resolved.get("mp4") and resolved:
            errors.append(
                f"{location(source, project_field, root)}: GIF and MP4 paths must differ"
            )
    _raise_errors(errors)
    return baseline


def discover_published_project_ids(
    repository_root: Path, *, binary_root: Path | None = None
) -> tuple[str, ...]:
    """Return every complete GIF/MP4 pair on the tracked delivery surface."""

    root = repository_root.resolve(strict=False)
    delivery_root = (binary_root or root / "assets" / "feature-gifs").resolve(
        strict=False
    )
    if not _is_relative_to(delivery_root, root):
        raise ContractError(
            f"{display_path(delivery_root, root)}: published binary root escapes repository"
        )
    if not delivery_root.is_dir():
        raise ContractError(
            f"{display_path(delivery_root, root)}: published binary root does not exist"
        )

    by_project: dict[str, set[str]] = {}
    errors: list[str] = []
    for path in sorted(delivery_root.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".gif", ".mp4"}:
            continue
        project_id = path.stem
        if not SLUG_RE.fullmatch(project_id):
            errors.append(
                f"{display_path(path, root)}: published binary basename must be lowercase kebab-case"
            )
            continue
        by_project.setdefault(project_id, set()).add(path.suffix.lower()[1:])
    if not by_project:
        errors.append(
            f"{display_path(delivery_root, root)}: no published GIF/MP4 pairs found"
        )
    for project_id, kinds in sorted(by_project.items()):
        missing = {"gif", "mp4"} - kinds
        if missing:
            errors.append(
                f"{display_path(delivery_root, root)}/{project_id}: incomplete published pair; missing {', '.join(sorted(missing))}"
            )
    _raise_errors(errors)
    return tuple(sorted(by_project))


def build_baseline_data(
    project_ids: Iterable[str],
    repository_root: Path,
    *,
    binary_root: Path | None = None,
) -> dict[str, Any]:
    """Build a baseline from tracked delivery binaries, never local renders."""

    root = repository_root.resolve(strict=False)
    delivery_root = (binary_root or root / "assets" / "feature-gifs").resolve(
        strict=False
    )
    if not _is_relative_to(delivery_root, root):
        raise ContractError(
            f"{display_path(delivery_root, root)}: baseline binary root escapes repository"
        )
    errors: list[str] = []
    entries: dict[str, Any] = {}
    identifiers = tuple(project_ids)
    if not identifiers:
        raise ContractError("cannot build an empty published binary baseline")
    if len(set(identifiers)) != len(identifiers):
        raise ContractError("published binary baseline project ids must be unique")
    for project_id in identifiers:
        if not isinstance(project_id, str) or not SLUG_RE.fullmatch(project_id):
            errors.append(f"invalid published binary project id: {project_id!r}")
            continue
        entry: dict[str, str] = {}
        for kind in ("gif", "mp4"):
            binary = delivery_root / f"{project_id}.{kind}"
            if not binary.is_file():
                errors.append(
                    f"{display_path(binary, root)}: cannot write baseline; binary does not exist"
                )
                continue
            entry[f"{kind}_path"] = binary.relative_to(root).as_posix()
            entry[f"{kind}_sha256"] = sha256_file(binary)
        entries[project_id] = entry
    _raise_errors(errors)
    result = {"schema_version": SCHEMA_VERSION, "projects": entries}
    validate_baseline_data(
        result,
        Path("<generated-baseline>"),
        root,
        allowed_project_ids=identifiers,
        required_project_ids=identifiers,
    )
    return result


def write_baseline_file(
    path: Path, data: Mapping[str, Any], *, replace: bool = False
) -> None:
    """Write canonical JSON atomically, refusing replacement unless explicit."""

    target = path.resolve(strict=False)
    if target.is_symlink():
        raise ContractError(f"{path}: refusing to replace a symbolic link")
    if target.exists() and not replace:
        raise ContractError(
            f"{path}: baseline already exists; pass --replace to overwrite it"
        )
    if target.exists() and not target.is_file():
        raise ContractError(f"{path}: baseline target is not a regular file")
    if not target.parent.is_dir():
        raise ContractError(f"{path}: parent directory does not exist")
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    except OSError as exc:
        raise ContractError(f"{path}: cannot write baseline: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink()
            except OSError:
                pass


def check_baseline_file(
    path: Path,
    repository_root: Path,
    *,
    allowed_project_ids: Iterable[str],
    required_project_ids: Iterable[str] = (),
) -> dict[str, Any]:
    if not path.is_file():
        raise ContractError(f"{path}: baseline file does not exist")
    return validate_baseline_data(
        load_json_document(path, repository_root),
        path,
        repository_root,
        allowed_project_ids=allowed_project_ids,
        required_project_ids=required_project_ids,
        verify_files=True,
    )


def palette_values(frame: Mapping[str, Any]) -> list[str]:
    """Return palette values in the profile's declared v1 semantic order."""

    palette = frame["palette"]
    order = (
        "background",
        "surface",
        "border",
        "text",
        "muted",
        "radar_blue",
        "deep_blue",
        "heart_red",
        "estimate_amber",
        "unknown_gray",
    )
    return [palette[key] for key in order]


__all__ = [
    "ADAPTER_PATH_KEYS",
    "BASELINE_ENTRY_KEYS",
    "ContractError",
    "ProjectRegistry",
    "ProjectSpec",
    "build_baseline_data",
    "check_baseline_file",
    "discover_published_project_ids",
    "display_path",
    "load_adapter",
    "load_brief_contract",
    "load_fixture",
    "load_frame_contract",
    "load_frontmatter",
    "load_json_document",
    "load_project_registry",
    "location",
    "palette_values",
    "resolve_contained_path",
    "sha256_file",
    "validate_baseline_data",
    "validate_brief_data",
    "validate_frame_data",
    "validate_repository_truth",
    "verify_asset_manifest",
    "write_baseline_file",
]
