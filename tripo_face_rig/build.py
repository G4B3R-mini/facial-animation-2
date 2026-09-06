"""Stage 2: construct the rig from a measured profile.

Every constant below is expressed as a fraction of a measured quantity
(head scale S, lip aperture A0, mouth corner XC). Nothing is absolute.

Two rules that are load-bearing and easy to get wrong:

  1. Deform weights MUST be computed from basis coordinates, before or
     independently of the mouth-close shape key. Once the lips are sealed
     the upper and lower rims sit at the same height and no z-threshold
     can separate them.
  2. Chin and neck are separated by DEPTH, not height. They overlap almost
     completely in z; a flat height cut slices through the middle of the chin.
"""
import math
import bpy
import bmesh
from mathutils import Vector
from . import util

VISEMES = ["mouthWide", "mouthPucker", "mouthFunnel", "lipsPressed", "mouthFF"]
BLINKS = ["blink_L", "blink_R"]

DEFAULTS = {
    "seal_overlap": 0.22,        # x A0, vertical lip overlap
    "seal_ybias": 0.125,         # x A0, lower lip tucks behind upper
    "seal_radius": 1.30,         # x A0, falloff radius around the rim
    "seal_corner_scale": 1.08,   # model the corner slightly outboard of measured
    "corner_weight": 0.42,       # jaw weight the commissure converges to
    "upper_lip_raise": 0.44,     # x A0
    "jaw_open_ref_deg": 18.0,    # jaw angle at which the corrective is full
    "tongue": True,
    "visemes": True,
    # Resting strength of the lip seal, 0..1. mouth_close() computes enough
    # travel to close the measured aperture plus an overlap, but where the
    # source mesh was modelled with a wide-open mouth that travel overshoots
    # badly: on a bearded quad head, full strength jammed the moustache into
    # the lower lip and lost the lip line entirely, while 0.25 gave a natural
    # closed mouth. The driver scales its resting value by this.
    "seal_rest": 1.0,
    "split_seam": False,         # cut the lip band (invaginated mouths); see
                                 # split_lip_seam() for when this is needed
}


# ---------------------------------------------------------------- curves

def _slice_lookup(P, x, key):
    """Linear interpolation across the measured slice array."""
    sl = P.get("slices")
    if not sl:
        return None
    x0 = sl[0]["x"]
    step = P["slice_step"]
    if x <= x0:
        return sl[0][key]
    if x >= sl[-1]["x"]:
        return sl[-1][key]
    f = (x - x0) / step
    i = int(f)
    if i >= len(sl) - 1:
        return sl[-1][key]
    t = f - i
    return sl[i][key] * (1.0 - t) + sl[i + 1][key] * t


def seam_z(P, x):
    """Fitted seam inside the mouth; jawline slope beyond the commissure.

    The fit comes from the central band only (see measure.py) -- fitting the
    full width flattens the curve and the seal then misses the corners.
    """
    ax = abs(x)
    a, b = P["seam_z"]
    xc = P["corner_x"]
    if ax <= xc:
        return a + b * x * x
    return (a + b * xc * xc) + (ax - xc) * P["jaw_slope"]


def seam_y(P, x):
    a, b = P["seam_y"]
    return a + b * x * x


def aperture(P, x):
    """Parabolic aperture, closing at the commissure.

    seal_corner_scale nudges the modelled corner slightly outboard of the
    measured one so the seal still has material to work with right at the
    commissure, where the measurement is least reliable.
    """
    xc = P["corner_x"] * P.get("seal_corner_scale", 1.0)
    t = x / xc
    v = P["A0"] * (1.0 - t * t)
    return v if v > 0.0 else 0.0


def rim(P, x, lower):
    sz = seam_z(P, x)
    sy = seam_y(P, x)
    amp = aperture(P, x)
    off = P["rim_off"][0] if lower else P["rim_off"][1]
    return (sz - amp * 0.5 if lower else sz + amp * 0.5), sy + off


