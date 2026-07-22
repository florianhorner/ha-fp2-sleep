#!/usr/bin/env python3
"""Render, encode, and verify managed Quiet Proof Loop deliverables."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import filecmp
from fractions import Fraction
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType
from typing import Callable


ROOT = Path(__file__).resolve().parent
PROJECTS_FILE = "projects.json"
SUPPORT_FILE = "quiet_proof_loops.py"
HUMAN_GO_LINE = "Human decision: GO"
DECISION_HASH_PREFIX = "Decision GIF SHA-256:"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PALETTE_COLOR_OPTIONS = (128, 96, 64)
DURATION_TOLERANCE_S = 0.01
SOURCE_ADAPTER_PATH_KEYS = (
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
)

HYPERFRAMES_PIN = re.compile(
    r"(?<![A-Za-z0-9_.-])hyperframes@"
    r"([0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)"
    r"(?![A-Za-z0-9_.+-])"
)


@dataclass(frozen=True)
class ManifestProject:
    slug: str
    adapter_relative: Path
    batch_default: bool


@dataclass(frozen=True)
class FrameProfile:
    width: int
    height: int
    duration_s: float
    gif_fps: int
    mp4_fps: int
    gif_frames: int
    mp4_frames: int
    gif_target_bytes: int
    gif_hard_ceiling_bytes: int
    mp4_endpoint_ssim_min: float
    silent: bool
    motion_start_s: float
    payoff_by_s: float
    payoff_hold_s: float


@dataclass(frozen=True)
class ProjectConfig:
    slug: str
    root: Path
    adapter: dict[str, object]
    brief: dict[str, object]
    profile: FrameProfile
    render_dir: Path
    verification_file: Path
    package_file: Path
    mp4_file: Path
    gif_file: Path
    hyperframes_pin: str
    approved_gif_sha256: str | None


@dataclass(frozen=True)
class Mp4Evidence:
    summary: dict[str, object]
    endpoint_ssim: float


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=merged_env,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if result.returncode:
        detail = ""
        if capture:
            detail = f"\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}{detail}"
        )
    return result


def load_support_module() -> ModuleType | None:
    """Load the shared parser without creating import cache files."""
    path = ROOT / SUPPORT_FILE
    if not path.is_file():
        return None

    module_name = "_quiet_proof_loops_for_deliverables"
    module = ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        source = path.read_text(encoding="utf-8")
        exec(compile(source, str(path), "exec"), module.__dict__)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise RuntimeError(f"unable to load {path.relative_to(ROOT)}: {exc}") from exc
    return module


def compatible_loader(
    support: ModuleType | None,
    names: tuple[str, ...],
    path: Path,
) -> Callable[[Path], object] | None:
    if support is None:
        return None
    for name in names:
        candidate = getattr(support, name, None)
        if not callable(candidate):
            continue
        try:
            inspect.signature(candidate).bind(path)
        except (TypeError, ValueError):
            continue
        return candidate
    return None


def mapping_result(value: object, label: str) -> dict[str, object]:
    if isinstance(value, tuple) and value and isinstance(value[0], dict):
        value = value[0]
    if not isinstance(value, dict):
        raise RuntimeError(f"{label}: expected an object")
    return value


def load_json_document(
    path: Path,
    support: ModuleType | None = None,
    *,
    role: str = "JSON",
) -> dict[str, object]:
    role_loaders = {
        "adapter": (
            "load_adapter",
            "load_json_document",
            "load_json_object",
            "load_json_file",
            "load_json",
            "read_json",
        ),
        "package": (
            "load_package",
            "load_json_document",
            "load_json_object",
            "load_json_file",
            "load_json",
            "read_json",
        ),
    }
    loader = compatible_loader(
        support,
        role_loaders.get(
            role,
            (
                "load_json_document",
                "load_json_object",
                "load_json_file",
                "load_json",
                "read_json",
            ),
        ),
        path,
    )
    try:
        value = loader(path) if loader else json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{path}: invalid {role} JSON: {exc}") from exc
    return mapping_result(value, str(path))


def load_front_matter(
    path: Path,
    support: ModuleType | None,
    *,
    role: str,
) -> dict[str, object]:
    role_loaders = {
        "brief": (
            "load_brief",
            "load_frontmatter",
            "load_front_matter",
            "load_markdown_front_matter",
            "read_front_matter",
        ),
        "frame": (
            "load_frame",
            "load_profile",
            "load_frontmatter",
            "load_front_matter",
            "load_markdown_front_matter",
            "read_front_matter",
        ),
    }
    loader = compatible_loader(support, role_loaders[role], path)
    if loader:
        return mapping_result(loader(path), str(path))

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"unable to read {role} {path}: {exc}") from exc
    if not lines or lines[0] != "---":
        raise RuntimeError(f"{path}: missing YAML front matter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise RuntimeError(f"{path}: unterminated YAML front matter") from exc

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            f"{ROOT / SUPPORT_FILE} is unavailable and PyYAML is required to load {path}"
        ) from exc
    try:
        value = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise RuntimeError(f"{path}: invalid YAML front matter: {exc}") from exc
    return mapping_result(value, str(path))


def required_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{label}: expected an object")
    return value


def required_text(mapping: dict[str, object], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{label}: {key} must be a non-empty string")
    return value.strip()


def required_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeError(f"{label}: expected a positive integer")
    return value


def required_number(value: object, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"{label}: expected a number")
    number = float(value)
    if number < minimum:
        raise RuntimeError(f"{label}: expected a value >= {minimum}")
    return number


def frame_count(duration: object, fps: int, label: str) -> tuple[float, int]:
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise RuntimeError(f"{label}: duration_s must be numeric")
    try:
        decimal_duration = Decimal(str(duration))
    except InvalidOperation as exc:
        raise RuntimeError(f"{label}: invalid duration_s") from exc
    if decimal_duration <= 0:
        raise RuntimeError(f"{label}: duration_s must be positive")
    frames = decimal_duration * Decimal(fps)
    if frames != frames.to_integral_value():
        raise RuntimeError(
            f"{label}: duration_s * fps must produce a whole frame count"
        )
    return float(decimal_duration), int(frames)


def parse_frame_profile(frame: dict[str, object], label: str) -> FrameProfile:
    canvas = required_mapping(frame.get("canvas"), f"{label}.canvas")
    gif = required_mapping(frame.get("gif"), f"{label}.gif")
    mp4 = required_mapping(frame.get("mp4"), f"{label}.mp4")
    timing = required_mapping(frame.get("timing"), f"{label}.timing")

    width = required_int(canvas.get("width_px"), f"{label}.canvas.width_px")
    height = required_int(canvas.get("height_px"), f"{label}.canvas.height_px")
    gif_fps = required_int(gif.get("fps"), f"{label}.gif.fps")
    mp4_fps = required_int(mp4.get("fps"), f"{label}.mp4.fps")
    source_fps = required_int(frame.get("source_fps"), f"{label}.source_fps")
    if source_fps != mp4_fps:
        raise RuntimeError(f"{label}: source_fps and mp4.fps must match")

    duration_s, gif_frames = frame_count(frame.get("duration_s"), gif_fps, label)
    _, mp4_frames = frame_count(frame.get("duration_s"), mp4_fps, label)
    target_bytes = required_int(gif.get("target_bytes"), f"{label}.gif.target_bytes")
    hard_ceiling = required_int(
        gif.get("hard_ceiling_bytes"), f"{label}.gif.hard_ceiling_bytes"
    )
    if target_bytes > hard_ceiling:
        raise RuntimeError(f"{label}: GIF target cannot exceed the hard ceiling")

    ssim_min = required_number(
        mp4.get("endpoint_ssim_min"), f"{label}.mp4.endpoint_ssim_min"
    )
    if ssim_min > 1.0:
        raise RuntimeError(f"{label}: mp4.endpoint_ssim_min cannot exceed 1")
    silent = frame.get("silent")
    if not isinstance(silent, bool):
        raise RuntimeError(f"{label}.silent: expected a boolean")

    motion_start = required_number(
        timing.get("motion_start_s"), f"{label}.timing.motion_start_s"
    )
    payoff_by = required_number(
        timing.get("payoff_by_s"), f"{label}.timing.payoff_by_s"
    )
    payoff_hold = required_number(
        timing.get("payoff_hold_s"), f"{label}.timing.payoff_hold_s"
    )
    if not (motion_start < payoff_by < duration_s):
        raise RuntimeError(f"{label}: motion/payoff timing must fall within duration_s")

    return FrameProfile(
        width=width,
        height=height,
        duration_s=duration_s,
        gif_fps=gif_fps,
        mp4_fps=mp4_fps,
        gif_frames=gif_frames,
        mp4_frames=mp4_frames,
        gif_target_bytes=target_bytes,
        gif_hard_ceiling_bytes=hard_ceiling,
        mp4_endpoint_ssim_min=ssim_min,
        silent=silent,
        motion_start_s=motion_start,
        payoff_by_s=payoff_by,
        payoff_hold_s=payoff_hold,
    )


def relative_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{label}: expected a non-empty relative path")
    path = Path(value)
    if path.is_absolute():
        raise RuntimeError(f"{label}: absolute paths are not allowed")
    return path


def resolved_inside(base: Path, relative: Path, boundary: Path, label: str) -> Path:
    path = (base / relative).resolve()
    try:
        path.relative_to(boundary.resolve())
    except ValueError as exc:
        raise RuntimeError(f"{label}: path escapes {boundary}") from exc
    return path


def load_manifest() -> list[ManifestProject]:
    path = ROOT / PROJECTS_FILE
    manifest = load_json_document(path)
    raw_projects = manifest.get("projects")
    if not isinstance(raw_projects, list):
        raise RuntimeError(f"{path}: projects must be an array")

    projects: list[ManifestProject] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_projects):
        label = f"{path}: projects[{index}]"
        entry = required_mapping(raw, label)
        slug = required_text(entry, "id", label)
        if slug in seen:
            raise RuntimeError(f"{label}: duplicate project id {slug!r}")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise RuntimeError(f"{label}: invalid project id {slug!r}")
        batch_default = entry.get("batch_default")
        if not isinstance(batch_default, bool):
            raise RuntimeError(f"{label}: batch_default must be a boolean")
        adapter_relative = relative_path(entry.get("adapter"), f"{label}.adapter")
        resolved_inside(ROOT, adapter_relative, ROOT, f"{label}.adapter")
        projects.append(ManifestProject(slug, adapter_relative, batch_default))
        seen.add(slug)
    if not projects:
        raise RuntimeError(f"{path}: no managed projects are registered")
    return projects


def select_projects(
    projects: list[ManifestProject], requested_slug: str | None
) -> list[ManifestProject]:
    if requested_slug is not None:
        if not requested_slug or requested_slug != requested_slug.strip():
            raise RuntimeError("--project requires a non-empty managed project slug")
        selected = [project for project in projects if project.slug == requested_slug]
        if not selected:
            managed = ", ".join(project.slug for project in projects)
            raise RuntimeError(
                f"unknown project {requested_slug!r}; managed projects: {managed}"
            )
        return selected

    selected = [project for project in projects if project.batch_default]
    if not selected:
        raise RuntimeError(
            f"{ROOT / PROJECTS_FILE}: no batch_default projects are registered"
        )
    return selected


def extract_hyperframes_pin(package: dict[str, object], label: str) -> str:
    scripts = required_mapping(package.get("scripts"), f"{label}.scripts")
    render_script = scripts.get("render")
    if not isinstance(render_script, str) or not render_script.strip():
        raise RuntimeError(f"{label}: scripts.render must be a non-empty string")
    render_pins = HYPERFRAMES_PIN.findall(render_script)
    if len(set(render_pins)) != 1:
        raise RuntimeError(
            f"{label}: scripts.render must contain one exact HyperFrames pin"
        )
    pin = render_pins[0]

    all_pins = {
        match
        for script in scripts.values()
        if isinstance(script, str)
        for match in HYPERFRAMES_PIN.findall(script)
    }
    if all_pins != {pin}:
        raise RuntimeError(
            f"{label}: package scripts contain inconsistent HyperFrames pins"
        )
    return pin


def read_human_approval(path: Path) -> str | None:
    """Return the approved GIF digest only when the receipt binds GO to it."""

    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(
            f"unable to read existing verification receipt {path}: {exc}"
        ) from exc
    if HUMAN_GO_LINE not in lines:
        return None
    candidates = [
        line.removeprefix(DECISION_HASH_PREFIX).strip().strip("`").lower()
        for line in lines
        if line.startswith(DECISION_HASH_PREFIX)
    ]
    if len(candidates) != 1 or not SHA256_RE.fullmatch(candidates[0]):
        return None
    return candidates[0]


def validate_output_paths(
    slug: str,
    project_root: Path,
    source_paths: dict[str, Path],
    render_dir: Path,
    verification_file: Path,
) -> None:
    """Keep generated writes disjoint from every declared source path."""

    if render_dir == project_root:
        raise RuntimeError(f"{slug}: render_dir must not be the project source root")
    for key, path in source_paths.items():
        try:
            path.relative_to(render_dir)
        except ValueError:
            pass
        else:
            raise RuntimeError(f"{slug}: render_dir contains source path from {key}")
    if verification_file in set(source_paths.values()):
        raise RuntimeError(
            f"{slug}: verification_file must not overwrite a source file"
        )
    try:
        verification_file.relative_to(render_dir)
    except ValueError:
        pass
    else:
        raise RuntimeError(
            f"{slug}: verification_file must stay outside render_dir to avoid generated-output collisions"
        )


def load_project(
    entry: ManifestProject,
    support: ModuleType | None,
) -> ProjectConfig:
    adapter_path = resolved_inside(
        ROOT, entry.adapter_relative, ROOT, f"{entry.slug}: adapter"
    )
    if not adapter_path.is_file():
        raise RuntimeError(f"{entry.slug}: selected adapter is missing: {adapter_path}")
    adapter = load_json_document(adapter_path, support, role="adapter")
    if required_text(adapter, "project_id", str(adapter_path)) != entry.slug:
        raise RuntimeError(
            f"{entry.slug}: adapter project_id does not match the manifest"
        )

    base_relative = relative_path(
        adapter.get("base_dir", "."), f"{entry.slug}: base_dir"
    )
    project_root = resolved_inside(
        adapter_path.parent, base_relative, ROOT, f"{entry.slug}: base_dir"
    )
    if not project_root.is_dir():
        raise RuntimeError(
            f"{entry.slug}: project directory is missing: {project_root}"
        )

    def project_file(key: str, *, boundary: Path = project_root) -> Path:
        relative = relative_path(adapter.get(key), f"{entry.slug}: {key}")
        return resolved_inside(project_root, relative, boundary, f"{entry.slug}: {key}")

    source_paths = {
        key: project_file(key, boundary=ROOT if key == "profile_file" else project_root)
        for key in SOURCE_ADAPTER_PATH_KEYS
    }
    brief_file = source_paths["brief_file"]
    profile_file = source_paths["profile_file"]
    package_file = source_paths["package_file"]
    render_dir = project_file("render_dir")
    verification_file = project_file("verification_file")
    validate_output_paths(
        entry.slug,
        project_root,
        source_paths,
        render_dir,
        verification_file,
    )
    for label, path in source_paths.items():
        if not path.is_file():
            raise RuntimeError(f"{entry.slug}: selected {label} is missing: {path}")

    brief = load_front_matter(brief_file, support, role="brief")
    for key in ("claim", "payoff_state", "uncertainty"):
        required_text(brief, key, str(brief_file))
    truth = required_mapping(brief.get("truth"), f"{brief_file}.truth")
    for key in ("checked_at", "baseline_commit", "release_tag"):
        required_text(truth, key, f"{brief_file}.truth")

    frame = load_front_matter(profile_file, support, role="frame")
    profile = parse_frame_profile(frame, str(profile_file))
    package = load_json_document(package_file, support, role="package")
    pin = extract_hyperframes_pin(package, str(package_file))

    mp4_file = render_dir / f"{entry.slug}.mp4"
    gif_file = render_dir / f"{entry.slug}.gif"
    return ProjectConfig(
        slug=entry.slug,
        root=project_root,
        adapter=adapter,
        brief=brief,
        profile=profile,
        render_dir=render_dir,
        verification_file=verification_file,
        package_file=package_file,
        mp4_file=mp4_file,
        gif_file=gif_file,
        hyperframes_pin=pin,
        approved_gif_sha256=read_human_approval(verification_file),
    )


def require_binaries(*, render: bool) -> None:
    required = ["ffmpeg", "ffprobe"]
    if render:
        required.append("npx")
    missing = [binary for binary in required if shutil.which(binary) is None]
    if missing:
        raise RuntimeError(f"required binaries are missing: {', '.join(missing)}")


def render_project(project: ProjectConfig, run_id: str) -> Path:
    project.render_dir.mkdir(parents=True, exist_ok=True)
    print(f"[{project.slug}] rendering high-quality MP4", flush=True)
    run(
        [
            "npx",
            "--yes",
            f"hyperframes@{project.hyperframes_pin}",
            "render",
            ".",
            "--format",
            "mp4",
            "--quality",
            "high",
            "--fps",
            str(project.profile.mp4_fps),
            "--strict-all",
            "--output",
            str(project.mp4_file.relative_to(project.root)),
        ],
        cwd=project.root,
        env={"HYPERFRAMES_RUN_ID": run_id},
    )
    if not project.mp4_file.is_file() or project.mp4_file.stat().st_size == 0:
        raise RuntimeError(
            f"{project.slug}: HyperFrames did not produce a non-empty MP4"
        )
    return project.mp4_file


def render_projects(projects: list[ProjectConfig]) -> None:
    run_id = "quiet-proof-loops-deliverables"
    if len(projects) == 1:
        render_project(projects[0], run_id)
        return
    with ThreadPoolExecutor(max_workers=min(2, len(projects))) as pool:
        futures = {
            pool.submit(render_project, project, run_id): project.slug
            for project in projects
        }
        for future in as_completed(futures):
            future.result()


def ffprobe(path: Path) -> dict[str, object]:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames,nb_read_frames,duration:format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        capture=True,
    )
    return json.loads(result.stdout)


def has_audio(path: Path) -> bool:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture=True,
    )
    return bool(result.stdout.strip())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stream_summary(probe: dict[str, object]) -> dict[str, object]:
    streams = probe.get("streams", [])
    formats = probe.get("format", {})
    if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
        raise RuntimeError("ffprobe returned no video stream")
    stream = streams[0]
    if not isinstance(formats, dict):
        formats = {}
    try:
        return {
            "codec": stream.get("codec_name"),
            "width": int(stream.get("width", 0)),
            "height": int(stream.get("height", 0)),
            "rate": stream.get("r_frame_rate") or stream.get("avg_frame_rate"),
            "frames": int(stream.get("nb_read_frames") or stream.get("nb_frames") or 0),
            "duration": float(stream.get("duration") or formats.get("duration") or 0),
            "bytes": int(formats.get("size") or 0),
        }
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"ffprobe returned invalid stream metadata: {exc}") from exc


def rate_matches(value: object, expected_fps: int) -> bool:
    try:
        return Fraction(str(value)) == expected_fps
    except (ValueError, ZeroDivisionError):
        return False


def validate_stream_summary(
    project: ProjectConfig,
    summary: dict[str, object],
    *,
    label: str,
    expected_codec: str,
    expected_fps: int,
    expected_frames: int,
) -> None:
    profile = project.profile
    if summary["codec"] != expected_codec:
        raise RuntimeError(f"{project.slug}: {label} codec mismatch: {summary}")
    if summary["width"] != profile.width or summary["height"] != profile.height:
        raise RuntimeError(f"{project.slug}: {label} resolution mismatch: {summary}")
    if (
        not rate_matches(summary["rate"], expected_fps)
        or summary["frames"] != expected_frames
    ):
        raise RuntimeError(f"{project.slug}: {label} rate/frame mismatch: {summary}")
    if abs(float(summary["duration"]) - profile.duration_s) > DURATION_TOLERANCE_S:
        raise RuntimeError(f"{project.slug}: {label} duration mismatch: {summary}")
    if int(summary["bytes"]) <= 0:
        raise RuntimeError(f"{project.slug}: {label} is empty")


def video_endpoint_ssim(source: Path, last_frame: int) -> float:
    """Compare decoded endpoints without an intermediate RGB conversion."""
    filter_graph = (
        f"[0:v]split=2[a][b];"
        f"[a]trim=start_frame=0:end_frame=1,setpts=PTS-STARTPTS[first];"
        f"[b]trim=start_frame={last_frame}:end_frame={last_frame + 1},"
        f"setpts=PTS-STARTPTS[last];[first][last]ssim"
    )
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(source),
            "-filter_complex",
            filter_graph,
            "-f",
            "null",
            "-",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    match = re.search(r"All:([0-9.]+)", result.stderr)
    if not match:
        raise RuntimeError("unable to parse endpoint SSIM output")
    return float(match.group(1))


def preflight_mp4(project: ProjectConfig) -> Mp4Evidence:
    path = project.mp4_file
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"{project.slug}: selected MP4 is missing or empty: {path}")
    summary = stream_summary(ffprobe(path))
    validate_stream_summary(
        project,
        summary,
        label="MP4",
        expected_codec="h264",
        expected_fps=project.profile.mp4_fps,
        expected_frames=project.profile.mp4_frames,
    )
    if project.profile.silent and has_audio(path):
        raise RuntimeError(f"{project.slug}: selected MP4 must be silent")
    endpoint_ssim = video_endpoint_ssim(path, project.profile.mp4_frames - 1)
    if endpoint_ssim < project.profile.mp4_endpoint_ssim_min:
        raise RuntimeError(
            f"{project.slug}: MP4 endpoint SSIM {endpoint_ssim:.6f} is below "
            f"{project.profile.mp4_endpoint_ssim_min:.6f}"
        )
    return Mp4Evidence(summary=summary, endpoint_ssim=endpoint_ssim)


def preflight_all_mp4s(projects: list[ProjectConfig]) -> dict[str, Mp4Evidence]:
    evidence: dict[str, Mp4Evidence] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(2, len(projects))) as pool:
        futures = {pool.submit(preflight_mp4, project): project for project in projects}
        for future in as_completed(futures):
            project = futures[future]
            try:
                evidence[project.slug] = future.result()
            except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
                errors[project.slug] = str(exc)
    if errors:
        detail = "\n".join(
            f"- {project.slug}: {errors[project.slug]}"
            for project in projects
            if project.slug in errors
        )
        raise RuntimeError(
            f"input MP4 preflight failed before deliverable writes:\n{detail}"
        )
    return evidence


def extract_sequence(
    source: Path, target: Path, *, fps: int | None = None
) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    if fps is not None:
        command.extend(["-vf", f"fps={fps}"])
    command.extend(["-start_number", "0", str(target / "frame-%03d.png")])
    run(command)
    return sorted(target.glob("frame-*.png"))


def encode_gif(project: ProjectConfig, temp: Path) -> tuple[int, int]:
    profile = project.profile
    frames_dir = temp / f"source-{profile.gif_fps}fps"
    frames = extract_sequence(project.mp4_file, frames_dir, fps=profile.gif_fps)
    if len(frames) != profile.gif_frames:
        raise RuntimeError(
            f"{project.slug}: expected {profile.gif_frames} GIF source frames, found {len(frames)}"
        )
    shutil.copyfile(frames[0], frames[-1])

    selected_colors = PALETTE_COLOR_OPTIONS[-1]
    selected_size = 0
    selected_candidate: Path | None = None
    for colors in PALETTE_COLOR_OPTIONS:
        palette = temp / f"palette-{colors}.png"
        candidate = temp / f"candidate-{colors}.gif"
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(profile.gif_fps),
                "-start_number",
                "0",
                "-i",
                str(frames_dir / "frame-%03d.png"),
                "-vf",
                f"palettegen=max_colors={colors}:stats_mode=full:reserve_transparent=0",
                str(palette),
            ]
        )
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(profile.gif_fps),
                "-start_number",
                "0",
                "-i",
                str(frames_dir / "frame-%03d.png"),
                "-i",
                str(palette),
                "-lavfi",
                "paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                "-loop",
                "0",
                str(candidate),
            ]
        )
        selected_colors = colors
        selected_size = candidate.stat().st_size
        selected_candidate = candidate
        if selected_size <= profile.gif_target_bytes:
            break

    if selected_candidate is None:
        raise RuntimeError(f"{project.slug}: GIF encoder produced no candidate")
    if selected_size > profile.gif_hard_ceiling_bytes:
        raise RuntimeError(
            f"{project.slug}: GIF is {selected_size} bytes after "
            f"{selected_colors} colors; hard ceiling is {profile.gif_hard_ceiling_bytes} bytes"
        )
    shutil.copyfile(selected_candidate, project.gif_file)
    return selected_colors, selected_size


def extract_selected_frames(
    source: Path, output_dir: Path, indices: list[int]
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    expression = "+".join(f"eq(n\\,{index})" for index in indices)
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            f"select='{expression}'",
            "-fps_mode",
            "passthrough",
            "-start_number",
            "0",
            str(output_dir / "selected-%03d.png"),
        ]
    )
    frames = sorted(output_dir.glob("selected-*.png"))
    if len(frames) != len(indices):
        raise RuntimeError(
            f"{source.name}: expected {len(indices)} selected frames, found {len(frames)}"
        )
    return frames


def contact_sheet(frames: list[Path], output: Path, profile: FrameProfile) -> None:
    if len(frames) != 4:
        raise ValueError("contact_sheet requires four frames")
    tile_width = profile.width // 2
    tile_height = profile.height // 2
    if tile_width <= 0 or tile_height <= 0:
        raise RuntimeError("frame dimensions are too small for a contact sheet")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for frame in frames:
        command.extend(["-i", str(frame)])
    command.extend(
        [
            "-filter_complex",
            f"[0:v]scale={tile_width}:{tile_height}:flags=lanczos[a];"
            f"[1:v]scale={tile_width}:{tile_height}:flags=lanczos[b];"
            f"[2:v]scale={tile_width}:{tile_height}:flags=lanczos[c];"
            f"[3:v]scale={tile_width}:{tile_height}:flags=lanczos[d];"
            "[a][b]hstack=inputs=2[top];[c][d]hstack=inputs=2[bottom];"
            "[top][bottom]vstack=inputs=2[out]",
            "-map",
            "[out]",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output),
        ]
    )
    run(command)


def ssim(first: Path, last: Path) -> float:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(first),
            "-i",
            str(last),
            "-lavfi",
            "ssim",
            "-f",
            "null",
            "-",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    match = re.search(r"All:([0-9.]+)", result.stderr)
    if not match:
        raise RuntimeError("unable to parse SSIM output")
    return float(match.group(1))


def review_indices(profile: FrameProfile, *, fps: int, frame_total: int) -> list[int]:
    last = frame_total - 1
    last_time = last / fps
    review_times = (
        0.0,
        min(profile.motion_start_s + 1.0, last_time),
        min(profile.payoff_by_s + min(profile.payoff_hold_s, 0.4), last_time),
        last_time,
    )
    indices = [min(last, max(0, round(moment * fps))) for moment in review_times]
    if len(set(indices)) != 4:
        raise RuntimeError("frame profile does not provide four distinct proof moments")
    return indices


def budget_status(
    project: ProjectConfig, gif_bytes: int, gif_sha256: str
) -> tuple[str, str, str]:
    profile = project.profile
    if gif_bytes > profile.gif_hard_ceiling_bytes:
        raise RuntimeError(f"{project.slug}: GIF exceeds the hard ceiling")
    if gif_bytes <= profile.gif_target_bytes:
        return "PASS", "PASS", "NOT_REQUIRED"
    if project.approved_gif_sha256 == gif_sha256:
        return "PASS_WITH_BUDGET_EXCEPTION", "PASS_WITH_BUDGET_EXCEPTION", "GO"
    return "PASS_WITH_BUDGET_EXCEPTION", "HUMAN_DECISION_REQUIRED", "PENDING"


def format_seconds(index: int, fps: int) -> str:
    return f"{index / fps:.2f}s"


def write_verification(project: ProjectConfig, result: dict[str, object]) -> None:
    profile = project.profile
    brief = project.brief
    truth = required_mapping(brief["truth"], f"{project.slug}.truth")
    gif = required_mapping(result["gif"], f"{project.slug}.gif")
    mp4 = required_mapping(result["mp4"], f"{project.slug}.mp4")
    proof = required_mapping(result["proof"], f"{project.slug}.proof")
    gif_indices = proof["gif_frame_indices"]
    mp4_indices = proof["mp4_frame_indices"]
    if not isinstance(gif_indices, list) or not isinstance(mp4_indices, list):
        raise RuntimeError(f"{project.slug}: invalid proof index data")

    budget_note = ""
    if result["budget_status"] == "PASS_WITH_BUDGET_EXCEPTION":
        budget_note = (
            "- Budget exception account: the encoder exhausted the configured palette "
            "fallbacks; further simplification requires a creative readability review.\n"
        )

    text = f"""# Final Binary Verification

