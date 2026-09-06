# Prompt-driven character pipeline

Use the same `$tripo-face-rig` skill for each task. The agent identifies the
current stage from your files and request; you do not need to memorize commands.
It records inputs, settings, outputs and review status in ignored
`work/<character>/handoff.md` so another session can resume.

## Task 1: prepared head to speaking preview

> Rig the prepared head in `work/character/source.blend` and animate it with
> `work/character/voice.wav`. Check prerequisites, diagnose deformation, and
> give me a speaking Blender file to review.

The agent runs `doctor.ps1 -Stage Head`, which reports missing Blender/Rhubarb
executables together with download URLs and configuration instructions. Blender
is available at [the official download page](https://www.blender.org/download/).
Extract the entire [Rhubarb release archive](https://github.com/DanielSWolf/rhubarb-lip-sync/releases),
including recognizer resources. Set the executable paths in local configuration
or use `-Blender` / `-Rhubarb`. No global Python installation is required for
rigging; Blender supplies Python. Optional contact sheets need Pillow.

The agent audits your parts, builds the rig, checks jaw/blink/dental deformation,
and generates Rhubarb cues and a separate animated `.blend`. A single request
authorizes the rig and audio stages; there is no mandatory approval question
between every command. A failed deformation gate must be diagnosed and recorded,
not suppressed just to complete the wizard. The agent may produce a clearly
labeled review preview with known limitations once it has inspected them.

Open the preview, start at frame 1 and play with sound. Check lips, teeth,
tongue, blinking and pauses from front and side. With live Blender tools the
agent can start/scrub playback and capture representative poses; it must not
claim to have heard audio or seen continuous playback from a numeric check.
Your visual approval is the handoff, not an automated gate count.

## Manual task: attach the approved head to a body

Attach the approved head to your chosen rigged body in Blender and save a new
`assembled.blend`. Preserve facial shape keys, weights, and facial armature.
Position the head, hair and dental parts together. Keep the original body rig
and name its head bone. Remove/hide the original head intentionally; an unapplied
Boolean cut is supported when explicitly identified. Keep cutter objects out of
the character export. Do not join the face mesh into a body mesh if that destroys
the face's shape keys. Return the assembled file to the agent when ready.

## Task 2: assembled character to Unity FBX

> I attached the approved head to the body in `work/character/assembled.blend`.
> Inspect it, connect the skeletons, and export a Unity-ready FBX.

The agent inventories armatures, bone names, skinning and attachment constraints.
It supplies actual names to `export-unity.ps1`; they are not universal presets:

```powershell
.\export-unity.ps1 .\work\character\assembled.blend -BodyArmature Armature -FaceArmature face_rig -HeadBone Head
```

An intentional body head-cut Boolean can be finalized with
`-ApplyBodyBooleans <body-mesh-name>`. The helper refuses to discard live body
shape keys. It merges armatures, parents facial roots under the body head,
retargets skinning and corrective drivers, and verifies evaluated facial vertex
positions and shape-key counts. Name collisions and unsupported bind transforms
produce actionable errors. Bind rigid accessories with full weights to the
appropriate bone before export; object parenting alone is not sufficient.
Inspect the report's mesh list for missing parts.

Outputs are a new `.blend`, `.fbx`, `.export.json` and texture files. The FBX is
a neutral runtime character, with no baked voice action competing with Unity
mouth drivers. The original speaking preview remains available separately.
Blender constraints/drivers are not runtime Unity components: verify exported
blendshape deltas, jaw/dental response and eye mapping after import. Do not treat
a successful FBX write as proof of working deformation.

## Task 3: import and wire a scene character

> Import the exported character into my Unity project at `<project path>` and
> wire it into `<scene>` with this voice WAV and Rhubarb JSON. Use its body
> Animator and the repo's face, gaze and expression components.

Read [Unity integration](unity.md). Run `doctor.ps1 -Stage Unity -UnityProject
<path>`. Install the maintained scripts with `install-unity.ps1 <path>`; review
existing differing scripts before using `-UpdateExisting`. Import the FBX,
textures, WAV and matching JSON under a character-specific Assets folder.
Use a valid Humanoid Avatar, preserve/assign the body controller, instantiate
the model in the requested scene, and use the generic Character Pipeline window
or its public `Configure(root, clip, cues)` entrypoint through Unity MCP.

The agent checks compilation, Avatar, deforming renderers, component references,
materials, scale, and channel ownership. It then runs a Play-mode audio/visual
test if live tools are connected, saves the requested scene/prefab, and reports
what was actually tested. If Unity MCP is absent, it can prepare the files and
give the exact editor actions; scene wiring/playback remains pending until done.
The workflow does not automatically add TTS, dialogue services or paid motions.

Record stage status explicitly: `preview ready`, `user accepted`, `awaiting manual
body attachment`, `FBX exported`, `Unity configured`, `Play-mode reviewed`.
Do not mark later stages complete merely because earlier artifacts exist.
