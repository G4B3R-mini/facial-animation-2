# Unity integration

## Install and use the setup window

Build the importable package with `python scripts/build_unity_package.py`, then
double-click `dist/TripoFaceRig-Unity.unitypackage` while your project is open and
click **Import**. The window opens after script compilation; reopen it from
**Tools > Tripo Face Rig > Character Pipeline**. The package includes only the
maintained runtime components and generic editor tools. Stable script GUIDs
preserve references in the reference project. If another project already has
copies installed with different GUIDs or paths, use `install-unity.ps1` to update
them in place instead of importing duplicate classes.

Assign a model prefab or scene instance, a test voice, and a Humanoid idle clip.
Expand an animation FBX in the Project window and drag its **AnimationClip**
subasset into the slot. Use **Add speaking animation** for each talking/gesture
clip. Animations must be imported as Humanoid, matching the model's rig type.
Supply Rhubarb JSON, or browse to Rhubarb's executable and let the wizard create
timings from the WAV. The download button opens the official releases page.

Click **Create and wire speaking character**, save the scene, then press Play.
The wizard creates a unique folder under `Assets/TripoFaceRigGenerated` containing
an Animator controller, upper-body mask, copied animation clips and performance
profile. It assigns the controller, wires all runtime components, and keeps the
previous controller asset intact. Rebuilding creates another version; it does
not overwrite another character's assets. The animation copies remove explicit
bone/blendshape curves and animation events to avoid competing facial drivers.

The body base layer loops the selected idle with foot IK. An Override layer
masks gestures to the torso/arms/fingers and excludes head/legs. Speech analysis
schedules gesture accents and controls their envelopes, using the same runtime
approach as the coordinated reference character. Default gesture segments use
up to the first three seconds of each clip; tune start/accent/hold/end in the
generated profile for your clips. **Existing performance** optionally copies an
authored profile, preserving its segment markers and sample-specific acting
notes. The bundled package does not contain the reference character's models,
voices or motion clips.

The idle explicitly retains the imported neutral Humanoid jaw value. Removing
all jaw curves can otherwise let Unity's default muscle pose open a closed jaw.
Mouth articulation remains owned by the facial blendshape player.

The maintained runtime scripts under `unity/` include the current coordinated
mouth, gaze and expression implementation from the reference project. Install
only the subset selected by `install-unity.ps1`. Older editor scripts in that
directory are historical, character-specific setup tools; copying the entire
folder can add duplicate editor classes or optional uLipSync dependencies.

## Import and preview

1. Import the exported FBX and texture files, then enable blendshape import.
   Configure Rig as Humanoid and verify its Avatar. Map the body's actual head,
   but select the working face eye bones for Left Eye/Right Eye when duplicate
   unused body eye bones exist. Inspect Jaw mapping for the same ambiguity.
2. Import the voice WAV and its matching Rhubarb JSON. For analysis use an audio
   import configuration with accessible PCM samples (Decompress On Load).
3. Instantiate the character in the requested scene. Preserve the body Animator
   controller; check scale, floor height, materials and texture color spaces.
4. Use the setup window described above. Agents can call
   `CharacterPipelineSetup.Build(model, voice, cues, idle, speakingClips)` to build
   the controller and full setup, or `Configure(root, clip, cues)` for just face/audio
   wiring while preserving an existing body controller.
   This marks the scene dirty; save it after reviewing changes.
5. Enter Play mode. SpeechGestureDriver starts the clip after scene settling;
   RhubarbVisemePlayer reads cues against that same AudioSource clock. Review
   mouth closures, tongue/teeth, gaze and blink with sound. Exit Play before saving.

## Ownership and body motion

| Channel | Owner |
| --- | --- |
| Speech articulation | RhubarbVisemePlayer |
| Head/eye gaze and blink | ConversationalGaze |
| Expressions and final smile mixing | ConversationExpressionDriver |
| Audio analysis, phrase timing and gesture triggers | SpeechGestureDriver |
| Torso/arm gesture weight | SubtleBodyDriver, when a suitable layer exists |

FaceMeshUtil selects actual deforming shapes; inert copied shapes on hair are
not valid targets. Include separate dental/tongue renderers when they deform.
Check missing channels, including `tongueUp`, on each model. Do not assume every
ARKit-named key has useful data. Blender drivers are not preserved as Unity
drivers; jaw-related exported shapes must move the relevant dental geometry.

The setup window creates a controller from user-supplied body clips. The
`Configure` API alone preserves an existing controller. SpeechPerformanceProfile
stores gesture segments and optional acting notes for the actual recording.
Avoid baked face
curves or jaw animation competing with runtime articulation. The setup disables
known older face writers but the agent must inspect custom Animator layers and
other project components too.

RuntimeLipSyncService is available for later generated WAV integration. A fixed
sample preview uses precomputed JSON and does not require Rhubarb in the player.
Shipping runtime recognition requires the complete platform-specific Rhubarb
distribution and its notices; it is not bundled or automatically downloaded.

## Validation boundary

A compiling script, valid Avatar, or configured scene is not artistic approval.
Capture a short Play-mode test at conversation distance and a face close-up;
check renderer targets, changing coefficients, real deformation and audio sync.
Report unsupported editor/platform versions and any missing live-tool access.
Keep project-specific scenes, clips, models, presets and absolute paths out of
this public source repository.

The package components compile against Unity 6000.3.10f1. The wizard also passed
an in-editor setup test on a temporary preview-scene character using the reference
project's Humanoid model, idle and gesture clips. The test verified controller
layers, masks, valid gesture segments and component references. Continuous
Play-mode audiovisual quality still requires review on the chosen model/clips.
