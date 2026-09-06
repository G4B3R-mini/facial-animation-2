"""Measured ARKit 52 and VRChat viseme generation.

This module deliberately builds on the landmarks already proven by the rig
pipeline.  It does not guess facial locations from whole-object percentages and
does not change topology.  The generated keys are conservative drafts intended
to survive a wide range of Tripo heads and remain manually sculptable.
"""
import math

import bpy
from mathutils import Vector

from . import util
from .build import (DEFAULTS, derive_params, jaw_weight, seam_y, seam_z,
                    vertex_sides)
from .mouth_fields import MouthField


ARKIT_52 = [
    "eyeBlinkLeft", "eyeBlinkRight",
    "eyeLookDownLeft", "eyeLookDownRight",
    "eyeLookInLeft", "eyeLookInRight",
    "eyeLookOutLeft", "eyeLookOutRight",
    "eyeLookUpLeft", "eyeLookUpRight",
    "eyeSquintLeft", "eyeSquintRight", "eyeWideLeft", "eyeWideRight",
    "jawForward", "jawLeft", "jawRight", "jawOpen",
    "mouthClose", "mouthFunnel", "mouthPucker", "mouthLeft", "mouthRight",
    "mouthSmileLeft", "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthDimpleLeft", "mouthDimpleRight", "mouthStretchLeft", "mouthStretchRight",
    "mouthRollLower", "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper",
    "mouthPressLeft", "mouthPressRight",
    "mouthLowerDownLeft", "mouthLowerDownRight",
    "mouthUpperUpLeft", "mouthUpperUpRight",
    "noseSneerLeft", "noseSneerRight",
    "cheekPuff", "cheekSquintLeft", "cheekSquintRight",
    "browDownLeft", "browDownRight", "browInnerUp",
    "browOuterUpLeft", "browOuterUpRight", "tongueOut",
]

VRC_15 = [
    "vrc.v_sil", "vrc.v_PP", "vrc.v_FF", "vrc.v_TH", "vrc.v_DD",
    "vrc.v_kk", "vrc.v_CH", "vrc.v_SS", "vrc.v_nn", "vrc.v_RR",
    "vrc.v_aa", "vrc.v_E", "vrc.v_I", "vrc.v_O", "vrc.v_U",
]
CALIBRATION_KEYS = {
    "jawOpen", "mouthClose", "mouthFunnel", "mouthPucker",
    "mouthSmileLeft", "mouthSmileRight",
}
_PRESERVE_EXISTING = set()


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def _smooth(v):
    v = _clamp(v)
    return v * v * (3.0 - 2.0 * v)


def _basis(obj):
    if not obj.data.shape_keys:
        obj.shape_key_add(name="Basis", from_mix=False)
    return obj.data.shape_keys.key_blocks["Basis"]


def _replace_key(obj, name):
    basis = _basis(obj)
    old = obj.data.shape_keys.key_blocks.get(name)
    if old is not None and name not in {"mouthClose", "mouthFunnel", "mouthPucker"}:
        obj.shape_key_remove(old)
    key = obj.data.shape_keys.key_blocks.get(name)
    if key is None:
        key = obj.shape_key_add(name=name, from_mix=False)
    key.value = 0.0
    key.slider_min = 0.0
    key.slider_max = 1.0
    return basis, key


def _stats(basis, key):
    moved = 0
    total = 0.0
    maximum = 0.0
    for i in range(len(basis.data)):
        d = (key.data[i].co - basis.data[i].co).length
        if d > 1e-6:
            moved += 1
            total += d
            maximum = max(maximum, d)
    return {"moved": moved, "mean": total / moved if moved else 0.0,
            "max": maximum}


def _make(obj, name, delta_fn, indices=None):
    existing = obj.data.shape_keys.key_blocks.get(name) if obj.data.shape_keys else None
    if name in _PRESERVE_EXISTING and existing is not None:
        existing.value = 0.0
        return _stats(_basis(obj), existing)
    basis, key = _replace_key(obj, name)
    allowed = set(indices) if indices is not None else None
    for i in range(len(basis.data)):
        if allowed is not None and i not in allowed:
            continue
        delta = delta_fn(i, basis.data[i].co)
        if delta is not None:
            key.data[i].co = basis.data[i].co + Vector(delta)
    return _stats(basis, key)