def derive_params(profile, opts):
    m = profile["mouth"]
    S = profile["scale"]
    A0 = m["aperture_centre"]
    XC = m["corner_x"]
    cond = profile["condyle"]["pivot"]
    ear = profile["condyle"]["ear_half_width"]

    slices = m.get("slices") or []
    slice_max_x = max(abs(slices[0]["x"]), abs(slices[-1]["x"])) if slices else XC
    if slices:
        edge_z = 0.5 * (slices[-1]["lo"] + slices[-1]["hi"])
    else:
        edge_z = m["seam_z"][0] + m["seam_z"][1] * XC * XC
    denom = max(1e-6, ear - slice_max_x)
    jaw_slope = (cond[2] - edge_z) / denom

    junk = profile["cavity"]["interior_junk_y"] if profile["cavity"] else None
    # Only trust "junk" that lies BEHIND the teeth. On an invaginated mouth the
    # interior is properly modelled and the nearest interior surface IS the
    # inner lip -- taking that as junk parks the bag in front of the teeth
    # (measured rear -0.3207 against a teeth front of -0.2770) and it pokes
    # straight through the face.
    if junk is not None and junk <= m["teeth_front_y"] + 0.02 * S:
        junk = None
    bag_rear = (junk - 0.03 * S) if junk is not None else (m["seam_y"][0] + 0.21 * S)

    face_id = profile["roles"]["face"]
    face_info = profile.get("shells", {}).get(str(face_id), {})
    face_fraction = face_info.get("verts", 0) / max(profile.get("verts", 1), 1)
    # A very large face island usually means facial hair or an inner-mouth
    # sheet is welded to the skin.  Large jaw rotations visibly stretch that
    # sheet; cap the safe performance range while leaving ordinary heads at
    # the full reference angle.
    #
    # face_fraction is only a PROXY for "the mouth is a welded sheet". Where the
    # mouth has actually been MEASURED as an aperture there is a real opening,
    # and the proxy must not override the measurement. A bearded head from a
    # quad generation measured mode="aperture" with placed teeth, but its
    # face_fraction of 0.62 clamped the jaw to 6 deg and the mouth visibly would
    # not open at any viseme.
    mouth_mode = (profile.get("mouth") or {}).get("mode")
    if mouth_mode == "aperture":
        jaw_max_deg = opts["jaw_open_ref_deg"]
    else:
        jaw_max_deg = 6.0 if face_fraction > 0.45 else opts["jaw_open_ref_deg"]
    face_verts = face_info.get("verts", 2152)
    density_scale = (1.0 if face_fraction > 0.45 else
                     max(0.90, min(1.35, math.sqrt(2152.0 / max(face_verts, 1)))))

    P = dict(opts)
    P.update({
        "S": S, "A0": A0, "corner_x": XC,
        "seam_z": m["seam_z"], "seam_y": m["seam_y"],
        "rim_off": m["rim_offsets"],
        "teeth_front_y": m["teeth_front_y"],
        "front_cut": m["front_cut"],
        "jaw_slope": jaw_slope,
        "pivot": cond,
        "ear_half_width": ear,
        "roles": profile["roles"],
        "bag_rear_y": bag_rear,
        "slices": slices,
        "guide_rails": m.get("guide_rails"),
        "guide_settings": m.get("guide_settings") or {},
        "slice_step": m.get("slice_step") or (S * 0.0055),
        "slice_max_x": slice_max_x,
        "seam_edge_z": edge_z,
        "face_fraction": face_fraction,
        "jaw_max_deg": jaw_max_deg,
        "density_scale": density_scale,
    })
    return P


# ---------------------------------------------------------------- mouth close

def build_mouth_close(obj, P, comp_of):
    me = obj.data
    face = P["roles"]["face"]
    S, A0 = P["S"], P["A0"]
    OV = P["seal_overlap"] * A0
    YB = P["seal_ybias"] * A0
    R = P["seal_radius"] * A0
    tf_margin = 0.009 * S

    if me.shape_keys is None:
        obj.shape_key_add(name="Basis", from_mix=False)
    for kb in list(me.shape_keys.key_blocks):
        if kb.name == "mouthClose":
            obj.shape_key_remove(kb)
    key = obj.shape_key_add(name="mouthClose", from_mix=False)

    n = 0
    for v in me.vertices:
        if comp_of[v.index] != face:
            continue
        x, y, z = v.co.x, v.co.y, v.co.z
        if abs(x) > P["corner_x"] * 1.15:
            continue
        amp = aperture(P, x)
        if amp <= 0.0:
            continue
        sz = seam_z(P, x)
        if abs(z - sz) > 0.16 * S:
            continue
        sy = seam_y(P, x)
        if P["teeth_front_y"] is not None and sy > P["teeth_front_y"] - tf_margin:
            sy = P["teeth_front_y"] - tf_margin
        lower = z < sz
        rz, ry = rim(P, x, lower)
        if lower:
            tz, ty = sz + OV, sy + YB
        else:
            tz, ty = sz - OV, sy
        dz, dy = z - rz, y - ry
        d = math.sqrt(dz * dz + dy * dy)
        if d >= R:
            continue
        w = util.smoothstep(1.0 - d / R)
        key.data[v.index].co.z = z + (tz - rz) * w
        key.data[v.index].co.y = y + (ty - ry) * w * w
        n += 1
    key.value = 1.0
    return n


# ---------------------------------------------------------------- armature

def _find_view3d():
    """Locate a VIEW_3D across all windows.

    bpy.context.window is None when running headless, and also when driven
    from some MCP/timer contexts, so scan the window manager instead.
    """
    wm = bpy.data.window_managers[0] if bpy.data.window_managers else None
    if wm is None:
        return (None, None, None)
    for win in wm.windows:
        scr = getattr(win, "screen", None)
        if scr is None:
            continue
        for area in scr.areas:
            if area.type != 'VIEW_3D':
                continue
            for region in area.regions:
                if region.type == 'WINDOW':
                    return (win, area, region)
    return (None, None, None)


def _mode_set(obj, mode):
    vl = bpy.context.view_layer
    for o in vl.objects:
        try:
            if o.mode != 'OBJECT' and o is not obj:
                pass
        except Exception:
            pass
    vl.objects.active = obj
    obj.hide_viewport = False
    try:
        obj.hide_set(False)
    except Exception:
        pass
    try:
        bpy.ops.object.mode_set(mode=mode)
        if obj.mode == mode:
            return
    except RuntimeError:
        pass
    win, area, region = _find_view3d()
    if area is not None:
        with bpy.context.temp_override(window=win, area=area, region=region,
                                       object=obj, active_object=obj):
            bpy.ops.object.mode_set(mode=mode)
        if obj.mode == mode:
            return
    # headless: no VIEW_3D exists at all
    with bpy.context.temp_override(object=obj, active_object=obj,
                                   selected_objects=[obj],
                                   selected_editable_objects=[obj]):
        bpy.ops.object.mode_set(mode=mode)


