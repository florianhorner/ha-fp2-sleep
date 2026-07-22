---
schema_version: 1
workflow: motion-graphics
flow: automation
storyboard: false
message: "A documented SleepRadar state can cap bedroom-light brightness at 20% through an optional Home Assistant comfort automation"
destination: vertical-social
aspect: "720x1280"
language: en
audience: "Aqara FP2 owners who use Home Assistant"
length: "6s"
angle: automation-chain
narration: false
claim: "A documented optional Home Assistant comfort automation can cap a bedroom light at 20 percent while SleepRadar reports asleep."
opening_state: "The trigger, asleep condition, comfort automation, and unresolved brightness response are all visible and neutral."
payoff_state: "Causal flow reaches the response and resolves Brightness from a dash to 20 percent."
motion_verb: flow
uncertainty: "Whether the full trigger-condition-action chain remains readable within one vertical frame."
truth:
  source_refs:
    - "examples/automations.yaml:1-33"
    - "examples/sleep_tracking.yaml:61-72"
    - "README.md:206-220"
  checked_at: "2026-07-21"
  baseline_commit: "995f81b402cbd15ed0500a6968a96d94c427933e"
  release_tag: "v1.2.1"
  qualifiers:
    - "This is an optional Home Assistant comfort example, not built-in or safety-critical behavior."
  visible_required:
    - "Asleep?"
    - "Lights cap at 20%."
    - "Bedroom light"
    - "FP2 Asleep"
    - "Cap light brightness"
    - "comfort automation"
    - "Brightness"
    - "20%"
    - "Optional Home Assistant example"
  visible_forbidden:
    - "emergency"
    - "safety"
---

## Intent

Create GIF 5 in the approved SleepRadar batch. The frame-zero hook is:

Asleep?
Lights cap at 20%.

Show one shipped example as a clear trigger plus condition to comfort automation
to response chain. Keep the example visibly optional and keep every claim inside
the documented Home Assistant behavior.

## Product truth

- Product baseline rechecked on 2026-07-21: origin/main is
  995f81b402cbd15ed0500a6968a96d94c427933e.
- Latest release rechecked by the batch orchestrator: v1.2.1, published
  2026-07-03.
- ../../examples/automations.yaml:14-33 is the canonical source for the alias
  Cap light brightness while asleep, the bedroom-light on trigger,
  binary_sensor.fp2_asleep equals on condition, and brightness_pct: 20 action.
- ../../examples/sleep_tracking.yaml:61-72 defines binary_sensor.fp2_asleep from
  the sensor-reported REM, Light sleep, or Deep sleep codes and preserves
  unavailable-state handling.
- The automation file itself labels these as optional examples. This GIF
  therefore says Optional Home Assistant example and comfort automation on
  screen.

## Locked creative

- Hook geometry, palette, typography, card surfaces, and calm motion follow the
  approved GIF 1 pilot without modifying or rerendering it.
- Opening state: four neutral Home Assistant nodes show Bedroom light · on,
  FP2 Asleep · on, Cap light brightness with an always-visible comfort
  automation qualifier, and Brightness · —.
- From 0.8 seconds, the trigger and condition activate in order, flow reaches
  the comfort automation, and Brightness · 20% is fully visible by 3.0 seconds.
- The payoff holds through 5.25 seconds, reverses through 5.9 seconds, and the
  exact opening state holds through 6.0 seconds.
- The chain is the hero. The 20% output state is the payoff.

## Assets

No visual or media assets. Inter Variable and GSAP 3.14.2 are pinned inside the
project as local runtime assets, so checks and renders make no external font or
script requests.

## Guardrails

- Present this only as an optional Home Assistant comfort example.
- Do not imply certainty beyond the helper's documented state mapping.
- Do not imply emergency, monitoring, diagnostic, clinical, or protective
  behavior.
- Do not imply built-in automatic support beyond the example YAML.
- Use no personal telemetry, audio, gradients, random motion, or network
  fetches.
- Do not modify product, API, Home Assistant, Conductor, policy, or GIF 1 files.

## Beat sheet

| Time | Beat |
| --- | --- |
| 0.00–0.80s | Frame-zero hook and complete neutral chain remain readable. |
| 0.80–1.30s | Bedroom light trigger activates and sends the first flow segment. |
| 1.30–1.82s | FP2 Asleep condition activates and the condition path resolves. |
| 1.82–2.42s | Cap light brightness comfort automation activates. |
| 2.42–3.00s | The response resolves from Brightness · — to Brightness · 20%. |
| 3.00–5.25s | Full chain and 20% payoff hold without decorative motion. |
| 5.25–5.90s | Output, automation, condition, and trigger reverse to neutral. |
| 5.90–6.00s | Exact CSS opening state holds for the loop seam. |

## Delivery

This worker authors and lints source only. Final checks, snapshots, MP4/GIF
rendering, binary-derived proof, hashes, loop metrics, and localhost handoff
remain pending for the batch orchestrator.