Verified on {date.today().isoformat()}. Product truth was checked on
{required_text(truth, "checked_at", f"{project.slug}.truth")} against
`{required_text(truth, "baseline_commit", f"{project.slug}.truth")}` and release
`{required_text(truth, "release_tag", f"{project.slug}.truth")}`.

## Claim and evidence

- **Claim:** {required_text(brief, "claim", project.slug)}
- **Binary proof:** {required_text(brief, "payoff_state", project.slug)}
- **Highest uncertainty:** {required_text(brief, "uncertainty", project.slug)}

## Artifact-derived proof

- `renders/proof-from-final-gif.jpg` uses delivered GIF frames
  {", ".join(str(index) for index in gif_indices)}
  ({", ".join(format_seconds(index, profile.gif_fps) for index in gif_indices)}).
- `renders/proof-from-final-mp4.jpg` uses delivered MP4 frames
  {", ".join(str(index) for index in mp4_indices)}
  ({", ".join(format_seconds(index, profile.mp4_fps) for index in mp4_indices)}).
- The selected binary-derived frames remain beside the contact sheets.

## Delivered artifacts

| Artifact | Codec | Resolution | Duration | Rate | Frames | Size | SHA-256 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `{project.gif_file.relative_to(project.root)}` | {gif["codec"]} | {gif["width"]}x{gif["height"]} | {gif["duration"]:.3f}s | {profile.gif_fps} fps | {gif["frames"]} | {gif["bytes"]:,} bytes | `{result["gif_sha256"]}` |
| `{project.mp4_file.relative_to(project.root)}` | {mp4["codec"]} | {mp4["width"]}x{mp4["height"]} | {mp4["duration"]:.3f}s | {profile.mp4_fps} fps | {mp4["frames"]} | {mp4["bytes"]:,} bytes | `{result["mp4_sha256"]}` |