def _copy(obj, source, target):
    existing = obj.data.shape_keys.key_blocks.get(target) if obj.data.shape_keys else None
    if target in _PRESERVE_EXISTING and existing is not None:
        existing.value = 0.0
        return _stats(_basis(obj), existing)
    basis, key = _replace_key(obj, target)
    src = obj.data.shape_keys.key_blocks.get(source)
    if src is not None:
        for i in range(len(basis.data)):
            key.data[i].co = src.data[i].co.copy()
    return _stats(basis, key)


def _combine(obj, name, sources):
    existing = obj.data.shape_keys.key_blocks.get(name) if obj.data.shape_keys else None
    if name in _PRESERVE_EXISTING and existing is not None:
        existing.value = 0.0
        return _stats(_basis(obj), existing)
    basis, key = _replace_key(obj, name)
    blocks = obj.data.shape_keys.key_blocks
    for i in range(len(basis.data)):
        delta = Vector((0.0, 0.0, 0.0))
        for source, weight in sources:
            block = blocks.get(source)
            if block is not None:
                delta += (block.data[i].co - basis.data[i].co) * weight
        key.data[i].co = basis.data[i].co + delta
    return _stats(basis, key)


def _component_indices(comp_of, components):
    wanted = set(components)
    return [i for i, comp in comp_of.items() if comp in wanted]


def _group_weights(obj, name):
    group = obj.vertex_groups.get(name)
    if group is None:
        return {}
    weights = {}
    for vertex in obj.data.vertices:
        try:
            weight = group.weight(vertex.index)
        except RuntimeError:
            continue
        if weight > 0.0:
            weights[vertex.index] = weight
    return weights


def _eye_specs(obj, profile, comp_of):
    specs = {}
    for comp in profile["roles"].get("eyes") or []:
        indices = _component_indices(comp_of, [comp])
        if not indices:
            continue
        coords = [obj.data.vertices[i].co for i in indices]
        xs, ys, zs = ([c.x for c in coords], [c.y for c in coords],
                      [c.z for c in coords])
        cx = 0.5 * (min(xs) + max(xs))
        side = "Right" if cx < 0.0 else "Left"
        specs[side] = {
            "component": comp, "indices": indices,
            "center": Vector((cx, 0.5 * (min(ys) + max(ys)),
                              0.5 * (min(zs) + max(zs)))),
            "rx": max(0.5 * (max(xs) - min(xs)), 0.018 * profile["scale"]),
            "rz": max(0.5 * (max(zs) - min(zs)), 0.014 * profile["scale"]),
            "front_y": min(ys),
        }
    if len(specs) == 1:
        source_side = next(iter(specs))
        missing = "Left" if source_side == "Right" else "Right"
        src = specs[source_side]
        mirrored = dict(src)
        mirrored["center"] = Vector((-src["center"].x, src["center"].y,
                                     src["center"].z))
        mirrored["indices"] = []
        mirrored["component"] = None
        mirrored["inferred"] = True
        specs[missing] = mirrored
    return specs


def _rotate(points, center, axis, angle):
    # Rodrigues is unnecessary for the two axes used here.
    x, y, z = (points - center)
    c, s = math.cos(angle), math.sin(angle)
    if axis == "X":
        out = Vector((x, y * c - z * s, y * s + z * c))
    else:
        out = Vector((x * c - y * s, x * s + y * c, z))
    return center + out


