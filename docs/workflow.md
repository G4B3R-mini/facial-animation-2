# From a model to a speaking Blender character

This workflow builds on your own model and manually placed facial parts.
It does not create a 3D model, buy generation credits, or supply licensed heads,
teeth, textures, voices, or motion clips. Use a model-generation tool or ordinary
modeling workflow of your choice. The rigging and Rhubarb steps run locally.

## 1. Create and prepare the source

Keep downloads and working files in `work/<character>/` (ignored by Git).
Create a character with a readable face and enough geometry around lips and
eyelids to deform. A visible mouth opening helps inspection. Preserve a quad
export if your generator supplies one; a GLB preview may be triangulated.
Triangulation alone is not proof that a model cannot work.

Import into Blender and preserve the original download. Orient the character
with **Z up and the face toward -Y**. `--align` shifts the midline to x=0;
it does not rotate a Y-up model or normalize its size. Inspect applied transforms.

| Part | Suggested name | Preparation / behavior |
| --- | --- | --- |
| Facial skin, head and neck | `head` | Explicit rigging target; retain the neutral appearance |
| Hair / clothing | `hair` and distinct names | Keep separate; not automatically face-skinned |
| Upper teeth/gums | `upper_jaw` | Fit inside upper lip; remains rigid on head |
| Lower teeth/gums | `lower_jaw` | Fit below upper teeth; remains rigid on jaw |
| Tongue | `tongue` | Place inside lower dental arch; follows tongue bone |
| Eyes | `eye_L`, `eye_R` during preparation | Include as disconnected shells in head for automatic eye detection |
| Brows / lashes | Descriptive names | Prepare explicitly; separate objects are not automatically animated |

Position teeth and tongue in **front and side views**. Check depth as well as
width: arches that look right from the front can stick through the lips in profile.
Do not bone-parent dental parts to a temporary skeleton.

For automatic eye/brow detection, select those prepared meshes, then select
`head` last and use **Object > Join** (`Ctrl+J`) on a working copy. This makes
one object with disconnected shells; do not merge/weld eyeballs to skin. Keep
hair and clothing separate. Classification is still heuristic: inspect the report
and resulting eye/brow bones. Small lash shells may need the optional lash helper.
If you need separate objects throughout, bind/transfer them deliberately; the
basic CLI does not do that integration for you.

Save as `work/<character>/source.blend`, with textures packed or available at
resolvable paths. Audit that saved copy:

```powershell
blender -b work/character/source.blend --python-exit-code 1 `
  --python scripts/face_pipeline/audit_scene.py -- work/character/audit.json --obj head
```

Use your Blender executable path if `blender` is not on PATH. The helper reports
inventory, shading, fragmentation, and possible mouth/orientation hazards. Its
boundary and bounding-box estimates are prompts to inspect, not anatomical truth.
Correct real placement problems; do not regenerate a model solely from a warning.

## 2. Build a review rig

From the clone root:

```powershell
.\rig.ps1 .\work\character\source.blend
```

This writes `source_rig.blend` and `source_rig.json` beside the source. It uses
`head`, `upper_jaw,lower_jaw`, and `tongue` by default, keeps the seam intact,
and asks for ARKit/VRChat draft expressions. Use `-Object`, `-Teeth`, `-Tongue`
for different names; `-NoTongue` omits a generated/bound tongue; `-Basic` omits
the expanded expression set. `-Align` and `-WeldCoincident` are opt-in.

If a visibly open mouth is misclassified as invaginated, this is a useful
**candidate to compare**, not a universal preset:

```powershell
.\rig.ps1 .\work\character\source.blend -MouthMode aperture -SealRest 0.5
```

`-SeamMode Keep` is the wrapper default. `Split` explicitly enables a cut;
`Auto` follows the legacy CLI heuristic. Only split when inspection supports
it. A real cavity can have no boundary loop and still be open. Adjust resting
lip seal in the range 0..1 per model. Keep the best accepted candidate separately.

Portable direct Blender equivalent (works without PowerShell):

```sh
blender -b work/character/source.blend --python-exit-code 1 \
  --python autorig.py -- --obj head --teeth upper_jaw,lower_jaw \
  --tongue-object tongue --no-split-seam --arkit \
  --out work/character/source_rig.blend --json work/character/source_rig.json