## Budget and loop seam

- GIF palette: {result["palette_colors"]} colors, global palette, {profile.gif_fps} fps, infinite loop.
- GIF budget: target <= {profile.gif_target_bytes:,} bytes; hard ceiling <=
  {profile.gif_hard_ceiling_bytes:,} bytes; observed {gif["bytes"]:,} bytes —
  **{result["budget_status"]}**.
{budget_note}- GIF frame 0 versus frame {profile.gif_frames - 1}: decoded PNGs byte-identical
  and SSIM `{result["gif_ssim"]:.6f}` — **PASS**.
- MP4 frame 0 versus frame {profile.mp4_frames - 1}: SSIM
  `{result["mp4_ssim"]:.6f}` against threshold
  `>={profile.mp4_endpoint_ssim_min:.6f}` — **PASS**.
- Final status: **{result["final_status"]}**.

## Reproducibility

- HyperFrames pin: `{project.hyperframes_pin}` from `{project.package_file.relative_to(project.root)}` scripts.
- Checksums: `{project.render_dir.relative_to(project.root) / "SHA256SUMS"}`.

## Locked scope

This selected project changes only its ignored delivery outputs: the {profile.width}x{profile.height}
GIF/MP4, binary-derived proof, verification JSON, checksum manifest, and this
receipt. No product, API, Home Assistant, publishing, commit, deployment, or
other managed-project output is included.

