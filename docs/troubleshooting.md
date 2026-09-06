# Troubleshooting the Blender face pipeline

| Symptom | Inspect first | Supported response |
| --- | --- | --- |
| Rig appears in hair / wrong facial region | Selected mesh, named teeth, measured mouth and pivot | Pass `--obj` and explicit dental names. Do not trust head vertex count. |
| Jagged lower lip when jaw rotates | Automatic seam cut and interior-vs-visible mouth measurement | Compare a fresh source build with `--no-split-seam`; for visibly open mouths compare `--mouth-mode aperture`. |
| Jaw stops opening beyond a small angle | `face_rig` jaw Limit Rotation constraint | Report actual evaluated range; fix measurement before widening a protective cap. |
| Lips stretch into a membrane | Which faces bridge upper/lower lip, jaw weights, cavity | Diagnose on evaluated mesh; a cut is not always the right fix. |
| Corners tear | Per-face weight spread AND evaluated area change | Use the commissure helper only on confirmed bridging skin faces; exclude teeth. |
| Teeth visible through skin | Source tooth placement in front and side views, lip seal | Correct source placement; sweep seal strength and rebuild a copy. |
| Mouth fills with a gray slab in QA | Untextured material viewport color | Match it to shader Base Color; distinguish shading from geometry. |
| Eye/brow channels exist but do nothing | Separate objects, shell roles, actual key deltas | Prepare/bind those parts explicitly. Key count alone is not functionality. |
| Lashes float on blinking | Lash islands and generated blink deltas | Inspect `attach_lashes.py` and transfer only intended lid motion. |
| Rhubarb fails | WAV format, executable path, stderr | Export a valid WAV; use the installed executable; do not continue on failure. |
| Wrong face after reanimation | Selected mesh and matching build profile | Use `--obj`; do not remeasure already-cut geometry or borrow another profile. |
| No audio | Sound strip, absolute WAV path, audio device/mute settings | Keep the file reachable and inspect actual playback. |
| Reference and inspected file disagree | Blender window, filepath, dirty state, MCP port | Snapshot the correct live file; verify the execution endpoint, not just status. |

## Geometry rules

Weights use Basis coordinates. Sealing lips first can put both rims at the
same height and destroy the upper/lower distinction. After splitting topology,
recompute component IDs and all vertex-indexed data. Coincident seam vertices
may be intentional; welding them can close an animated mouth.

Keep upper dental geometry rigid on `head`, lower dental geometry rigid on
`jaw`. Use an armature modifier plus full-weight vertex group for the tongue.
Avoid bone parenting while editing the rest rig. Any geometry edit to a mesh
with shape keys must account for every affected key, not only Basis.

Do not use whole-head subdivision as a routine deformation repair: it can
shrink the head around fitted teeth or change the inner mouth. First diagnose
landmarks, weights, seams, and driver interactions. Missing deformation topology
can matter, but a bad result does not establish that topology is the cause.

## Scope and acceptance

Numeric gates can pass while a face looks wrong. They can also flag an
intentionally tooth-showing neutral expression. Preserve the failure report,
show the result, and distinguish visual acceptance from all-gates success.
One character's accepted mouth/seal settings are not defaults for every head.
When repeated attempts stop improving the result, explain the remaining issue
and agree on a targeted manual adjustment or a different scope.

The archived canonical fitting path and legacy marker wizard are not the main
workflow. Unity code is an optional integration starting point with additional
project/package assumptions; a Blender preview does not certify a Unity avatar.