def build_armature(obj, P, comp_of, name="face_rig"):
    me = obj.data
    S = P["S"]
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    arm = bpy.data.armatures.new(name)
    ao = bpy.data.objects.new(name, arm)
    bpy.context.collection.objects.link(ao)

    px, py, pz = P["pivot"]
    chin_y = seam_y(P, 0.0) - 0.02 * S
    chin_z = seam_z(P, 0.0) - 0.20 * S

    eyes = P["roles"]["eyes"]
    eye_centres = []
    for c in eyes:
        xs = []
        ys = []
        zs = []
        for vi, cc in comp_of.items():
            if cc == c:
                co = me.vertices[vi].co
                xs.append(co.x)
                ys.append(co.y)
                zs.append(co.z)
        if xs:
            eye_centres.append(((min(xs) + max(xs)) * 0.5,
                                (min(ys) + max(ys)) * 0.5,
                                (min(zs) + max(zs)) * 0.5))
    eye_centres.sort()

    for o in bpy.context.view_layer.objects:
        try:
            o.select_set(False)
        except Exception:
            pass
    ao.select_set(True)
    bpy.context.view_layer.objects.active = ao

    _mode_set(ao, 'EDIT')
    eb = arm.edit_bones
    head = eb.new("head")
    head.head = (0.0, py, pz - 0.24 * S)
    head.tail = (0.0, py, pz + 0.18 * S)

    jaw = eb.new("jaw")
    jaw.head = (0.0, py, pz)
    jaw.tail = (0.0, chin_y, chin_z)
    jaw.parent = head
    jaw.use_connect = False

    tongue_z = seam_z(P, 0.0) - 0.018 * S
    tng = eb.new("tongue")
    tng.head = (0.0, P["bag_rear_y"] - 0.01 * S, tongue_z)
    tng.tail = (0.0, seam_y(P, 0.0) + 0.04 * S, tongue_z)
    tng.parent = jaw
    tng.use_connect = False

    names = []
    for i, ec in enumerate(eye_centres):
        nm = "eye_R" if ec[0] < 0 else "eye_L"
        b = eb.new(nm)
        b.head = (ec[0], ec[1], ec[2])
        b.tail = (ec[0], ec[1] - 0.09 * S, ec[2])
        b.parent = head
        b.use_connect = False
        names.append(nm)

    # BROWS: one bone per shell, at the shell centre. Brows on these heads are
    # separate floating shells, so rigid binding is enough; raising is mostly
    # translation, so animators key location rather than rotation.
    brow_names = []
    brows = P["roles"].get("brows") or []
    for c in brows:
        pts = [me.vertices[vi].co for vi, cc in comp_of.items() if cc == c]
        if not pts:
            continue
        cx = 0.5 * (min(p.x for p in pts) + max(p.x for p in pts))
        cy = 0.5 * (min(p.y for p in pts) + max(p.y for p in pts))
        cz = 0.5 * (min(p.z for p in pts) + max(p.z for p in pts))
        nm = "brow_R" if cx < 0 else "brow_L"
        b = eb.new(nm)
        b.head = (cx, cy, cz)
        b.tail = (cx, cy, cz + 0.055 * S)
        b.parent = head
        b.use_connect = False
        brow_names.append(nm)
    _mode_set(ao, 'OBJECT')

    for pb in ao.pose.bones:
        pb.rotation_mode = 'XYZ'

    jaw_limit = ao.pose.bones["jaw"].constraints.new('LIMIT_ROTATION')
    jaw_limit.use_limit_x = True
    jaw_limit.min_x = 0.0
    jaw_limit.max_x = math.radians(P["jaw_max_deg"])
    jaw_limit.owner_space = 'LOCAL'

    # Clamp the eyes to the measured-safe gaze envelope. Wider darts swing
    # untextured sclera past the lids: verified bad at 18 deg yaw, clean at 10.
    for nm in names:
        pb = ao.pose.bones[nm]
        con = pb.constraints.new('LIMIT_ROTATION')
        con.use_limit_x = con.use_limit_y = con.use_limit_z = True
        con.min_x = math.radians(-6.0)   # look up
        con.max_x = math.radians(8.0)    # look down
        con.min_y = con.max_y = 0.0
        con.min_z = math.radians(-10.0)
        con.max_z = math.radians(10.0)
        con.owner_space = 'LOCAL'
    return ao, names + brow_names


# ---------------------------------------------------------------- weights

