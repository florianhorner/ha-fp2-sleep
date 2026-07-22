---
schema_version: 1
system: quiet-proof-loops
profile: midnight-console
canvas:
  width_px: 720
  height_px: 1280
  aspect: "9:16"
duration_s: 6
source_fps: 30
silent: true
gif:
  fps: 15
  target_bytes: 700000
  hard_ceiling_bytes: 1000000
  loop_mode: infinite
  endpoint: pixel-identical
mp4:
  fps: 30
  endpoint_ssim_min: 0.998
palette:
  background: "#0b1020"
  surface: "#151d31"
  border: "#34405a"
  text: "#f4f7ff"
  muted: "#aab5ce"
  radar_blue: "#62d2a2"
  deep_blue: "#31846a"
  heart_red: "#ff6b6b"
  estimate_amber: "#ffd166"
  unknown_gray: "#6d7892"
typography:
  family: Inter
  hook_weight: 640
  hook_size_px: 54
  hook_line_height: 1.05
hook:
  left_px: 60
  top_px: 110
  width_px: 600
  max_lines: 2
card:
  width_px: 600
  radius_px: 12
  border_px: 1
timing:
  motion_start_s: 0.75
  payoff_by_s: 2.9
  payoff_hold_s: 1.6
  return_start_s: 5.2
  return_complete_by_s: 5.88
  opening_hold_s: 0.12
forbidden_treatments:
  - gradients
  - invented_telemetry
  - medical_language
  - safety_language
  - generic_wellness_imagery
  - random_motion
  - camera_theatrics
---

# Fixture profile

Only this front matter is normative.
