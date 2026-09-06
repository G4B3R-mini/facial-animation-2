"""Automatic facial animation and Rhubarb voice-sync.

The build stage owns geometry and rig construction; this module owns actions.
It deliberately keys eye/brow bones and eyelid/viseme shape keys in one pass so
speech import cannot erase blinks and idle motion (the old standalone script
cleared both actions each time it ran).
"""
import json
import math
import os

import bpy

from . import util


VISEMES = ["mouthWide", "mouthPucker", "mouthFunnel", "lipsPressed", "mouthFF"]
BLINKS = ["blink_L", "blink_R"]

# Preston Blair cue -> (jaw degrees, {shape key: value}, tongue raise 0..1)
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


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _offset_bone_world_up(bone, amount):
    """Move a pose bone `amount` along WORLD +Z, whatever its local axes are.

    Blender bones point along their LOCAL Y, so for a brow bone standing upright
    the local Z axis points out of the face. Keying location.z therefore pushed
    the brows forward off the forehead instead of lifting them. Convert world up
    into the bone's own space rather than assuming an axis.
    """
    from mathutils import Vector
    m = bone.bone.matrix_local.to_3x3()
    try:
        local_up = m.inverted() @ Vector((0.0, 0.0, 1.0))
    except ValueError:
        local_up = Vector((0.0, 1.0, 0.0))
    bone.location = local_up * amount
    return bone.location


def speech_settings(profile):
    """Derive per-head speech amplitudes from measured mouth proportions.

    The original male has A0/S ~= .0358 and is the 1.0 reference.  The female
    has A0/S ~= .0588 and was hand-validated at .60 jaw/viseme scale.  The
    inverse aperture ratio reproduces both without a per-character preset.
    Tongue travel grows with aperture because a deeper mouth needs a larger
    readable lift.
    """
    ratio = profile["mouth"]["aperture_centre"] / max(profile["scale"], 1e-8)
    reference = 0.0358
    amplitude = _clamp(reference / max(ratio, 1e-6), 0.45, 1.40)
    face_id = profile["roles"]["face"]
    face_info = profile.get("shells", {}).get(str(face_id), {})
    face_fraction = face_info.get("verts", 0) / max(profile.get("verts", 1), 1)
    # NOTE: build.derive_params() computes this same clamp. The two must agree,
    # or the rig is built for one jaw range and driven at another. face_fraction
    # is only a PROXY for "the mouth is a welded sheet"; where the mouth was
    # actually MEASURED as an aperture the measurement wins. A bearded quad head
    # measured mode="aperture" but had face_fraction 0.62, which pinned this to
    # 6 deg and, through the amplitude cap below, drove the whole performance at
    # a third strength.
    mode = profile["mouth"].get("mode")
    if mode == "aperture":
        max_jaw_deg = 18.0
    else:
        max_jaw_deg = 6.0 if face_fraction > 0.45 else 18.0
    if mode == "invaginated":
        amplitude = min(amplitude, 0.62)
        max_jaw_deg = min(max_jaw_deg, 11.0)
    amplitude = min(amplitude, max_jaw_deg / 18.0)
    tongue_raise = _clamp(14.0 * ratio / reference, 10.0, 24.0)
    tongue_max = _clamp(18.0 * math.sqrt(ratio / reference), 16.0, 26.0)
    return {"jaw_scale": amplitude, "viseme_scale": amplitude,
            "tongue_raise": tongue_raise, "tongue_jaw_comp": 1.40,
            "tongue_max_deg": tongue_max, "aperture_ratio": ratio,
            "max_jaw_deg": max_jaw_deg, "face_fraction": face_fraction}


def _set_interpolation(id_data):
    ad = getattr(id_data, "animation_data", None)
    if not ad or not ad.action:
        return
    for fc in util.iter_fcurves(ad.action):
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
            kp.handle_left_type = "AUTO_CLAMPED"
            kp.handle_right_type = "AUTO_CLAMPED"
        fc.update()


def _add_audio_strip(scene, path):
    if not path:
        return "none"
    if not os.path.exists(path):
        return "missing: %s" % path
    se = scene.sequence_editor or scene.sequence_editor_create()
    holder = getattr(se, "strips", None)
    if holder is None:
        holder = se.sequences
    for strip in list(holder):
        if strip.type == "SOUND":
            holder.remove(strip)
    try:
        holder.new_sound(name="dialogue", filepath=path, channel=1, frame_start=1)
        return "added"
    except Exception as exc:
        return "failed: %s" % exc


