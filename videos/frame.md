---
schema_version: 1
system: quiet-proof-loops
profile: sleepradar
canvas:
  width_px: 720
  height_px: 1280
  aspect: "9:16"
duration_s: 6
source_fps: 30
silent: true
gif:
  fps: 15
  target_bytes: 768000
  hard_ceiling_bytes: 1048576
  loop_mode: infinite
  endpoint: pixel-identical
mp4:
  fps: 30
  endpoint_ssim_min: 0.999
palette:
  background: "#101112"
  surface: "#1b1c1e"
  border: "#2b2d31"
  text: "#e8e8ea"
  muted: "#9a9da3"
  radar_blue: "#5aa2ff"
  deep_blue: "#2758d8"
  heart_red: "#ff4d57"
  estimate_amber: "#f5a623"
  unknown_gray: "#747982"
typography:
  family: Inter
  hook_weight: 650
  hook_size_px: 56
  hook_line_height: 1.04
hook:
  left_px: 56
  top_px: 118
  width_px: 608
  max_lines: 2
card:
  width_px: 608
  radius_px: 14
  border_px: 1
timing:
  motion_start_s: 0.8
  payoff_by_s: 3.0
  payoff_hold_s: 1.5
  return_start_s: 5.25
  return_complete_by_s: 5.9
  opening_hold_s: 0.1
forbidden_treatments:
  - gradients
  - invented_telemetry
  - medical_language
  - safety_language
  - generic_wellness_imagery
  - random_motion
  - camera_theatrics
---

# SleepRadar video profile

The YAML front matter is the only normative source for shared SleepRadar clip
tokens. The validator rejects unknown or duplicate keys and checks every
projection in episode shot plans, composition metadata, CSS, motion assertions,
and delivered-binary QA.

The values describe a low-glare, vertical Home Assistant proof loop. They do
not contain product claims. `DESIGN.md` owns SleepRadar voice and semantic
honesty; each episode `BRIEF.md` owns its claim and evidence.

Other projects can reuse Quiet Proof Loops by copying the schema and supplying
their own profile values. They should not copy SleepRadar colors by default.
