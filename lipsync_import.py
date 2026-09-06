"""Import Rhubarb Lip Sync JSON onto the face_rig.

Keys two channels: the jaw/tongue pose bones (armature action) and the
viseme shape key values (a separate action on the shape key datablock).

Override any of the constants below by pre-defining them in globals()
before exec'ing this file.
"""
import bpy, json, math

g = globals()
JSON_PATH = g.get("JSON_PATH")
WAV_PATH  = g.get("WAV_PATH", "")
FPS       = g.get("FPS", 30)
ARM       = g.get("ARM", "face_rig")
MESH      = g.get("MESH", "head")
BLEND     = g.get("BLEND", 0.055)          # seconds to reach a new shape
HOLD_MIN  = g.get("HOLD_MIN", 0.22)        # cues longer than this get a hold key
TONGUE_RAISE = g.get("TONGUE_RAISE", 14.0) # degrees, for the L shape
# Per-head scaling. POSES below is tuned for the reference (male) head; a head
# with a longer condyle-to-chin radius or a deeper measured aperture needs less
# of both or it gapes. 1.0 leaves the reference head untouched.
JAW_SCALE    = g.get("JAW_SCALE", 1.0)
VISEME_SCALE = g.get("VISEME_SCALE", 1.0)
# Per-key strength, multiplied on top of VISEME_SCALE. The POSES table below
# deliberately over-drives several keys past 1.0 (pucker 1.50, FF 1.30,
# lipsPressed 1.30, funnel 1.25) because that read well on the reference head.
# On a character with heavy facial hair those values crush the moustache and
# drag the nose down - measured on the blacksmith, where pucker 1.50 crumpled
# the moustache into itself while 0.6 read cleanly. Tune per head, e.g.
#   VISEME_WEIGHTS = {"mouthPucker": 0.40, "mouthFunnel": 0.50}
VISEME_WEIGHTS = g.get("VISEME_WEIGHTS", {})
# The tongue bone is a child of the jaw, so opening the jaw drags the tongue
# down out of sight -- it was visible in only 8% of frames on the test clip.
# A real tongue is not rigidly attached to the mandible; it stays relatively
# higher as the jaw drops. This counter-rotates by a fraction of the jaw angle.
TONGUE_JAW_COMP = g.get("TONGUE_JAW_COMP", 1.40)
# Ceiling on total tongue rotation. Measured on the reference head: full
# cancellation of the jaw's drag needs ~2.2x the jaw angle, so a comp below
# ~1.0 barely registers -- the jaw still wins and the tongue reads as welded
# to the mandible.
TONGUE_MAX_DEG  = g.get("TONGUE_MAX_DEG", 18.0)

VISEMES = ["mouthWide", "mouthPucker", "mouthFunnel", "lipsPressed", "mouthFF"]

# Preston Blair cue -> (jaw degrees, {shape key: value}, tongue raise 0..1)
#
# The tongue column is NOT just for L. B covers T/D/N/S/K -- all tongue-tip
# consonants -- and is typically the most common cue in speech (26 of 91 in the
# test clip), so leaving it at 0 leaves the tongue frozen through most of a
# take. Only A (P/B/M, lips closed) has no tongue movement worth showing.
POSES = {
    "X": (0.0,  {},                                      0.00),
    "A": (0.0,  {"lipsPressed": 1.30},                   0.00),
    "B": (4.0,  {"mouthWide": 0.85},                     0.55),
    "C": (10.0, {"mouthWide": 0.50},                     0.25),
    "D": (18.0, {"mouthWide": 0.25},                     0.10),
    "E": (8.0,  {"mouthFunnel": 1.25},                   0.20),
    "F": (3.0,  {"mouthPucker": 1.50},                   0.15),
    "G": (2.0,  {"mouthFF": 1.30},                       0.30),
    "H": (9.0,  {"mouthWide": 0.30},                     1.00),
}


def clear_action(id_data):
    ad = id_data.animation_data
    if ad and ad.action:
        act = ad.action
        id_data.animation_data.action = None
        if act.users == 0:
            bpy.data.actions.remove(act)