def jaw_weight(P, x, y, z):
    """Jaw influence for one basis-space point on the face shell."""
    S, XC = P["S"], P["corner_x"]
    ax = abs(x)
    sz = seam_z(P, x)

    # sharp at the midline so the lips part; wider outboard
    density = P.get("density_scale", 1.0)
    h = density * (0.0135 * S + 0.20 * max(0.0, ax - 0.056 * S))
    d = z - sz
    if d <= -h:
        w = 1.0
    elif d >= h:
        w = 0.0
    else:
        w = util.smoothstep((h - d) / (2.0 * h))

    # lateral taper: both lips converge on one weight at the commissure,
    # then the field returns to normal past the corner
    dl = abs(z - sz)
    lp = util.ramp(dl, 0.073 * S, 0.028 * S)
    up = util.ramp(ax, 0.35 * XC, 1.0 * XC)
    dn = util.ramp(ax, 1.62 * XC, 1.10 * XC)
    s = lp * up * dn
    w = w * (1.0 - s) + P["corner_weight"] * s

    # chin/neck split by DEPTH, not height
    z_neck = sz - 0.075 * S
    if z < z_neck:
        sy = seam_y(P, 0.0)
        # fn == 1 forward (chin keeps jaw weight), 0 further back (neck released).
        # Getting this ramp the wrong way round drives the neck and freezes the chin.
        fn = util.ramp(y, sy + 0.18 * S, sy + 0.04 * S)
        k = util.ramp(z, z_neck, z_neck - 0.068 * S * density)
        w = w * (1.0 - k * (1.0 - fn))

    # release toward the back of the head
    back0 = 0.0
    w = w * util.ramp(y, back0 + 0.112 * S, back0)
    return w


def split_lip_seam(obj, P, comp_of, seam_data=None):
    """Cut the polygon band bridging the lip line, so the lips can part.

    A mouth modelled as an INVAGINATION -- lips fold inward and run back into
    the head, no boundary edge at the lip line -- has a continuous band of
    polygons spanning the seam. Splitting the weights 0/1 across that band
    stretches it into a membrane that hangs in front of the teeth: on the test
    head, teeth visibility went 16 samples at rest -> 2 -> 0 as the jaw opened,
    instead of increasing.

    split_edges() moves nothing, so the rest pose is unchanged; the two rims
    only separate once the jaw rotates. Vertex indices and island numbering DO
    change, so callers must re-measure afterwards.
    """
    import bmesh
    me = obj.data
    XC = P["corner_x"]
    face = P["roles"]["face"]
    bm = bmesh.new(); bm.from_mesh(me)
    bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table()
    if seam_data and seam_data.get("validated"):
        points = [Vector(point) for point in seam_data.get("local_points") or []]
        if len(points) < 4:
            bm.free()
            raise RuntimeError("validated mouth seam contains too few points")
        candidates = [v for v in bm.verts if comp_of.get(v.index) == face]
        resolved = []
        tolerance = max(1e-6, 0.002 * P["S"])
        for point in points:
            vertex = min(candidates, key=lambda item: (item.co - point).length_squared)
            if (vertex.co - point).length > tolerance:
                bm.free()
                raise RuntimeError(
                    "mouth seam no longer matches the source topology; recapture it")
            if not resolved or vertex is not resolved[-1]:
                resolved.append(vertex)
        path_edges = []
        for left, right in zip(resolved, resolved[1:]):
            edge = bm.edges.get((left, right))
            if edge is None:
                bm.free()
                raise RuntimeError(
                    "captured mouth seam is not an edge path after preparation; recapture it")
            path_edges.append(edge)
        # Keep one edge at either corner unsplit. Those short anchored segments
        # act as commissure hinges and prevent pointed corner tears.
        cut = path_edges[1:-1] if seam_data.get("anchor_endpoints", True) else path_edges
        if len(cut) < 3:
            bm.free()
            raise RuntimeError("mouth seam is too short after anchoring its corners")
        bmesh.ops.split_edges(bm, edges=cut)
        bm.to_mesh(me); me.update(); bm.free()
        obj["face_rig_explicit_seam"] = True
        obj["face_rig_seam_edges"] = len(cut)
        return len(cut)
    cut = []
    for e in bm.edges:
        v0, v1 = e.verts
        if not all(comp_of.get(v.index) == face for v in (v0, v1)):
            continue
        # stop short of the measured corner: the lateral taper is only fully
        # converged at XC, so cutting right up to it leaves the outermost pair
        # free to separate into a pointed tab at the commissure
        if not all(abs(v.co.x) <= 0.90 * XC and v.co.y < P["front_cut"]
                   for v in (v0, v1)):
            continue
        if (v0.co.z - seam_z(P, v0.co.x)) * (v1.co.z - seam_z(P, v1.co.x)) < 0:
            cut.append(e)
    if cut:
        bmesh.ops.split_edges(bm, edges=cut)
        bm.to_mesh(me); me.update()
    bm.free()
    return len(cut)


def vertex_sides(obj, P):
    """Which side of the seam each vertex's FACES are on.

    After a split the two copies of a seam vertex share coordinates, so a
    position-based weight gives them the same value and they move together --
    which defeats the split entirely. The faces disambiguate them.
    """
    import bmesh
    bm = bmesh.new(); bm.from_mesh(obj.data); bm.verts.ensure_lookup_table()
    sides = {}
    for v in bm.verts:
        if not v.link_faces:
            continue
        acc = 0.0
        for f in v.link_faces:
            c = f.calc_center_median()
            acc += c.z - seam_z(P, c.x)
        sides[v.index] = acc / len(v.link_faces)
    bm.free()
    return sides