## Human decision

Human decision: {result["human_decision"]}
{DECISION_HASH_PREFIX} `{result["gif_sha256"]}`
"""
    project.verification_file.write_text(text, encoding="utf-8")


def write_sha256s(project: ProjectConfig, files: list[Path]) -> Path:
    checksum_file = project.render_dir / "SHA256SUMS"
    unique_files = sorted(
        set(files), key=lambda path: path.relative_to(project.root).as_posix()
    )
    lines = [
        f"{sha256(path)}  {path.relative_to(project.root).as_posix()}"
        for path in unique_files
    ]
    checksum_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return checksum_file


def verify_and_encode(
    project: ProjectConfig, mp4_evidence: Mp4Evidence
) -> dict[str, object]:
    profile = project.profile
    print(f"[{project.slug}] encoding GIF and deriving binary proof", flush=True)
    with tempfile.TemporaryDirectory(prefix=f"{project.slug}-") as temp_name:
        temp = Path(temp_name)
        colors, _ = encode_gif(project, temp)

        gif_frames = extract_sequence(project.gif_file, temp / "gif-decoded")
        if len(gif_frames) != profile.gif_frames:
            raise RuntimeError(
                f"{project.slug}: expected {profile.gif_frames} decoded GIF frames, "
                f"found {len(gif_frames)}"
            )
        gif_ssim = ssim(gif_frames[0], gif_frames[-1])
        if (
            not filecmp.cmp(gif_frames[0], gif_frames[-1], shallow=False)
            or gif_ssim != 1.0
        ):
            raise RuntimeError(
                f"{project.slug}: GIF endpoints are not pixel-identical (SSIM {gif_ssim:.6f})"
            )

        gif_indices = review_indices(
            profile, fps=profile.gif_fps, frame_total=profile.gif_frames
        )
        mp4_indices = review_indices(
            profile, fps=profile.mp4_fps, frame_total=profile.mp4_frames
        )
        gif_selected = [gif_frames[index] for index in gif_indices]
        mp4_selected = extract_selected_frames(
            project.mp4_file, temp / "mp4-selected", mp4_indices
        )

        gif_named: list[Path] = []
        mp4_named: list[Path] = []
        for index, source in zip(gif_indices, gif_selected):
            target = project.render_dir / f"proof-from-gif-frame-{index:03d}.png"
            shutil.copyfile(source, target)
            gif_named.append(target)
        for index, source in zip(mp4_indices, mp4_selected):
            target = project.render_dir / f"proof-from-mp4-frame-{index:03d}.png"
            shutil.copyfile(source, target)
            mp4_named.append(target)
        gif_sheet = project.render_dir / "proof-from-final-gif.jpg"
        mp4_sheet = project.render_dir / "proof-from-final-mp4.jpg"
        contact_sheet(gif_named, gif_sheet, profile)
        contact_sheet(mp4_named, mp4_sheet, profile)

    gif_summary = stream_summary(ffprobe(project.gif_file))
    validate_stream_summary(
        project,
        gif_summary,
        label="GIF",
        expected_codec="gif",
        expected_fps=profile.gif_fps,
        expected_frames=profile.gif_frames,
    )
    if profile.silent and has_audio(project.gif_file):
        raise RuntimeError(f"{project.slug}: delivered GIF must be silent")

    gif_digest = sha256(project.gif_file)
    budget, final_status, human_decision = budget_status(
        project, int(gif_summary["bytes"]), gif_digest
    )
    proof_files = gif_named + mp4_named + [gif_sheet, mp4_sheet]
    result: dict[str, object] = {
        "project": project.slug,
        "verified_on": date.today().isoformat(),
        "hyperframes_version": project.hyperframes_pin,
        "gif": gif_summary,
        "mp4": mp4_evidence.summary,
        "palette_colors": colors,
        "gif_sha256": gif_digest,
        "mp4_sha256": sha256(project.mp4_file),
        "gif_ssim": gif_ssim,
        "mp4_ssim": mp4_evidence.endpoint_ssim,
        "gif_target_bytes": profile.gif_target_bytes,
        "gif_hard_ceiling_bytes": profile.gif_hard_ceiling_bytes,
        "mp4_endpoint_ssim_min": profile.mp4_endpoint_ssim_min,
        "budget_status": budget,
        "human_decision": human_decision,
        "final_status": final_status,
        "status": final_status,
        "proof": {
            "gif_frame_indices": gif_indices,
            "mp4_frame_indices": mp4_indices,
            "files": [
                path.relative_to(project.root).as_posix() for path in proof_files
            ],
            "sha256": {
                path.relative_to(project.root).as_posix(): sha256(path)
                for path in proof_files
            },
        },
    }
    verification_json = project.render_dir / "verification.json"
    verification_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    write_verification(project, result)
    write_sha256s(
        project,
        [
            project.gif_file,
            project.mp4_file,
            *proof_files,
            verification_json,
            project.verification_file,
        ],
    )
    print(
        f"[{project.slug}] verified: GIF {gif_summary['bytes']} bytes, "
        f"GIF seam {gif_ssim:.6f}, MP4 seam {mp4_evidence.endpoint_ssim:.6f}, "
        f"status {final_status}",
        flush=True,
    )
    return result


def self_test() -> None:
    """Exercise hash-bound approval semantics without rendering media."""

    approved_digest = "a" * 64
    different_digest = "b" * 64
    with tempfile.TemporaryDirectory(prefix="quiet-proof-loops-builder-test-") as name:
        root = Path(name)
        receipt = root / "VERIFICATION.md"
        receipt.write_text(f"{HUMAN_GO_LINE}\n", encoding="utf-8")
        if read_human_approval(receipt) is not None:
            raise RuntimeError("approval without a decision hash did not fail closed")
        receipt.write_text(
            f"{HUMAN_GO_LINE}\n{DECISION_HASH_PREFIX} `{approved_digest}`\n",
            encoding="utf-8",
        )
        if read_human_approval(receipt) != approved_digest:
            raise RuntimeError("hash-bound approval was not parsed")

        profile = FrameProfile(
            width=720,
            height=1280,
            duration_s=6.0,
            gif_fps=15,
            mp4_fps=30,
            gif_frames=90,
            mp4_frames=180,
            gif_target_bytes=100,
            gif_hard_ceiling_bytes=200,
            mp4_endpoint_ssim_min=0.999,
            silent=True,
            motion_start_s=0.8,
            payoff_by_s=3.0,
            payoff_hold_s=2.0,
        )
        project = ProjectConfig(
            slug="approval-self-test",
            root=root,
            adapter={},
            brief={},
            profile=profile,
            render_dir=root / "renders",
            verification_file=receipt,
            package_file=root / "package.json",
            mp4_file=root / "renders/output.mp4",
            gif_file=root / "renders/output.gif",
            hyperframes_pin="0.0.0",
            approved_gif_sha256=approved_digest,
        )
        if budget_status(project, 101, approved_digest)[2] != "GO":
            raise RuntimeError("matching hash-bound approval was not honored")
        if budget_status(project, 101, different_digest)[2] != "PENDING":
            raise RuntimeError("stale approval hash did not require a new decision")
        if budget_status(project, 100, different_digest)[2] != "NOT_REQUIRED":
            raise RuntimeError("within-budget render incorrectly required approval")

        source = root / "BRIEF.md"
        source_paths = {"brief_file": source}
        try:
            validate_output_paths(
                "output-path-self-test",
                root,
                source_paths,
                root / "renders",
                source,
            )
        except RuntimeError as exc:
            if "must not overwrite a source file" not in str(exc):
                raise RuntimeError(
                    f"source-overwrite guard returned wrong failure: {exc}"
                ) from exc
        else:
            raise RuntimeError("source-overwrite guard did not fail closed")

        try:
            validate_output_paths(
                "output-path-self-test",
                root,
                source_paths,
                root / "renders",
                root / "renders/output.gif",
            )
        except RuntimeError as exc:
            if "generated-output collisions" not in str(exc):
                raise RuntimeError(
                    f"generated-output collision guard returned wrong failure: {exc}"
                ) from exc
        else:
            raise RuntimeError("generated-output collision guard did not fail closed")

    print("Quiet Proof Loop builder self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project", metavar="SLUG", help="process one managed project only"
    )
    parser.add_argument(
        "--skip-render", action="store_true", help="reuse existing MP4 masters"
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run non-rendering builder guard self-tests",
    )
    options = parser.parse_args()

    if options.self_test:
        if options.project or options.skip_render:
            parser.error(
                "--self-test cannot be combined with project or render options"
            )
        self_test()
        return 0

    managed = load_manifest()
    selected_entries = select_projects(managed, options.project)
    support = load_support_module()
    projects = [load_project(entry, support) for entry in selected_entries]
    require_binaries(render=not options.skip_render)

    if not options.skip_render:
        render_projects(projects)

    # This full, read-only preflight happens for every selected MP4 before the
    # first GIF, proof frame, receipt, checksum, or batch-summary write.
    mp4_evidence = preflight_all_mp4s(projects)
    results = [
        verify_and_encode(project, mp4_evidence[project.slug]) for project in projects
    ]

    selected_mode = options.project is not None
    if not selected_mode:
        summary = {entry["project"]: entry for entry in results}
        (ROOT / "gif-batch-verification.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )

    pending = [
        str(result["project"])
        for result in results
        if result["final_status"] == "HUMAN_DECISION_REQUIRED"
    ]
    if pending:
        raise RuntimeError(
            "budget exception requires a literal standalone "
            f"{HUMAN_GO_LINE!r} bound to the current {DECISION_HASH_PREFIX!r} "
            f"in the project receipt: {', '.join(pending)}"
        )

    scope = (
        f"selected project {projects[0].slug}"
        if selected_mode
        else f"{len(projects)} default projects"
    )
    print(f"Quiet Proof Loop deliverables verified ({scope})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
