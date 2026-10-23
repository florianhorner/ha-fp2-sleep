#!/usr/bin/env python3
"""Build the planned dashboard SVG from explicitly constructed illustration data.

Run this script from any directory. From the repository root, rasterize with:

    npm exec --yes --package=resvg-cli@2.6.2 -- resvg-js assets/last-night.svg assets/last-night.png

The SVG fixes the native size at 880 by 560. Rendering uses the system Arial
font, so antialiasing and font metrics can differ across operating systems.
The PNG is documentation art, not a Home Assistant screenshot or evidence of
a recorded night.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "assets/last-night.fixture.json"
SVG = ROOT / "assets/last-night.svg"
COLORS = {"Deep": "#2758d8", "Light": "#5aa2ff", "REM": "#f5a623"}


def build_svg(fixture: dict) -> str:
    """Keep illustrative values separate from the presentation source."""
    if fixture.get("data_origin") != "constructed illustration; no recorded telemetry":
        raise ValueError("dashboard preview requires explicitly constructed data")
    segments = fixture["stage_segments"]
    if not segments or any(
        segment["stage"] not in COLORS
        or type(segment["units"]) is not int
        or segment["units"] <= 0
        for segment in segments
    ):
        raise ValueError("stage segments must use positive illustrative units and supported labels")
    bars = []
    x = 46.0
    total = sum(segment["units"] for segment in segments)
    for segment in segments:
        width = 668 * segment["units"] / total
        bars.append(
            f'<rect x="{x:.2f}" y="313" width="{width:.2f}" height="20" '
            f'fill="{COLORS[segment["stage"]]}"/>'
        )
        x += width
    heart = fixture["heart_rate"]
    breathing = fixture["breathing_rate"]
    for reading in (heart, breathing):
        if any(type(reading[key]) is not int for key in ("average", "low", "high")):
            raise ValueError("illustrative readings must be integer constants")
        if not 0 < reading["low"] <= reading["average"] <= reading["high"]:
            raise ValueError("illustrative reading bounds are inconsistent")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="880" height="560" viewBox="0 0 880 560" role="img" aria-labelledby="title desc">
  <title id="title">Planned dashboard preview</title>
  <desc id="desc">Heart rate, breathing rate and indicative sleep stages. All values and stage segments are constructed illustration, not recorded telemetry.</desc>
  <defs><clipPath id="timeline"><rect x="46" y="313" width="668" height="20" rx="6"/></clipPath></defs>
  <rect width="880" height="560" fill="#101112"/>
  <rect x="24" y="24" width="712" height="359" rx="14" fill="#1b1c1e"/>
  <g font-family="Arial, sans-serif" font-size="12" fill="#9a9da3">
    <text x="46" y="57">LAST NIGHT · SYNTHETIC ILLUSTRATION</text>
    <text x="46" y="90" fill="#e8e8ea" font-size="20">Planned dashboard preview. Heart rate, breathing rate</text>
    <text x="46" y="118" fill="#e8e8ea" font-size="20">and indicative sleep stages.</text>
    <rect x="46" y="145" width="327" height="89" rx="10" fill="#151617" stroke="#2b2d31"/>
    <rect x="388" y="145" width="326" height="89" rx="10" fill="#151617" stroke="#2b2d31"/>
    <circle cx="66" cy="165" r="4.5" fill="#ff4d57"/>
    <text x="78" y="169">Heart rate</text>
    <text x="62" y="199" fill="#e8e8ea" font-size="26" font-weight="700">{heart["average"]}</text>
    <text x="98" y="199">bpm avg</text>
    <text x="62" y="217">{heart["low"]} low · {heart["high"]} high · illustration</text>
    <circle cx="408" cy="165" r="4.5" fill="#5aa2ff"/>
    <text x="420" y="169">Breathing</text>
    <text x="404" y="199" fill="#e8e8ea" font-size="26" font-weight="700">{breathing["average"]}</text>
    <text x="440" y="199">br/min avg</text>
    <text x="404" y="217">{breathing["low"]} low · {breathing["high"]} high · illustration</text>
    <text x="48" y="250" font-size="11">Illustration only. These values are not recorded telemetry.</text>
    <path d="M46 271.5H714" stroke="#2b2d31"/>
    <text x="46" y="301" fill="#e8e8ea" font-size="14">Sleep stages</text>
    <text x="714" y="301" text-anchor="end" font-size="10">the sensor’s best guess</text>
    <g clip-path="url(#timeline)">{"".join(bars)}</g>
    <rect x="46" y="349" width="10" height="10" rx="3" fill="#2758d8"/>
    <text x="65" y="358" fill="#e8e8ea">Deep</text>
    <rect x="184" y="349" width="10" height="10" rx="3" fill="#5aa2ff"/>
    <text x="203" y="358" fill="#e8e8ea">Light</text>
    <rect x="322" y="349" width="10" height="10" rx="3" fill="#f5a623"/>
    <text x="341" y="358" fill="#e8e8ea">REM</text>
    <text x="714" y="358" text-anchor="end">Illustrative stage segments</text>
  </g>
</svg>
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check the tracked SVG without writing")
    options = parser.parse_args()
    expected = build_svg(json.loads(FIXTURE.read_text(encoding="utf-8")))
    if options.check:
        if SVG.read_text(encoding="utf-8") != expected:
            raise SystemExit("dashboard preview SVG differs from its constructed fixture")
        print("Dashboard preview SVG matches its constructed fixture")
    else:
        SVG.write_text(expected, encoding="utf-8")
        print("Built assets/last-night.svg from constructed illustration data")


if __name__ == "__main__":
    main()