def assign_weights(obj, ao, P, comp_of, sides=None):
    """Computed from BASIS coordinates -- see module docstring, rule 1."""
    me = obj.data
    roles = P["roles"]
    for nm in ["head", "jaw", "eye_L", "eye_R"]:
        g = obj.vertex_groups.get(nm)
        if g is not None:
            obj.vertex_groups.remove(g)
    g_head = obj.vertex_groups.new(name="head")
    g_jaw = obj.vertex_groups.new(name="jaw")
    g_eyes = {}
    for c in roles["eyes"]:
        pass

    brow_groups = {}
    for c in (roles.get("brows") or []):
        xs = [me.vertices[vi].co.x for vi, cc in comp_of.items() if cc == c]
        if not xs:
            continue
        nm = "brow_R" if (sum(xs) / len(xs)) < 0 else "brow_L"
        g = obj.vertex_groups.get(nm)
        if g is not None:
            obj.vertex_groups.remove(g)
        brow_groups[c] = obj.vertex_groups.new(name=nm)

    eye_groups = {}
    for c in roles["eyes"]:
        xs = []
        for vi, cc in comp_of.items():
            if cc == c:
                xs.append(me.vertices[vi].co.x)
        nm = "eye_R" if (sum(xs) / len(xs)) < 0 else "eye_L"
        eye_groups[c] = obj.vertex_groups.new(name=nm)

    lower_teeth = set(roles.get("teeth_lower_all") or [roles["teeth_lower"]])
    lower_teeth.discard(None)
    direct_jaw = obj.vertex_groups.get("FRG_jaw")
    stats = {"jaw": 0, "eyes": 0, "static": 0,
             "direct_jaw": direct_jaw is not None}
    for v in me.vertices:
        c = comp_of[v.index]
        i = v.index
        if c in eye_groups:
            eye_groups[c].add([i], 1.0, 'REPLACE')
            stats["eyes"] += 1
            continue
        if c in brow_groups:
            brow_groups[c].add([i], 1.0, 'REPLACE')
            stats["eyes"] += 1
            continue
        if c in lower_teeth:
            g_jaw.add([i], 1.0, 'REPLACE')
            stats["jaw"] += 1
            continue
        if c != roles["face"]:
            g_head.add([i], 1.0, 'REPLACE')
            stats["static"] += 1
            continue
        if direct_jaw is not None:
            try:
                w = direct_jaw.weight(i)
            except RuntimeError:
                w = 0.0
        else:
            w = jaw_weight(P, v.co.x, v.co.y, v.co.z)
        if sides is not None and direct_jaw is None:
            # resolve split vertices by SIDE: sample the field a little off the
            # seam in the direction this vertex's faces actually lie
            sd = sides.get(i)
            ax = abs(v.co.x)
            h = P.get("density_scale", 1.0) * (
                0.0135 * P["S"] + 0.20 * max(0.0, ax - 0.056 * P["S"]))
            sz0 = seam_z(P, v.co.x)
            if sd is not None and abs(v.co.z - sz0) < 2.5 * h:
                w = jaw_weight(P, v.co.x, v.co.y,
                               sz0 + (1.35 * h if sd > 0 else -1.35 * h))
        if w > 0.001:
            g_jaw.add([i], w, 'REPLACE')
            stats["jaw"] += 1
        g_head.add([i], 1.0 - w, 'REPLACE')

    mod = None
    for m in obj.modifiers:
        if m.type == 'ARMATURE':
            mod = m
    if mod is None:
        mod = obj.modifiers.new(name="Armature", type='ARMATURE')
    mod.object = ao
    obj.parent = ao
    obj.matrix_parent_inverse = ao.matrix_world.inverted()
    return stats


# ---------------------------------------------------------------- interior

def _uvsphere(u, v):
    bm = bmesh.new()
    try:
        bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=1.0)
    except TypeError:
        bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, diameter=1.0)
    return bm


def build_mouth_bag(obj, ao, P, comp_of, name="mouth_bag"):
    me = obj.data
    S = P["S"]
    roles = P["roles"]
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)

    teeth = set(roles.get("teeth_upper_all") or [roles["teeth_upper"]])
    teeth.update(roles.get("teeth_lower_all") or [roles["teeth_lower"]])
    teeth.discard(None)
    zs = []
    for vi, c in comp_of.items():
        if c in teeth:
            zs.append(me.vertices[vi].co.z)
    z_lo = min(zs) - 0.006 * S
    z_hi = max(zs)

    front = seam_y(P, 0.0) + 0.036 * S
    # never let the bag reach in front of the teeth -- they are the frontmost
    # interior structure, so anything ahead of them is already outside the lips
    front = max(front, P["teeth_front_y"] + 0.03 * S)
    rear = P["bag_rear_y"]
    cy = 0.5 * (front + rear)
    ry = 0.5 * (rear - front)
    cz = 0.5 * (z_lo + z_hi)
    rz = 0.5 * (z_hi - z_lo)
    rx = 0.86 * P["corner_x"]

    bm = _uvsphere(28, 18)
    for v in bm.verts:
        v.co.x = v.co.x * rx
        v.co.y = cy + v.co.y * ry
        v.co.z = cz + v.co.z * rz
    bmesh.ops.reverse_faces(bm, faces=bm.faces[:])   # normals inward
    nm = bpy.data.meshes.new(name)
    bm.to_mesh(nm)
    bm.free()
    for p in nm.polygons:
        p.use_smooth = True

    bag = bpy.data.objects.new(name, nm)
    bpy.context.collection.objects.link(bag)

    mat = bpy.data.materials.get("mouth_interior")
    if mat is None:
        mat = bpy.data.materials.new("mouth_interior")
    mat.use_nodes = True
    for n in mat.node_tree.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            n.inputs['Base Color'].default_value = (0.13, 0.035, 0.04, 1.0)
            n.inputs['Roughness'].default_value = 0.65
    # without this the front wall draws as a solid plug over the interior
    mat.use_backface_culling = True
    nm.materials.append(mat)
    bag.visible_shadow = False

    gh = bag.vertex_groups.new(name="head")
    gj = bag.vertex_groups.new(name="jaw")
    h = 0.025 * S
    for v in nm.vertices:
        sz = seam_z(P, v.co.x)
        d = v.co.z - sz
        if d <= -h:
            w = 1.0
        elif d >= h:
            w = 0.0
        else:
            w = util.smoothstep((h - d) / (2.0 * h))
        if w > 0.001:
            gj.add([v.index], w, 'REPLACE')
        gh.add([v.index], 1.0 - w, 'REPLACE')

    mod = bag.modifiers.new(name="Armature", type='ARMATURE')
    mod.object = ao
    bag.parent = ao
    bag.matrix_parent_inverse = ao.matrix_world.inverted()
    return {"rx": rx, "y": [front, rear], "z": [z_lo, z_hi]}