def _infer_face_landmarks(profile, eye_specs):
    S = profile["scale"]
    m = profile["mouth"]
    mouth_z = seam_z({"seam_z": m["seam_z"], "corner_x": m["corner_x"],
                      "jaw_slope": 0.0}, 0.0)
    eye_z = (sum(spec["center"].z for spec in eye_specs.values()) /
             max(1, len(eye_specs)))
    if not eye_specs:
        fbb = profile["shells"][str(profile["roles"]["face"])]["bbox"]
        eye_z = fbb["z"][0] + 0.68 * (fbb["z"][1] - fbb["z"][0])
    nose_z = mouth_z + 0.48 * (eye_z - mouth_z)
    cheek_z = mouth_z + 0.42 * (eye_z - mouth_z)
    return {"mouth_z": mouth_z, "eye_z": eye_z, "nose_z": nose_z,
            "cheek_z": cheek_z, "S": S}


def generate(obj, armature, profile, tongue_obj=None, include_vrc=True,
             preserve_existing=None):
    """Generate ARKit 52 drafts and optional VRC 15 visemes.

    The report distinguishes present/non-empty/partial expressions.  A missing
    separate eyeball produces valid eyelid expressions but partial gaze keys.
    """
    global _PRESERVE_EXISTING
    _PRESERVE_EXISTING = set(preserve_existing or ())
    P = derive_params(profile, DEFAULTS)
    me = obj.data
    comp_of, _ = util.islands(me)
    face = profile["roles"]["face"]
    face_indices = _component_indices(comp_of, [face])
    lower_teeth = set(profile["roles"].get("teeth_lower_all") or
                      [profile["roles"].get("teeth_lower")])
    lower_teeth.discard(None)
    eye_specs = _eye_specs(obj, profile, comp_of)
    landmarks = _infer_face_landmarks(profile, eye_specs)
    S, A0, XC = P["S"], P["A0"], P["corner_x"]
    front_cut = P["front_cut"]
    guide_settings = P.get("guide_settings") or {}
    guided_mouth = bool(P.get("guide_rails"))
    results = {}
    partial = []
    semantic = {
        "upper": _group_weights(obj, "FRG_upper_lip"),
        "lower": _group_weights(obj, "FRG_lower_lip"),
        "corners": _group_weights(obj, "FRG_corners"),
        "jaw": _group_weights(obj, "FRG_jaw"),
    }
    semantic["enabled"] = bool(semantic["upper"] or semantic["lower"])
    mouth_field = MouthField(P, vertex_sides(obj, P), semantic=semantic)

    def side_weight(x, side):
        signed = x / max(XC, 1e-8)
        if side == "Right":
            signed = -signed
        return _smooth(0.5 + 0.75 * signed)

    def lip_mask(index, co, side=None, upper=None, corner=False):
        field = mouth_field.evaluate(index, co)
        if not field:
            return 0.0
        if upper is not None and (field["side"] > 0) != upper:
            return 0.0
        w = field["body"]
        if side:
            w *= field["left" if side == "Left" else "right"]
        if corner:
            w = field["corner"] * (
                field["left" if side == "Left" else "right"] if side else 1.0)
        return w

    # Existing production keys are the best source for these ARKit names.
    for source, target in (("blink_L", "eyeBlinkLeft"),
                           ("blink_R", "eyeBlinkRight")):
        results[target] = _copy(obj, source, target)

    # Eye gaze rotates actual eyeball shells. Inferred sides remain partial.
    for side in ("Left", "Right"):
        spec = eye_specs.get(side)
        if not spec:
            for direction in ("Down", "In", "Out", "Up"):
                results[f"eyeLook{direction}{side}"] = _make(
                    obj, f"eyeLook{direction}{side}", lambda i, co: None, [])
                partial.append(f"eyeLook{direction}{side}: no eye landmark")
            continue
        if not spec["indices"]:
            partial.extend(f"eyeLook{direction}{side}: fused eyeball"
                           for direction in ("Down", "In", "Out", "Up"))
        for direction, axis, degrees in (
                ("Down", "X", 6.0), ("Up", "X", -5.0),
                ("In", "Z", -7.0 if side == "Left" else 7.0),
                ("Out", "Z", 7.0 if side == "Left" else -7.0)):
            name = f"eyeLook{direction}{side}"
            center = spec["center"]
            results[name] = _make(
                obj, name,
                lambda i, co, c=center, a=axis, d=degrees:
                    _rotate(co, c, a, math.radians(d)) - co,
                spec["indices"])

        def lid_delta(kind):
            def delta(i, co):
                dx = (co.x - spec["center"].x) / (1.72 * spec["rx"])
                dz = (co.z - spec["center"].z) / (1.72 * spec["rz"])
                if dx * dx + dz * dz >= 1.0 or co.y > spec["center"].y + 0.4 * spec["rz"]:
                    return None
                radial = _smooth(1.0 - dx * dx - dz * dz)
                upper = co.z >= spec["center"].z
                if kind == "wide":
                    move = (0.30 if upper else -0.10) * spec["rz"] * radial
                    return (0.0, 0.0, move)
                move = (-0.08 if upper else 0.24) * spec["rz"] * radial
                return (0.0, -0.025 * spec["rz"] * radial, move)
            return delta
        results[f"eyeSquint{side}"] = _make(obj, f"eyeSquint{side}",
                                             lid_delta("squint"), face_indices)
        results[f"eyeWide{side}"] = _make(obj, f"eyeWide{side}",
                                           lid_delta("wide"), face_indices)

    # Jaw shapes use the exact production jaw field and hinge.
    pivot = Vector(P["pivot"])
    lower_indices = _component_indices(comp_of, lower_teeth)
    jaw_indices = set(face_indices) | set(lower_indices)

    def jaw_influence(i, co):
        if comp_of.get(i) in lower_teeth:
            return 1.0
        influence = (semantic["jaw"].get(i, 0.0)
                     if semantic["jaw"] else jaw_weight(P, co.x, co.y, co.z))
        field = mouth_field.evaluate(i, co)
        if field:
            # The upper rail belongs to the static maxilla. The lower rail
            # follows the jaw, but not as rigidly as teeth/chin; this prevents
            # a coarse lower lip from stretching into a broad hanging flap.
            damping = 0.92 if field["side"] > 0 else 0.24
            influence *= 1.0 - damping * field["body"]
        return influence

    open_deg = min(P["jaw_max_deg"],
                   float(guide_settings.get("jaw_open_deg", 12.0)))
    results["jawOpen"] = _make(
        obj, "jawOpen",
        lambda i, co: (_rotate(co, pivot, "X", math.radians(open_deg)) - co)
        * jaw_influence(i, co), jaw_indices)
    results["jawForward"] = _make(
        obj, "jawForward", lambda i, co: Vector((0.0, -0.025 * S, 0.0))
        * jaw_influence(i, co), jaw_indices)
    results["jawLeft"] = _make(
        obj, "jawLeft", lambda i, co: Vector((0.022 * S, 0.0, 0.0))
        * jaw_influence(i, co), jaw_indices)
    results["jawRight"] = _make(
        obj, "jawRight", lambda i, co: Vector((-0.022 * S, 0.0, 0.0))
        * jaw_influence(i, co), jaw_indices)

    # Hard mouth shapes use fitted rails rather than an elliptical topology
    # mask.  The wet line receives the performance motion while the lip body
    # supplies a broad, identity-preserving falloff into the surrounding skin.
    def close_delta(i, co):
        field = mouth_field.evaluate(i, co)
        if not field:
            return None
        w = max(field["wet"], 0.42 * field["body"])
        target = field["seam_z"] + field["side"] * 0.018 * A0
        tuck = 0.055 * A0 if field["side"] < 0 else 0.012 * A0
        return (0.0, tuck * w, (target - co.z) * 0.68 * w)

    def round_delta(kind):
        def delta(i, co):
            field = mouth_field.evaluate(i, co)
            if not field:
                return None
            w = max(field["wet"], 0.58 * field["body"])
            corner = field["corner"]
            if kind == "pucker":
                x_scale, forward, spread = 0.34, -0.37, -0.09
                strength = float(guide_settings.get("pucker_strength", 1.0))
            else:
                x_scale, forward, spread = 0.40, -0.30, 0.09
                strength = float(guide_settings.get("funnel_strength", 1.0))
            dx = -co.x * x_scale * (0.45 * w + 0.55 * corner)
            dy = forward * A0 * w
            dz = (spread * field["side"] * A0
                  - 0.10 * (co.z - field["seam_z"])) * w
            return (dx * strength, dy * strength, dz * strength)
        return delta

    if guided_mouth:
        # Explicitly replace the production defaults only when the artist has
        # supplied rails. Unguided reference heads retain their validated seal
        # and viseme shapes for backward compatibility.
        for name in ("mouthClose", "mouthFunnel", "mouthPucker"):
            old = me.shape_keys.key_blocks.get(name)
            if old is not None and name not in _PRESERVE_EXISTING:
                obj.shape_key_remove(old)
        results["mouthClose"] = _make(
            obj, "mouthClose", close_delta, face_indices)
        results["mouthFunnel"] = _make(
            obj, "mouthFunnel", round_delta("funnel"), face_indices)
        results["mouthPucker"] = _make(
            obj, "mouthPucker", round_delta("pucker"), face_indices)
    else:
        for name in ("mouthFunnel", "mouthPucker"):
            block = me.shape_keys.key_blocks.get(name)
            results[name] = (_stats(_basis(obj), block) if block else
                             _make(obj, name, lambda i, co: None, []))
        block = me.shape_keys.key_blocks.get("mouthClose")
        if block is not None:
            results["mouthClose"] = _stats(_basis(obj), block)
        else:
            results["mouthClose"] = _make(
                obj, "mouthClose", close_delta, face_indices)

    # Lateral whole-mouth motion.
    for name, sign in (("mouthLeft", 1.0), ("mouthRight", -1.0)):
        results[name] = _make(obj, name, lambda i, co, s=sign:
                              Vector((s * 0.24 * A0 * lip_mask(i, co), 0.0, 0.0)),
                              face_indices)

    # Paired mouth expressions.
    for side in ("Left", "Right"):
        lateral = 1.0 if side == "Left" else -1.0

        def corner_delta(kind):
            def delta(i, co):
                w = lip_mask(i, co, side=side, corner=True)
                if not w:
                    return None
                if kind == "smile":
                    strength = float(guide_settings.get("smile_strength", 1.0))
                    return Vector((lateral * 0.16 * A0 * w,
                                   -0.05 * A0 * w,
                                   0.52 * A0 * w)) * strength
                if kind == "frown":
                    return (-lateral * 0.04 * A0 * w, 0.03 * A0 * w,
                            -0.28 * A0 * w)
                if kind == "dimple":
                    return (lateral * 0.05 * A0 * w, 0.20 * A0 * w,
                            0.04 * A0 * w)
                return (lateral * 0.32 * A0 * w, 0.0, 0.02 * A0 * w)
            return delta

        for suffix, kind in (("Smile", "smile"), ("Frown", "frown"),
                             ("Dimple", "dimple"), ("Stretch", "stretch")):
            name = f"mouth{suffix}{side}"
            results[name] = _make(obj, name, corner_delta(kind), face_indices)

        def vertical_lip(upper, amount, forward=0.0):
            def delta(i, co):
                w = lip_mask(i, co, side=side, upper=upper)
                if not w:
                    return None
                return (0.0, forward * A0 * w, amount * A0 * w)
            return delta

        results[f"mouthLowerDown{side}"] = _make(
            obj, f"mouthLowerDown{side}", vertical_lip(False, -0.34), face_indices)
        results[f"mouthUpperUp{side}"] = _make(
            obj, f"mouthUpperUp{side}", vertical_lip(True, 0.30), face_indices)

        def press_delta(i, co):
            upper = co.z >= seam_z(P, co.x)
            w = lip_mask(i, co, side=side, upper=upper)
            if not w:
                return None
            return (0.0, 0.12 * A0 * w, (-0.18 if upper else 0.18) * A0 * w)
        results[f"mouthPress{side}"] = _make(obj, f"mouthPress{side}",
                                              press_delta, face_indices)

    # Symmetric roll and shrug shapes.
    for name, upper, z_amount, y_amount in (
            ("mouthRollLower", False, 0.22, 0.22),
            ("mouthRollUpper", True, -0.20, 0.22),
            ("mouthShrugLower", False, 0.22, -0.12),
            ("mouthShrugUpper", True, 0.24, -0.10)):
        results[name] = _make(
            obj, name,
            lambda i, co, u=upper, za=z_amount, ya=y_amount:
                Vector((0.0, ya * A0 * lip_mask(i, co, upper=u),
                        za * A0 * lip_mask(i, co, upper=u))), face_indices)

    # Nose and cheeks are inferred between the measured mouth and eye line.
    def oval_mask(co, cx, cz, rx, rz):
        dx, dz = (co.x - cx) / rx, (co.z - cz) / rz
        if dx * dx + dz * dz >= 1.0 or co.y > front_cut + 0.07 * S:
            return 0.0
        return _smooth(1.0 - dx * dx - dz * dz)

    for side in ("Left", "Right"):
        sx = 1.0 if side == "Left" else -1.0
        nose_cx = sx * 0.30 * XC
        cheek_cx = sx * 1.20 * XC

        results[f"noseSneer{side}"] = _make(
            obj, f"noseSneer{side}",
            lambda i, co, cx=nose_cx:
                Vector((0.0, -0.035 * S, 0.045 * S))
                * oval_mask(co, cx, landmarks["nose_z"], 0.62 * XC, 0.09 * S),
            face_indices)
        results[f"cheekSquint{side}"] = _make(
            obj, f"cheekSquint{side}",
            lambda i, co, cx=cheek_cx:
                Vector((0.0, -0.018 * S, 0.035 * S))
                * oval_mask(co, cx, landmarks["cheek_z"], 0.95 * XC, 0.11 * S),
            face_indices)

    def puff_delta(i, co):
        left = oval_mask(co, 1.20 * XC, landmarks["cheek_z"], 1.05 * XC, 0.12 * S)
        right = oval_mask(co, -1.20 * XC, landmarks["cheek_z"], 1.05 * XC, 0.12 * S)
        w = max(left, right)
        if not w:
            return None
        return (math.copysign(0.022 * S * w, co.x), -0.045 * S * w,
                0.006 * S * w)
    results["cheekPuff"] = _make(obj, "cheekPuff", puff_delta, face_indices)

    # Brow shells support rigid and partial-shell expressions cleanly.
    brow_components = profile["roles"].get("brows") or []
    brow_indices = _component_indices(comp_of, brow_components)
    for side in ("Left", "Right"):
        results[f"browDown{side}"] = _make(
            obj, f"browDown{side}",
            lambda i, co, sd=side:
                Vector((0.0, 0.0, -0.020 * S * side_weight(co.x, sd))),
            brow_indices)
        results[f"browOuterUp{side}"] = _make(
            obj, f"browOuterUp{side}",
            lambda i, co, sd=side:
                Vector((0.0, 0.0, 0.030 * S * side_weight(co.x, sd)
                        * _smooth(abs(co.x) / max(1.35 * XC, 1e-8)))),
            brow_indices)
    results["browInnerUp"] = _make(
        obj, "browInnerUp",
        lambda i, co: Vector((0.0, 0.0, 0.032 * S
                              * _smooth(1.0 - abs(co.x) / max(1.30 * XC, 1e-8)))),
        brow_indices)

    # Tongue is a separate skinned object in this pipeline. Keep the ARKit key
    # on the geometry it actually deforms and report it as a distributed target.
    if tongue_obj is None:
        tongue_obj = bpy.data.objects.get("tongue")
    if tongue_obj is not None and tongue_obj.type == 'MESH':
        local_delta = tongue_obj.matrix_world.inverted().to_3x3() @ Vector(
            (0.0, -0.12 * S, -0.018 * S))
        results["tongueOut"] = _make(
            tongue_obj, "tongueOut", lambda i, co, d=local_delta: d)
    else:
        results["tongueOut"] = {"moved": 0, "mean": 0.0, "max": 0.0}
        partial.append("tongueOut: no tongue mesh")

    vrc = {}
    if include_vrc:
        recipes = {
            "vrc.v_sil": [],
            "vrc.v_PP": [("lipsPressed", 1.0)],
            "vrc.v_FF": [("mouthFF", 1.0)],
            "vrc.v_TH": [("mouthWide", 0.25), ("jawOpen", 0.18)],
            "vrc.v_DD": [("mouthWide", 0.30), ("jawOpen", 0.28)],
            "vrc.v_kk": [("mouthWide", 0.35), ("jawOpen", 0.45)],
            "vrc.v_CH": [("mouthFunnel", 0.35), ("lipsPressed", 0.18)],
            "vrc.v_SS": [("mouthWide", 0.50)],
            "vrc.v_nn": [("mouthWide", 0.30), ("jawOpen", 0.18)],
            "vrc.v_RR": [("mouthFunnel", 0.35), ("jawOpen", 0.25)],
            "vrc.v_aa": [("mouthWide", 0.42), ("jawOpen", 0.82)],
            "vrc.v_E": [("mouthWide", 0.65), ("jawOpen", 0.38)],
            "vrc.v_I": [("mouthWide", 0.82), ("jawOpen", 0.18)],
            "vrc.v_O": [("mouthFunnel", 0.90), ("jawOpen", 0.52)],
            "vrc.v_U": [("mouthPucker", 0.92), ("jawOpen", 0.20)],
        }
        for name in VRC_15:
            vrc[name] = _combine(obj, name, recipes[name])

    empty = [name for name in ARKIT_52
             if results.get(name, {}).get("moved", 0) == 0]
    neutral_weights = {
        key.name: key.value for key in obj.data.shape_keys.key_blocks
        if key.name != "Basis" and abs(key.value) > 1e-6
    }
    targets_by_expression = {
        name: (tongue_obj.name if name == "tongueOut" and tongue_obj else obj.name)
        for name in ARKIT_52
    }
    targets_by_expression.update({name: obj.name for name in VRC_15})
    report = {
        "arkit": results,
        "arkit_present": sum(1 for name in ARKIT_52 if name in results),
        "arkit_nonempty": len(ARKIT_52) - len(empty),
        "arkit_required": len(ARKIT_52),
        "arkit_empty": empty,
        "vrc": vrc,
        "vrc_present": len(vrc),
        "partial": partial,
        "targets": {"face": obj.name,
                    "tongue": tongue_obj.name if tongue_obj else None},
        "targets_by_expression": targets_by_expression,
        "neutral_weights": neutral_weights,
        "status": "ready" if not empty else "partial",
        "eye_support": {side: bool(spec.get("indices"))
                        for side, spec in eye_specs.items()},
        "mouth_field": mouth_field.report(me.vertices, face_indices),
    }
    _PRESERVE_EXISTING = set()
    return report


def retain_calibration(obj, tongue_obj=None):
    """Remove final-delivery keys while keeping editable calibration poses."""
    keep = set(CALIBRATION_KEYS) | {
        "Basis", "blink_L", "blink_R", "upperLipRaise",
        "mouthWide", "lipsPressed", "mouthFF",
    }
    removed = []
    if obj.data.shape_keys:
        for key in list(obj.data.shape_keys.key_blocks):
            if key.name in ARKIT_52 or key.name in VRC_15:
                if key.name not in keep:
                    removed.append(key.name)
                    obj.shape_key_remove(key)
    if tongue_obj is not None and tongue_obj.data.shape_keys:
        for key in list(tongue_obj.data.shape_keys.key_blocks):
            if key.name in ARKIT_52 and key.name not in keep:
                removed.append(key.name)
                tongue_obj.shape_key_remove(key)
    return {"kept": sorted(name for name in keep
                           if obj.data.shape_keys and
                           obj.data.shape_keys.key_blocks.get(name)),
            "removed": sorted(removed)}
