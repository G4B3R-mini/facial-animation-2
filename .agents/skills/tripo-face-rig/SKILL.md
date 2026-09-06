---
name: tripo-face-rig
description: Prepare, rig, diagnose, and animate a generated character head in Blender with this repository, including artist-placed teeth and tongue, facial expressions, and a Rhubarb audio test. Use for a prompt-driven head-to-speaking-preview, manual body attachment handoff, skeleton merge, FBX export, and Unity scene setup pipeline.
---

# Tripo face rig

Work with the user's character from model preparation through an inspectable
rigged and animated Blender file. This is a repository skill: keep the clone
available, and resolve the repository root three levels above this directory.
Use `scripts/face_pipeline/` as the shared implementation; the Claude entrypoint
uses the same scripts. No separate Codex-specific rig builder is needed.

Read [the agent wizard](../../../docs/agent-wizard.md) for stage handoffs and prerequisite checks.
Read [Unity integration](../../../docs/unity.md) for assembled-body export and scene wiring.

Read [the workflow](../../../docs/workflow.md) for preparation and commands.
Read [troubleshooting](../../../docs/troubleshooting.md) when measurement,
deformation, or audio playback fails. For numeric QA and optional repair tools,
read [diagnostics](../../../docs/diagnostics.md).

## Start at the user's current stage

- **Model creation / placement:** the user supplies or creates the model and
  chooses the generation tool. Inventory head, hair, eyes, brows, lashes, upper
  teeth, lower teeth, and tongue. Help place/scale parts when asked. Show front
  and side views to check dental placement and mouth depth. Keep a prepared
  source copy before rigging; do not substitute a different character.
- **Prerequisites:** run `doctor.ps1` for the requested stage. Report all missing
  tools with official download/install steps and executable configuration. Use
  Blender background processing when live MCP is unavailable.
- **Audit:** run `scripts/face_pipeline/audit_scene.py` on a background copy.
  Pass `--obj` when the head is known. Hair can have more vertices than skin;
  never select the head by vertex count alone. Present actionable findings,
  perform authorized reversible preparation, and ask about unresolved artistic
  choices only when needed. Audit guesses are not proof of anatomy.
- **Build:** use `rig.ps1` or `autorig.py` on the prepared source. Keep generated
  `.blend` and matching JSON report together under `work/<character>/`.
  The wrapper keeps seams intact by default. Choose aperture/seam options from
  actual mouth geometry, not from a previous character's preset. Review bones,
  0/9/18-degree jaw poses, lip corners, teeth/tongue, and blink before speech.
- **Diagnose and fix:** compare the source, current rig, and any supplied
  reference under equivalent framing. Inspect measured mouth width/height,
  pivot, weights, drivers, and topology before adding more geometry. Apply only
  fixes supported by evidence; compare again. Report limitations honestly.
- **Audio test:** use the supplied sample WAV after inspecting the rig. A combined
  rig-and-animate request authorizes both steps without another approval question.
  Run `lipsync.ps1` on that rig, using its embedded profile or matching report.
  It runs Rhubarb and replaces actions in a separate output, preserving geometry
  and drivers. Verify speech cues, jaw/tongue motion, visemes, sound strip, FPS,
  blinks/gaze, and the saved file. Show/list the output and simplest repeat command.
- **Manual body handoff:** after the user reviews playback, let them attach the
  approved head to their rigged full body and return an assembled `.blend`.
  Preserve that source; the preview file is not a substitute for this handoff.
- **Skeleton/export:** inspect the assembled scene, identify both armatures and
  the body head bone, then run `export-unity.ps1`. Check the export report, import
  the FBX into a fresh scene, and verify the hierarchy and deforming shape keys.
- **Unity scene:** install the maintained subset, import character/audio/cues,
  configure the Humanoid Avatar, preserve the body controller and wire the generic
  CharacterPipelineSetup. Verify channel ownership and Play-mode motion/audio;
  save the requested scene/prefab. See the Unity guide for the complete contract.
  For an installable release, run `python scripts/build_unity_package.py` and
  provide `dist/TripoFaceRig-Unity.unitypackage`. The Character Pipeline window
  accepts a model, voice, idle and speaking clips and builds/assigns its controller.
  `CharacterPipelineSetup.Build` is the equivalent agent API; `Configure` alone
  only wires face/audio. Preserve the imported neutral Humanoid jaw muscle value
  in the idle; omitting jaw curves can open the mouth at rest.

## Invariants

- Keep source appearance, textures, and user-authored placement. Bone-parenting
  teeth/tongue is fragile when rest bones change: use armature modifiers and
  full bone weights instead. Upper teeth stay on the head; lower teeth stay
  rigid on the jaw. Exclude dental vertices from lip smoothing.
- A continuous mouth cavity can be visibly open with zero boundary edges.
  Automatic `invaginated` detection is not proof that a seam should be cut.
  Wrong mouth landmarks can produce bad weights even on good topology.
- Work from Basis coordinates. Topology edits invalidate cached vertex indices,
  component roles, and measurements. Do not weld intentional split-lip vertices.
- Separate eye/brow/lash objects are not automatically integrated by the basic
  build. Prepare them as disconnected shells in the head, or explicitly bind
  them and verify. Do not claim 52 functional expressions from key names alone.
- Numerical gates are evidence, not artistic acceptance. Show neutral and
  expressive views at conversation distance using Workbench FLAT/TEXTURE and
  correct untextured material viewport colors. Report failed gates even when
  a review file was saved. Use the user's accepted result as the next-stage input.
- `--open-deg` sets the verification test angle, not the rig's limit. Inspect the
  jaw constraint and distinguish requested rotation from evaluated rotation.

## Live Blender and handoffs

Use the available Blender MCP integration if connected; it is optional. Inspect
the actual filepath, selected mesh, mode, and connection port before trusting a
scene. Multiple Blender windows may connect to different servers. Verify the
command endpoint as well as the status endpoint. Do not assume port 9876.

Before modifying an unsaved live scene, save a separate snapshot with
`bpy.ops.wm.save_as_mainfile(filepath=backup, copy=True)`. Prefer background
processing of the snapshot. Restore frame, selection/mode, pose and key values
after temporary live tests. Never replace the user's open file to view a result
without preserving the original state. Tell them which file/session was changed.

If live tools are unavailable, continue with a supplied saved source; explain
when unsaved state is required and request the missing connection or snapshot.

Record reproducible commands, model-specific settings, and QA findings in the
ignored work directory. Keep models, voice clips, renders and personal paths
out of tracked skills/docs. Canonical fitting is legacy/advanced code. For an assembled-body request, use
`export-unity.ps1` with inspected armature and head-bone names. For Unity setup,
use `install-unity.ps1` and the generic CharacterPipelineSetup entrypoint; preserve
existing project scripts and their metadata when updating. Never reuse old
Helen-specific editor menus blindly. Stop at the manual body attachment handoff
when the user has only supplied a head. Resume when they provide the assembled
file; record actual stage status in ignored `work/<character>/handoff.md`.
Do not publish, push, or license user assets merely because a rig was requested.