def build_tongue(obj, ao, P, name="tongue"):
    S = P["S"]
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)

    cz = seam_z(P, 0.0) - 0.018 * S
    front = seam_y(P, 0.0) + 0.045 * S
    rear = P["bag_rear_y"] + 0.03 * S
    cy = 0.5 * (front + rear)
    ry = 0.5 * (rear - front)
    rx = 0.53 * P["corner_x"]
    rz = 0.027 * S

    bm = _uvsphere(20, 12)
    for v in bm.verts:
        ty = (v.co.y + 1.0) * 0.5
        v.co.x = v.co.x * rx * (0.55 + 0.45 * ty)
        v.co.z = cz + v.co.z * rz
        v.co.y = cy + v.co.y * ry
    nm = bpy.data.meshes.new(name)
    bm.to_mesh(nm)
    bm.free()
    for p in nm.polygons:
        p.use_smooth = True

    tg = bpy.data.objects.new(name, nm)
    bpy.context.collection.objects.link(tg)
    mat = bpy.data.materials.get("tongue_mat")
    if mat is None:
        mat = bpy.data.materials.new("tongue_mat")
    mat.use_nodes = True
    for n in mat.node_tree.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            n.inputs['Base Color'].default_value = (0.40, 0.125, 0.145, 1.0)
            n.inputs['Roughness'].default_value = 0.5
    nm.materials.append(mat)
    tg.visible_shadow = False

    vg = tg.vertex_groups.new(name="tongue")
    vg.add([v.index for v in nm.vertices], 1.0, 'REPLACE')
    mod = tg.modifiers.new(name="Armature", type='ARMATURE')
    mod.object = ao
    tg.parent = ao
    tg.matrix_parent_inverse = ao.matrix_world.inverted()
    return {"rx": rx, "y": [front, rear], "z": cz}


# ---------------------------------------------------------------- correctives

def _ensure_basis(obj):
    """Shape keys may not exist yet: build_mouth_close is skipped on an
    invaginated mouth, and it is what normally creates the Basis."""
    if obj.data.shape_keys is None:
        obj.shape_key_add(name="Basis", from_mix=False)


def build_upper_lip_corrective(obj, ao, P, comp_of):
    me = obj.data
    S, A0, XC = P["S"], P["A0"], P["corner_x"]
    face = P["roles"]["face"]
    amt = P["upper_lip_raise"] * A0
    band = 1.41 * A0
    reach = 1.21 * XC
    _ensure_basis(obj)

    for kb in list(me.shape_keys.key_blocks):
        if kb.name == "upperLipRaise":
            obj.shape_key_remove(kb)
    key = obj.shape_key_add(name="upperLipRaise", from_mix=False)

    n = 0
    for v in me.vertices:
        if comp_of[v.index] != face:
            continue
        x, z = v.co.x, v.co.z
        ax = abs(x)
        if ax > reach:
            continue
        d = z - seam_z(P, x)
        if d < -0.06 * A0 or d > band:
            continue
        w = util.smoothstep(1.0 - (d + 0.06 * A0) / (band + 0.06 * A0))
        lat = util.ramp(ax, reach, reach - 0.35 * reach)
        s = w * lat
        if s <= 0.001:
            continue
        key.data[v.index].co.z = z + amt * s
        key.data[v.index].co.y = v.co.y + 0.28 * amt * s
        n += 1

    key.value = 0.0
    fc = key.driver_add("value")
    drv = fc.driver
    drv.type = 'SCRIPTED'
    for vv in list(drv.variables):
        drv.variables.remove(vv)
    var = drv.variables.new()
    var.name = "jaw"
    var.type = 'TRANSFORMS'
    tg = var.targets[0]
    tg.id = ao
    tg.bone_target = "jaw"
    tg.transform_type = 'ROT_X'
    tg.transform_space = 'LOCAL_SPACE'
    ref = math.radians(P["jaw_open_ref_deg"])
    drv.expression = "min(1.0, max(0.0, jaw/%.4f))" % ref

    # Release the resting lip seal as the jaw opens.
    #
    # mouth_close() sets mouthClose = 1.0 to seal a mouth that was modelled
    # open, but nothing downstream ever released it: neither animate.py nor
    # lipsync_import.py so much as mentions the key. The seal then fights every
    # opening for the whole take. Measured on a bearded quad head over 319
    # paired lip-rim verts: mouthClose 0.0 gave mean separation 0.0350 with no
    # overlapping pairs, while 1.0 gave 0.0101 with 133 of 319 pairs
    # interpenetrating - lips that visibly overlap at rest and never part.
    seal = obj.data.shape_keys.key_blocks.get("mouthClose")
    if seal is not None:
        try:
            seal.driver_remove("value")
        except Exception:
            pass
        sfc = seal.driver_add("value")
        sdrv = sfc.driver
        sdrv.type = 'SCRIPTED'
        for vv in list(sdrv.variables):
            sdrv.variables.remove(vv)
        svar = sdrv.variables.new()
        svar.name = "jaw"
        svar.type = 'TRANSFORMS'
        stg = svar.targets[0]
        stg.id = ao
        stg.bone_target = "jaw"
        stg.transform_type = 'ROT_X'
        stg.transform_space = 'LOCAL_SPACE'
        sdrv.expression = ("%.4f * (1.0 - min(1.0, max(0.0, jaw/%.4f)))"
                           % (P.get("seal_rest", 1.0), ref))
    return n