```

Exit 0 means all numeric gates passed. Exit 1 may still produce a review file
and JSON report; inspect `verify.failed` rather than treating it as success.
No rig is guaranteed to have 52 useful expressions; missing anatomy/roles are
reported as empty channels. The supplied heads and prior local tests are not
part of the public repository.

## 3. Inspect before voice testing

Compare source neutral, rig neutral, jaw at 9/18 degrees, blink, and a few
visemes at conversation distance. Check the jaw **constraint limit**: some
automatic measurements cap it below the requested rotation. `--open-deg` is
the verification angle, not a jaw-limit setting.

```powershell
blender -b work/character/source_rig.blend --python-exit-code 1 `
  --python scripts/face_pipeline/diagnose_rig.py -- work/character/diagnosis.json --obj head
blender -b work/character/source_rig.blend --python-exit-code 1 `
  --python scripts/face_pipeline/qa_render.py -- work/character/qa --obj head --closeup
python scripts/face_pipeline/make_sheet.py work/character/qa --kind bust
```

The sheet helper uses Pillow in your ordinary Python environment. Blender's
embedded Python runs the other two scripts. See [diagnostics](diagnostics.md).
Inspect the rendered result, not only scores. The QA metadata records the head,
generated poses, and jaw limit. Run these tools in background copies; camera,
material display colors and temporary poses are QA state.

If the user supplied an existing rig as a reference, compare its actual saved
or snapshotted state. Do not substitute a lower jaw range to conceal deformation.

## 4. Supply sample voice and animate

Use a WAV clip of the voice you want to test. Supply the **approved rig**, not
the raw source, to preserve your accepted geometry, weights, and correctives:

```powershell
.\lipsync.ps1 .\work\character\voice.wav -Rig .\work\character\source_rig.blend
```

This runs Rhubarb and writes `source_rig_voice_lipsync.blend` plus
`source_rig_voice_lipsync.rhubarb.json` beside the rig. It reuses the profile
embedded by `autorig.py`; for older files, pass the matching `-Profile rig.json`.
Use `-Output path.blend` for a different destination and `-Fps 30` for FPS.
For non-English speech, use `-Recognizer phonetic`. Rhubarb's default
PocketSphinx recognizer is intended for English.

For repeated use, copy `pipeline.example.json` to ignored `pipeline.local.json`
and set your approved `rig` and executable paths. Then only the audio is needed:

```powershell
.\lipsync.ps1 .\work\character\voice.wav
```

Command-line arguments override local configuration. Executables can also come
from `BLENDER_PATH` / `RHUBARB_PATH` or PATH. Paths in local config are relative
to the clone root; explicit command-line paths are relative to your current
directory. Changing `-Rig` does not reuse a different rig's configured profile.

On other shells, run the same stages directly:

```sh
rhubarb -f json -o work/character/voice.rhubarb.json work/character/voice.wav
blender -b work/character/source_rig.blend --python-exit-code 1 \
  --python scripts/face_pipeline/reanimate.py -- work/character/talking.blend \
  --cues work/character/voice.rhubarb.json --audio work/character/voice.wav --fps 30
```

## 5. Review the animated file

Open the output `.blend`, start at frame 1, and play. It includes the sound
strip and generated jaw/tongue/viseme actions, plus blinks/gaze/brows where those
bones and shapes exist. This creates a Blender scene, not an encoded video.

Check lip closures (M/B/P), open vowels, F/V, rounded vowels and pauses. Confirm
the sound strip is present, Blender audio is enabled and FPS is correct. Playback
lag is not necessarily a cue error; use audio-sync playback or render a short
video to separate viewport performance from timing. Keep the WAV accessible;
it is referenced by path, not guaranteed to be packed into the blend.

If speech needs tuning, the direct animation helper accepts `--jaw-scale` and
`--viseme-scale`. It replaces animation actions, not geometry. Do not run
`autorig.py` on an already-approved rig merely to change the voice clip.

Record the accepted source, options, report, rig, audio, timings and findings
under the ignored character work directory. See [publishing](publishing.md)
before sharing the repository; code and user assets have separate ownership.

## 6. Continue to a body and Unity

After preview approval, manually attach the head to your rigged body. Give the
assembled file to the agent for skeleton merging and FBX export, then request
Unity scene setup. Follow the [agent wizard](agent-wizard.md) and
[Unity integration](unity.md) for the next tasks.
