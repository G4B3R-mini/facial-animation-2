# Tripo Face Rig

Prepare a generated character head in Blender, build a procedural face rig,
and test it speaking a sample voice clip with Rhubarb Lip Sync.

The intended workflow is **prepared head -> speaking Blender preview -> user
attaches head to a rigged body -> agent connects skeletons -> FBX -> Unity scene**.
Drive it by prompting the repository Codex or Claude skill; the agent runs the
commands and checks prerequisites. Models, textures, voices and motions are yours.

Start with the [prompt-driven wizard](docs/agent-wizard.md), including example
prompts for each task and the manual body-attachment handoff. The
[Unity guide](docs/unity.md) covers the reusable components and generic scene setup.
The self-contained [Blacksmith prepared-head example](examples/README.md) shows
how separate upper teeth, lower teeth, and tongue objects should be arranged.

For the Unity setup window, build `dist/TripoFaceRig-Unity.unitypackage` with
`python scripts/build_unity_package.py`. Import it, assign your model, voice,
idle and speaking animation clips, then click **Create and wire speaking character**.
It creates and assigns the Animator controller, mask, speech profile and components.
Published GitHub releases build and attach the same package automatically.

This is an experimental artist-assisted pipeline. Mouth detection and facial
weights need visual review per character. Expression names or passing numeric
gates do not guarantee acceptable animation. The maintained path is the
procedural rig; legacy canonical fitting/extensions are not the recommended path.

## Requirements

- Blender: the current workflow was exercised with **5.1.1**. Other versions
  are not certified; use the saving version or newer for supplied blend files.
- [Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync): tested with
  1.14.0. Extract the complete distribution, including recognizer resources.
- PowerShell 5.1+ on Windows, or PowerShell 7 for other systems, for the wrappers.
  Direct Blender/Python commands are documented too; macOS/Linux are untested.
- Optional regular Python 3 + Pillow for QA contact sheets:
  `python -m pip install Pillow`. Core scripts run in Blender's Python.
- Optional Blender MCP connection for live inspection by an assistant.
  No MCP connection is required for command-line builds.

Put `blender` and `rhubarb` on PATH, set `BLENDER_PATH` / `RHUBARB_PATH`, or use
`-Blender` / `-Rhubarb` executable paths. You can store machine-specific defaults
in ignored `pipeline.local.json`; start from [pipeline.example.json](pipeline.example.json).

## Start with an assistant

Open this clone in Codex and invoke:

> $tripo-face-rig Rig the prepared head in work/character/source.blend and
> animate it with work/character/voice.wav. Check prerequisites and give me
> a speaking Blender file to review.

The Codex skill is at [.agents/skills/tripo-face-rig/SKILL.md](.agents/skills/tripo-face-rig/SKILL.md).
It is repository-scoped: keep the clone available rather than copying only its
SKILL.md into a global skill folder. See [Codex skill documentation](https://developers.openai.com/codex/skills/)
for discovery. The matching [Claude skill](.claude/skills/tripo-face-rig/SKILL.md)
uses the same workflow and scripts.

## Quick start

First create/import a model and place its head, eyes, brows, teeth and tongue
in Blender. Save a prepared `head` mesh plus named `upper_jaw`, `lower_jaw`,
and `tongue` objects under `work/character/source.blend`. Keep hair separate.
Read [preparation instructions](docs/workflow.md) for eye/brow integration and
front/side placement checks before building.

From this repository folder:

```powershell
# Build a review rig and matching JSON report.
.\rig.ps1 .\work\character\source.blend

# After accepting the rig visually, add sample speech and sound.
.\lipsync.ps1 .\work\character\voice.wav -Rig .\work\character\source_rig.blend
```

The first command produces `source_rig.blend` and `source_rig.json`. The second
produces `source_rig_voice_lipsync.blend` and Rhubarb timings beside the rig.
Open the animated blend and press Space. Keep the voice WAV available at its
referenced path. Rendering an encoded video is a separate Blender operation.

For repeated testing, set `rig` in `pipeline.local.json`, then run only:

```powershell
.\lipsync.ps1 .\work\character\voice.wav
```

`-Output` selects a different output path. Use `-Recognizer phonetic` for
non-English voice clips. The scripts stop on tool errors and protect input files
from being used as output. Re-running an output path replaces that generated run.

## Rig settings and limitations

`rig.ps1` keeps lip seams intact by default. `-MouthMode aperture -SealRest 0.5`
was useful for one visibly open head, but is not a universal preset. Inspect
mouth measurements, jaw limit, lip corners, and tooth placement. The direct
`autorig.py` entrypoint retains its legacy automatic seam behavior; pass
`--no-split-seam` when preserving a cavity that is already open.

The rig creates jaw/tongue/eye/brow bones where the measured parts support them,
procedural facial shape keys, a mouth cavity, and optional ARKit/VRChat drafts.
Separate brows/eyes/lashes require preparation or binding; static hair is not
hair physics. You supply the rigged body in the manual attachment stage; the
next agent task connects the skeletons and exports for Unity. A rig can save
while a verification gate fails: inspect the
report and rendered result rather than ignoring the nonzero exit.

## Documentation and code

- [Complete workflow](docs/workflow.md): creation, placement, build, review, audio.
- [Troubleshooting](docs/troubleshooting.md): mouth detection, weights, teeth, playback.
- [Diagnostic tools](docs/diagnostics.md): QA renders and optional targeted repairs.
- [Publishing](docs/publishing.md): ignored files, clean source export, history.
- [Third-party dependencies](THIRD_PARTY.md): external tools and asset separation.
- `autorig.py`, `tripo_face_rig/`: measured rigging, expressions, verification, animation.
- `scripts/face_pipeline/`: shared assistant/CLI helpers.
- `unity/`: maintained runtime components and generic setup; see the Unity guide.
- `blender_extension/`: legacy/advanced sources; extra setup and
  validation required. Packaged extensions and third-party model assets are excluded.

## Contributing

Keep reproductions in ignored `work/` or `scratchpad/`. Submit code, reproducible
commands and findings; do not commit private models/audio, generated runs or
machine configuration. Test changes on background copies, include visual evidence
when deformation changes, and distinguish numeric checks from artistic approval.
Use `python -m unittest discover -s tests` for portable helper/packaging checks.
The self-contained driver-preservation check runs in Blender:
`blender -b --factory-startup --python-exit-code 1 --python tests/blender_animation_smoke.py`.

## License

This repository and its included Blacksmith example are available under the
[MIT License](LICENSE). Third-party tools and assets retain their respective
licenses; see [THIRD_PARTY.md](THIRD_PARTY.md).

Prerequisite report: `./doctor.ps1`. Skeleton/export task: `./export-unity.ps1`.
Unity component installation: `./install-unity.ps1 <project-path>`.