def build_blinks(obj, P, comp_of):
    """Create measured eyelid-close shape keys around each eye shell.

    Tripo heads generally ship an eyeball behind an open eye socket but no
    separate eyelid mesh.  The only portable blink is therefore a local face
    deformation: upper-lid skin travels most of the distance to the measured
    eye equator, lower-lid skin travels the remainder, and the closed seam is
    nudged just in front of the eyeball.  Every radius comes from that eye's
    own shell bbox so stylised and realistic eyes use the same algorithm.
    """
    me = obj.data
    face = P["roles"]["face"]
    _ensure_basis(obj)
    for nm in BLINKS:
        old = me.shape_keys.key_blocks.get(nm)
        if old is not None:
            obj.shape_key_remove(old)

    made = {}
    landmarks = []
    for comp in P["roles"].get("eyes") or []:
        indices = [vi for vi, cc in comp_of.items() if cc == comp]
        if not indices:
            continue
        xs = [me.vertices[i].co.x for i in indices]
        ys = [me.vertices[i].co.y for i in indices]
        zs = [me.vertices[i].co.z for i in indices]
        cx = 0.5 * (min(xs) + max(xs))
        cy = 0.5 * (min(ys) + max(ys))
        cz = 0.5 * (min(zs) + max(zs))
        rx = max(0.5 * (max(xs) - min(xs)), 0.018 * P["S"])
        rz = max(0.5 * (max(zs) - min(zs)), 0.014 * P["S"])
        front_y = min(ys)
        landmarks.append((cx, cy, cz, rx, rz, front_y))

    if len(landmarks) == 1:
        cx, cy, cz, rx, rz, front_y = landmarks[0]
        landmarks.append((-cx, cy, cz, rx, rz, front_y))

    for cx, cy, cz, rx, rz, front_y in landmarks:
        side = "R" if cx < 0.0 else "L"
        name = "blink_" + side
        key = obj.shape_key_add(name=name, from_mix=False)
        close_z = cz - 0.08 * rz
        moved = 0

        for v in me.vertices:
            if comp_of[v.index] != face:
                continue
            x, y, z = v.co.x, v.co.y, v.co.z
            nx = abs(x - cx) / (1.75 * rx)
            nz = abs(z - cz) / (1.55 * rz)
            if nx >= 1.0 or nz >= 1.0 or y > cy + 0.38 * rz:
                continue
            # Smooth elliptical mask, strongest across the exposed eyeball and
            # fading before the brow/cheek so a blink does not move the face.
            radial = util.smoothstep(1.0 - (nx * nx + nz * nz))
            if radial <= 0.002:
                continue
            upper = z >= close_z
            travel = 1.00 if upper else 0.90
            # Cross the two lids by a hair at full value.  Merely meeting at
            # one line leaves a bright eyeball slit after interpolation.
            target_z = close_z + (-0.080 * rz if upper else 0.080 * rz)
            w = radial * travel
            key.data[v.index].co.z = z + (target_z - z) * w
            # Put the lid seam barely in front of the sphere to prevent a thin
            # crescent of eyeball showing through at full closure.
            target_y = front_y - 0.070 * rz
            if y > target_y:
                key.data[v.index].co.y = y + (target_y - y) * radial
            moved += 1

        key.value = 0.0
        key.slider_max = 1.0
        made[name] = {"verts": moved, "centre": [cx, cy, cz],
                      "radius": [rx, rz]}
    return made


