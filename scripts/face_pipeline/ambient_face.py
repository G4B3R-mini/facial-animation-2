"""Replace the baked dialogue performance with a looping AMBIENT face clip.

    blender helen.blend -b --python ambient_face.py -- PROFILE.json OUT.blend [frames]

Why: the baked clip mixed visemes, jaw, blinks, gaze and brows into one take
tied to one line of dialogue. Runtime lipsync (uLipSync) now owns the mouth, and
dialogue is generated per-conversation, so a clip tied to one recording is
useless. What remains genuinely dialogue-independent is blinking and idle gaze -
those loop forever and never contradict anything being said.

Deliberately excluded:
  visemes / jaw   uLipSync drives the mouth from live audio
  speech brows    they only make sense against a specific waveform; at runtime
                  SpeechGestureDriver's SpeechLevel drives them instead
"""
import bpy, sys, json, math

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tripo_face_rig import animate as A, util

argv = sys.argv[sys.argv.index("--") + 1:]
PROFILE, OUT = argv[0], argv[1]
FRAMES = int(argv[2]) if len(argv) > 2 else 300      # 10s at 30fps

best, ob = -1, None
for o in bpy.data.objects:
    if o.type != 'MESH' or not o.data.shape_keys:
        continue
    kb = o.data.shape_keys.key_blocks
    if len(kb) <= 5:
        continue
    bz = kb["Basis"].data
    n = sum(1 for k in kb if k.name != "Basis"
            for i in range(len(o.data.vertices))
            if (k.data[i].co - bz[i].co).length > 1e-6)
    if n > best:
        ob, best = o, n
arm = bpy.data.objects["face_rig"]
prof = json.load(open(PROFILE))
prof = prof.get("profile", prof)

sc = bpy.context.scene
sc.render.fps = 30
sc.render.fps_base = 1.0
sc.frame_start = 1
sc.frame_end = FRAMES

# Drop whatever the previous take left behind, on both the rig and the keys.
util.clear_action(arm)
if ob.data.shape_keys:
    util.clear_action(ob.data.shape_keys)
for o in bpy.data.objects:
    if o.type == 'MESH' and o.data.shape_keys:
        util.clear_action(o.data.shape_keys)

keyed = A.apply_performance(ob, arm, prof, sc.frame_start, sc.frame_end, fps=30)

# Park the jaw and every mouth key at rest so nothing competes with uLipSync.
kb = ob.data.shape_keys.key_blocks
MOUTH = ("jawOpen", "jawForward", "jawLeft", "jawRight", "mouthClose",
         "mouthWide", "mouthPucker", "mouthFunnel", "lipsPressed", "mouthFF",
         "upperLipRaise")
parked = []
for k in kb:
    if k.name.startswith("vrc.") or k.name in MOUTH:
        try:
            k.value = 0.0
            parked.append(k.name)
        except Exception:
            pass          # driven keys (mouthClose) refuse; the driver owns them
jb = arm.pose.bones.get("jaw")
if jb:
    jb.rotation_mode = 'XYZ'
    jb.rotation_euler = (0.0, 0.0, 0.0)

A._set_interpolation(arm)
if ob.data.shape_keys:
    A._set_interpolation(ob.data.shape_keys)
sc.frame_set(sc.frame_start)

bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("AMBIENT " + json.dumps({
    "mesh": ob.name, "frames": [sc.frame_start, sc.frame_end],
    "seconds": round(FRAMES / 30.0, 2), "keyed": keyed,
    "mouth_keys_parked": len(parked), "saved": OUT}))