def iter_fcurves(action):
    """Blender <4.4 exposes action.fcurves; 4.4+/5.x use layered actions."""
    fcs = getattr(action, "fcurves", None)
    if fcs is not None:
        return list(fcs)
    out = []
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for cb in getattr(strip, "channelbags", []):
                out.extend(list(cb.fcurves))
    return out


def set_interpolation(id_data):
    ad = id_data.animation_data
    if not ad or not ad.action:
        return
    for fc in iter_fcurves(ad.action):
        for kp in fc.keyframe_points:
            kp.interpolation = 'BEZIER'
            kp.handle_left_type = 'AUTO_CLAMPED'
            kp.handle_right_type = 'AUTO_CLAMPED'
        fc.update()


def add_audio_strip(scene, path, fps):
    se = scene.sequence_editor
    if se is None:
        se = scene.sequence_editor_create()
    holder = getattr(se, "strips", None)
    if holder is None:
        holder = se.sequences
    for s in list(holder):
        if s.type == 'SOUND':
            holder.remove(s)
    try:
        holder.new_sound(name="dialogue", filepath=path, channel=1, frame_start=1)
        return "added"
    except Exception as e:
        return "failed: %s" % e


def run():
    with open(JSON_PATH, "r") as f:
        data = json.load(f)
    cues = data["mouthCues"]
    duration = data["metadata"]["duration"]

    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.render.fps_base = 1.0
    scene.frame_start = 1
    scene.frame_end = int(math.ceil(duration * FPS)) + 12

    ao = bpy.data.objects[ARM]
    ob = bpy.data.objects[MESH]
    kb = ob.data.shape_keys.key_blocks

    clear_action(ao)
    clear_action(ob.data.shape_keys)

    jaw = ao.pose.bones["jaw"]
    jaw.rotation_mode = 'XYZ'
    tongue = ao.pose.bones.get("tongue")
    if tongue is not None:
        tongue.rotation_mode = 'XYZ'

    # build the list of (time, pose) samples
    samples = []
    for c in cues:
        pose = POSES.get(c["value"], POSES["X"])
        start = c["start"]
        end = c["end"]
        t_on = start + min(BLEND, max(0.0, (end - start) * 0.5))
        samples.append((t_on, pose))
        if (end - start) > HOLD_MIN:
            samples.append((end - 0.04, pose))

    n = 0
    for t, pose in samples:
        frame = 1.0 + t * FPS
        deg, keys, tng = pose

        jaw.rotation_euler = (math.radians(deg * JAW_SCALE), 0.0, 0.0)
        jaw.keyframe_insert("rotation_euler", index=0, frame=frame)

        if tongue is not None:
            # Clamped to the full-L raise: that is as high as a tongue goes,
            # and letting the jaw compensation stack on top of it drove the
            # reference head's tongue up through the occlusion plane
            # (z 0.3383 against a bite line at 0.3304).
            tdeg = min(TONGUE_RAISE * tng + TONGUE_JAW_COMP * deg * JAW_SCALE,
                       TONGUE_MAX_DEG)
            tongue.rotation_euler = (math.radians(tdeg), 0.0, 0.0)
            tongue.keyframe_insert("rotation_euler", index=0, frame=frame)

        for name in VISEMES:
            kb[name].value = (keys.get(name, 0.0) * VISEME_SCALE
                              * VISEME_WEIGHTS.get(name, 1.0))
            kb[name].keyframe_insert("value", frame=frame)
        n += 1

    set_interpolation(ao)
    set_interpolation(ob.data.shape_keys)
    audio = add_audio_strip(scene, WAV_PATH, FPS)

    return {"cues": len(cues), "keyed_samples": n, "duration": duration,
            "fps": FPS, "frame_end": scene.frame_end, "audio": audio}


if not JSON_PATH:
    raise RuntimeError('Set JSON_PATH for this legacy importer, or use lipsync.ps1 / scripts/face_pipeline/reanimate.py')
RESULT = run()