def build_visemes(obj, P, comp_of):
    me = obj.data
    A0, XC = P["A0"], P["corner_x"]
    face = P["roles"]["face"]
    band = 1.73 * A0
    _ensure_basis(obj)
    for nm in VISEMES:
        for kb in list(me.shape_keys.key_blocks):
            if kb.name == nm:
                obj.shape_key_remove(kb)
    keys = {}
    for nm in VISEMES:
        keys[nm] = obj.shape_key_add(name=nm, from_mix=False)

    n = 0
    for v in me.vertices:
        if comp_of[v.index] != face:
            continue
        x, y, z = v.co.x, v.co.y, v.co.z
        ax = abs(x)
        if ax > 1.33 * XC:
            continue
        if y > P["front_cut"] + 0.03 * P["S"]:
            continue
        sz = seam_z(P, x)
        dl = abs(z - sz)
        if dl > band:
            continue
        lp = util.smoothstep(1.0 - dl / band)
        lw = util.smoothstep(min(1.0, ax / XC))
        sgn = 1.0 if x >= 0.0 else -1.0
        rel = z - sz
        n += 1

        k = keys["mouthWide"]
        k.data[v.index].co.x = x + 0.53 * A0 * sgn * lp * lw
        k.data[v.index].co.z = z + 0.16 * A0 * lp * lw - rel * 0.22 * lp
        k.data[v.index].co.y = y + 0.13 * A0 * lp

        k = keys["mouthPucker"]
        k.data[v.index].co.x = x - 0.66 * A0 * sgn * lp * lw
        k.data[v.index].co.y = y - 0.47 * A0 * lp
        k.data[v.index].co.z = z - rel * 0.20 * lp

        k = keys["mouthFunnel"]
        k.data[v.index].co.x = x - 0.50 * A0 * sgn * lp * lw
        k.data[v.index].co.y = y - 0.35 * A0 * lp
        k.data[v.index].co.z = z + rel * 0.30 * lp

        k = keys["lipsPressed"]
        k.data[v.index].co.y = y + 0.19 * A0 * lp
        k.data[v.index].co.z = z - rel * 0.38 * lp

        k = keys["mouthFF"]
        if rel < 0.0:
            k.data[v.index].co.z = z + 0.35 * A0 * lp
            k.data[v.index].co.y = y + 0.28 * A0 * lp
        else:
            k.data[v.index].co.z = z + 0.09 * A0 * lp

    for nm in VISEMES:
        keys[nm].value = 0.0
        keys[nm].slider_max = 2.0
    return n


# ---------------------------------------------------------------- entry

def build(obj, profile, opts=None):
    o = dict(DEFAULTS)
    if opts:
        o.update(opts)
    if profile.get("mouth") is None:
        raise RuntimeError("no mouth landmarks: cannot rig this mesh")

    P = derive_params(profile, o)
    comp_of, _ = util.islands(obj.data)

    report = {}
    invaginated = profile["mouth"].get("mode") == "invaginated"
    sides = None
    if o["split_seam"]:
        face_guide = (profile.get("face_guide") or {}).get("guide")
        seam_data = None
        if face_guide:
            seam_data = ((face_guide.get("topology") or {}).get("mouth_seam") or None)
            if not seam_data:
                raise RuntimeError(
                    "guided build requires an artist-validated mouth seam")
        n = split_lip_seam(obj, P, comp_of, seam_data=seam_data)
        report["seam_split_edges"] = n
        if n:
            # indices and island ids both move; everything downstream needs the
            # fresh numbering, so re-measure rather than patch it up
            from . import measure as _measure
            # keep the ORIGINAL detection: the split itself creates boundary
            # edges at the lip line, so "auto" would now pick the wrong mode
            refreshed = _measure.measure(obj, profile["mouth"].get("mode", "auto"),
                                         profile.get("teeth_hint"))
            if face_guide:
                from . import face_guides as _face_guides
                _face_guides.apply_to_profile(refreshed, face_guide)
            # Keep the caller's profile authoritative after topology changes.
            # Downstream expression generation and verification otherwise use
            # stale component ids from before the seam split.
            profile.clear()
            profile.update(refreshed)
            P = derive_params(profile, o)
            comp_of, _ = util.islands(obj.data)
            sides = vertex_sides(obj, P)
    explicit_seam = bool(obj.get("face_rig_explicit_seam", False))
    if invaginated or explicit_seam:
        # already sealed -- see the note in split_lip_seam(); applying the seal
        # here closes the lips by the invagination depth and flattens them
        report["mouth_close_verts"] = 0
        report["mouth_close_skipped"] = (
            "artist_seam_neutral" if explicit_seam else "invaginated")
    else:
        report["mouth_close_verts"] = build_mouth_close(obj, P, comp_of)
    ao, eye_names = build_armature(obj, P, comp_of)
    report["bones"] = [b.name for b in ao.data.bones]
    report["weights"] = assign_weights(obj, ao, P, comp_of, sides)
    report["bag"] = build_mouth_bag(obj, ao, P, comp_of)
    if o["tongue"]:
        report["tongue"] = build_tongue(obj, ao, P)
    report["upper_lip_verts"] = build_upper_lip_corrective(obj, ao, P, comp_of)
    report["blinks"] = build_blinks(obj, P, comp_of)
    if o["visemes"]:
        report["viseme_verts"] = build_visemes(obj, P, comp_of)
    report["params"] = {"S": P["S"], "A0": P["A0"], "corner_x": P["corner_x"],
                        "jaw_slope": P["jaw_slope"], "pivot": P["pivot"],
                        "bag_rear_y": P["bag_rear_y"],
                        "face_fraction": P["face_fraction"],
                        "jaw_max_deg": P["jaw_max_deg"],
                        "density_scale": P["density_scale"]}
    report["armature"] = ao.name
    return report
