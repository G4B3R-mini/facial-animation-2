# QA and optional repair tools

The maintained tools live in `scripts/face_pipeline/` and are shared by the
Codex and Claude skills. The older Claude script paths forward to these tools.
Use background Blender on copies for diagnostics and renders. None of the
commands below implicitly modifies an open editor session.

| Tool | Purpose |
| --- | --- |
| `audit_scene.py` | Source inventory, shading, shell/duplicate and orientation warnings; `--obj NAME` |
| `diagnose_rig.py` | Evaluate animation or synthetic key poses AND direct jaw poses; report face area changes and dental weights; `--obj NAME` |
| `qa_render.py` | Neutral, direct jaw, expression and blink images at bust distance; optional `--closeup`, `--obj NAME`, `--tag NAME` |
| `make_sheet.py` | Assemble QA images with regular Python + Pillow; `--kind bust` or `mouth` |
| `reanimate.py` | Rhubarb cues + audio to a separate animated blend using embedded or explicit profile |
| `fix_commissure.py` | Optional local corner weight/delta smoothing; inspect `--dry` first; `--obj NAME` |
| `place_teeth.py` | Approximate placement from a user-supplied donor; inspect front/side before accepting |
| `attach_lashes.py` | Optional transfer of lid motion to small detached islands; inspect `--dry` / `--object NAME` |
| `ambient_face.py` | Advanced: replace speech performance with an ambient face loop |
| `unity_prep.py` | Merge assembled armatures, preserve shape keys, retarget drivers and export a neutral Unity FBX; see agent-wizard.md |

Read the helper's module docstring for its exact invocation before using an
optional repair tool. Do not apply corner smoothing or lash transfer globally
because a diagnostic listed it as a possibility.

Useful indicators include per-face evaluated area ratio (large spikes around
2.6â€“3x deserve inspection), changes between animation samples, weight spread
on bridging faces, and rigid dental weights. These are debugging heuristics,
not universal quality thresholds. Degenerate/tiny source polygons can inflate
ratios; inspect the corresponding faces. A weight spread by itself is not a tear.

`diagnose_rig.py` historically uses geometric/material heuristics to identify
teeth when named dental groups are absent; fragmented arches can be missed.
Confirm component membership and vertex weights before accepting its dental
classification or using it as a repair mask. For precise skin-only measures,
use the build report's component roles and recheck them after any topology edit.

QA requested angles are 9 and 18 degrees. The rig may clamp them; inspect the
limit recorded in QA/diagnostic JSON before comparing two apparently equal poses.
Shape-key-only sweeps are not a substitute for the actual jaw-bone test.