def apply_lipsync(obj, armature, profile, json_path, fps=30, blend=0.055,
                  hold_min=0.22, settings=None):
    with open(json_path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    cues = data["mouthCues"]
    duration = data["metadata"]["duration"]
    cfg = dict(speech_settings(profile))
    if settings:
        cfg.update(settings)

    keys = obj.data.shape_keys.key_blocks
    missing = [name for name in VISEMES if keys.get(name) is None]
    if missing:
        raise RuntimeError("missing viseme shape keys: %s" % ", ".join(missing))
    jaw = armature.pose.bones["jaw"]
    tongue = armature.pose.bones.get("tongue")
    jaw.rotation_mode = "XYZ"
    if tongue:
        tongue.rotation_mode = "XYZ"

    samples = []
    for cue in cues:
        pose = POSES.get(cue["value"], POSES["X"])
        start, end = cue["start"], cue["end"]
        samples.append((start + min(blend, max(0.0, (end - start) * 0.5)), pose))
        if (end - start) > hold_min:
            samples.append((end - 0.04, pose))

    for when, pose in samples:
        frame = 1.0 + when * fps
        degrees, shape_values, tongue_amount = pose
        jaw_degrees = min(degrees * cfg["jaw_scale"], cfg["max_jaw_deg"])
        jaw.rotation_euler = (math.radians(jaw_degrees), 0.0, 0.0)
        jaw.keyframe_insert("rotation_euler", index=0, frame=frame)
        if tongue:
            tongue_degrees = min(
                cfg["tongue_raise"] * tongue_amount
                + cfg["tongue_jaw_comp"] * jaw_degrees,
                cfg["tongue_max_deg"],
            )
            tongue.rotation_euler = (math.radians(tongue_degrees), 0.0, 0.0)
            tongue.keyframe_insert("rotation_euler", index=0, frame=frame)
        for name in VISEMES:
            key = keys[name]
            key.value = shape_values.get(name, 0.0) * cfg["viseme_scale"]
            key.keyframe_insert("value", frame=frame)

    return {"cues": len(cues), "keyed_samples": len(samples),
            "duration": duration, "settings": cfg}


def apply_performance(obj, armature, profile, frame_start, frame_end, fps=30):
    """Add deterministic blinks, gaze changes, and brow movement."""
    S = profile["scale"]
    keyed = {"eyes": 0, "brows": 0, "blinks": 0}

    eye_frames = [
        (frame_start, 0.0, 0.0),
        (frame_start + 0.18 * (frame_end - frame_start), -4.0, 6.0),
        (frame_start + 0.40 * (frame_end - frame_start), 3.0, -7.0),
        (frame_start + 0.68 * (frame_end - frame_start), -2.0, 4.0),
        (frame_end, 0.0, 0.0),
    ]
    for name in ("eye_L", "eye_R"):
        bone = armature.pose.bones.get(name)
        if bone is None:
            continue
        bone.rotation_mode = "XYZ"
        side = -1.0 if name.endswith("R") else 1.0
        for frame, pitch, yaw in eye_frames:
            bone.rotation_euler.x = math.radians(pitch)
            bone.rotation_euler.z = math.radians(yaw * side)
            bone.keyframe_insert("rotation_euler", index=0, frame=frame)
            bone.keyframe_insert("rotation_euler", index=2, frame=frame)
            keyed["eyes"] += 1

    brow_frames = [
        (frame_start, 0.0),
        (frame_start + 0.30 * (frame_end - frame_start), 0.012 * S),
        (frame_start + 0.52 * (frame_end - frame_start), -0.004 * S),
        (frame_start + 0.78 * (frame_end - frame_start), 0.008 * S),
        (frame_end, 0.0),
    ]
    for name in ("brow_L", "brow_R"):
        bone = armature.pose.bones.get(name)
        if bone is None:
            continue
        for frame, z in brow_frames:
            _offset_bone_world_up(bone, z)
            bone.keyframe_insert("location", frame=frame)
            keyed["brows"] += 1

    shape_keys = obj.data.shape_keys.key_blocks if obj.data.shape_keys else {}
    duration = max(1, frame_end - frame_start)
    centres = [frame_start + 0.22 * duration, frame_start + 0.61 * duration]
    if duration > 4.5 * fps:
        centres.append(frame_start + 0.86 * duration)
    half = max(1.0, 0.055 * fps)
    for name in BLINKS:
        key = shape_keys.get(name)
        if key is None:
            continue
        for centre in centres:
            for frame, value in ((centre - 2.0 * half, 0.0),
                                 (centre - half, 1.0),
                                 (centre + half, 1.0),
                                 (centre + 2.0 * half, 0.0)):
                key.value = value
                key.keyframe_insert("value", frame=frame)
                keyed["blinks"] += 1
    return keyed



# ---------------------------------------------------------------- speech brows

def _rms_envelope(wav_path, fps, n_frames):
    """Per-video-frame RMS of a WAV, normalised 0..1.

    Uses only the stdlib wave module: audioop was removed in Python 3.13 and
    numpy is not guaranteed inside Blender's interpreter.
    """
    import wave, array
    try:
        w = wave.open(wav_path, "rb")
    except Exception:
        return None
    try:
        nch, width, rate, nsamp = (w.getnchannels(), w.getsampwidth(),
                                   w.getframerate(), w.getnframes())
        if width != 2:
            return None
        raw = w.readframes(nsamp)
    finally:
        w.close()
    a = array.array("h")
    a.frombytes(raw[:len(raw) - (len(raw) % 2)])
    if nch > 1:
        a = array.array("h", a[::nch])
    per = max(1, int(rate / float(fps)))
    env = []
    for f in range(n_frames):
        lo = f * per
        hi = min(len(a), lo + per)
        if lo >= len(a):
            env.append(0.0)
            continue
        acc = 0
        for i in range(lo, hi):
            v = a[i]
            acc += v * v
        env.append((acc / max(1, hi - lo)) ** 0.5)
    if not env:
        return None
    # normalise against a high percentile so one loud transient does not flatten
    ref = sorted(env)[int(0.92 * (len(env) - 1))] or max(env) or 1.0
    env = [min(1.0, e / ref) for e in env]
    # smooth: brows are slow relative to phonemes
    k = max(1, int(0.09 * fps))
    out = []
    for i in range(len(env)):
        lo = max(0, i - k)
        hi = min(len(env), i + k + 1)
        out.append(sum(env[lo:hi]) / (hi - lo))
    return out


def apply_speech_brows(obj, armature, profile, wav_path, frame_start, frame_end,
                       fps=30, amount=0.014, key_every=3):
    """Drive the brows from the speech envelope instead of a fixed pattern.

    apply_performance() keys brows at three hardcoded fractions of the take,
    which reads as alive but never emphasises the right word. Loudness is a
    decent cheap proxy for stress, so raise the brows with the smoothed RMS
    envelope. Existing brow location curves are cleared first, otherwise the
    deterministic keys fight these.
    """
    S = profile["scale"]
    n = max(1, frame_end - frame_start + 1)
    env = _rms_envelope(wav_path, fps, n) if wav_path else None
    if not env:
        return {"brows": 0, "source": "unavailable"}

    bones = [armature.pose.bones.get(nm) for nm in ("brow_L", "brow_R")]
    bones = [b for b in bones if b is not None]
    if not bones:
        return {"brows": 0, "source": "no brow bones"}

    act = armature.animation_data.action if armature.animation_data else None
    if act is not None:
        for b in bones:
            path = 'pose.bones["%s"].location' % b.name
            for fc in list(util.iter_fcurves(act)):
                if fc.data_path == path:
                    util.remove_fcurve(act, fc)

    kb = obj.data.shape_keys.key_blocks if obj.data.shape_keys else {}
    inner = kb.get("browInnerUp") if hasattr(kb, "get") else None

    keyed = 0
    for i in range(0, n, key_every):
        f = frame_start + i
        e = env[i]
        # bias low so quiet passages sit at rest rather than a permanent lift
        lift = max(0.0, (e - 0.25) / 0.75) ** 1.3
        for b in bones:
            _offset_bone_world_up(b, lift * amount * S)
            b.keyframe_insert("location", frame=f)
            keyed += 1
        if inner is not None:
            inner.value = 0.55 * lift
            inner.keyframe_insert("value", frame=f)
    return {"brows": keyed, "source": os.path.basename(wav_path),
            "peak_env": round(max(env), 3)}


def animate(obj, armature, profile, lipsync_json=None, audio_path=None,
            fps=30, frame_end=None, settings=None, brow_amount=0.014):
    """Create one coherent facial performance action."""
    util.clear_action(armature)
    if obj.data.shape_keys:
        util.clear_action(obj.data.shape_keys)

    scene = bpy.context.scene
    scene.render.fps = fps
    scene.render.fps_base = 1.0
    scene.frame_start = 1
    speech = None
    if lipsync_json:
        speech = apply_lipsync(obj, armature, profile, lipsync_json, fps=fps,
                               settings=settings)
        natural_end = int(math.ceil(speech["duration"] * fps)) + 12
    else:
        natural_end = int(4.0 * fps)
    scene.frame_end = int(frame_end or natural_end)
    performance = apply_performance(obj, armature, profile, scene.frame_start,
                                    scene.frame_end, fps=fps)
    # Speech-driven brows replace the deterministic brow pass above where audio
    # is available; without audio the fixed pattern stands.
    brows = None
    if audio_path and audio_path.lower().endswith(".wav"):
        brows = apply_speech_brows(obj, armature, profile, audio_path,
                                   scene.frame_start, scene.frame_end, fps=fps,
                                   amount=brow_amount)
    audio = _add_audio_strip(scene, audio_path)
    _set_interpolation(armature)
    if obj.data.shape_keys:
        _set_interpolation(obj.data.shape_keys)
    scene.frame_set(scene.frame_start)
    return {"fps": fps, "frame_end": scene.frame_end, "speech": speech,
            "performance": performance, "speech_brows": brows, "audio": audio}
