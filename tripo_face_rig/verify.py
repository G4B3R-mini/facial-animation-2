"""Stage 3: automated gates.

Each of these corresponds to a bug that actually shipped during the manual
build of this rig. They are cheap; run them after every build.

Note on gate 2: check ALL teeth vertices. An earlier version filtered to
y < -0.20 and silently missed the corner teeth, reporting 3 exposed when
the render clearly showed large gaps. A verification metric with its own
hidden filter is worse than no metric.
"""
import math
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from . import util
from .build import seam_z, seam_y, jaw_weight, derive_params


def _eval_mesh(obj, dg):
    oe = obj.evaluated_get(dg)
    return oe, oe.to_mesh()


def _face_bvh(obj, dg, comp_of, face_id):
    oe, mv = _eval_mesh(obj, dg)
    verts = [v.co.copy() for v in mv.vertices]
    faces = [list(p.vertices) for p in mv.polygons
             if comp_of.get(p.vertices[0]) == face_id]
    bvh = BVHTree.FromPolygons(verts, faces, all_triangles=False, epsilon=0.0)
    oe.to_mesh_clear()
    return bvh


def mouth_region(profile):
    """Predicate: is this point in the lip band that split_lip_seam cuts?

    Used so the no_new_holes gate can still catch accidental holes even when
    the lip seam has been opened deliberately.
    """
    m = profile.get("mouth")
    if m is None:
        return lambda co: False
    XC = m["corner_x"]
    a, b = m["seam_z"]
    fc = m["front_cut"]

    def inside(co):
        return (abs(co.x) <= 1.30 * XC and co.y < fc
                and abs(co.z - (a + b * co.x * co.x)) < 0.09)
    return inside


def boundary_edges(mesh, skip_region=None):
    """Count boundary edges. skip_region(co) -> True excludes an edge."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(mesh)
    n = 0
    for e in bm.edges:
        if len(e.link_faces) != 1:
            continue
        if skip_region is not None and any(skip_region(v.co) for v in e.verts):
            continue
        n += 1
    bm.free()
    return n


def teeth_exposure_baseline(obj, profile):
    """Teeth exposure on the UNRIGGED mesh, using the SAME sampling as the gate.

    'Always pass' is not an acceptable relaxation for an invaginated mouth: it
    let a build through where subdividing the head shrank it enough for the
    teeth to spike through the lips at rest. The rest pose is the artist's, so
    the gate compares against the INPUT rather than against zero -- but only if
    both sides count the same samples. Centres-only against centres+vertices+
    interiors is not a comparison, it is a unit error.
    """
    comp_of, _ = util.islands(obj.data)
    return gate_teeth_hidden(obj, None, profile, comp_of, 0.0)["exposed"]


def teeth_through_skin(obj, profile):
    """Teeth that have PIERCED the lip, as opposed to being seen through it.

    Comparing against the fitted seam_y does not work: that curve recedes
    steeply at the commissures (b = +10.6 on the test head), so it excludes the
    very region where teeth punch through, and the metric read 0 on a visibly
    broken mesh. The discriminator that works: a pierced tooth has skin close
    BEHIND it, because it came through that skin. A tooth seen through an open
    mouth has only cavity behind it.
    """
    comp_of, _ = util.islands(obj.data)
    roles = profile["roles"]
    teeth = set(roles.get("teeth_upper_all") or [roles["teeth_upper"]])
    teeth.update(roles.get("teeth_lower_all") or [roles["teeth_lower"]])
    teeth.discard(None)
    near = 0.035 * profile["scale"]
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    bvh = _face_bvh(obj, dg, comp_of, roles["face"])
    oe, mv = _eval_mesh(obj, dg)
    n = 0
    for p in mv.polygons:
        c = comp_of.get(p.vertices[0])
        if c not in teeth:
            continue
        cen = p.center.copy()
        if bvh.ray_cast(Vector((cen.x, cen.y - 0.0004, cen.z)),
                        Vector((0.0, -1.0, 0.0)), 0.6)[0] is not None:
            continue                       # skin in front: covered, fine
        hit = bvh.ray_cast(Vector((cen.x, cen.y + 0.0004, cen.z)),
                           Vector((0.0, 1.0, 0.0)), near)
        if hit[0] is not None:
            n += 1                         # skin just behind: it pierced it
    oe.to_mesh_clear()
    return n


def gate_teeth_hidden(obj, ao, profile, comp_of, jaw_deg=0.0):
    """At rest no tooth may be visible; opened, teeth must become visible."""
    roles = profile["roles"]
    teeth = set(roles.get("teeth_upper_all") or [roles["teeth_upper"]])
    teeth.update(roles.get("teeth_lower_all") or [roles["teeth_lower"]])
    teeth.discard(None)
    pb = ao.pose.bones["jaw"] if ao is not None else None
    if pb is not None:
        pb.rotation_euler = (math.radians(jaw_deg), 0.0, 0.0)
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    bvh = _face_bvh(obj, dg, comp_of, roles["face"])
    oe, mv = _eval_mesh(obj, dg)

    # Sample vertices AND polygon interiors. A vertex-only test reported
    # 1 exposed while the render showed obvious gaps at both commissures:
    # the holes fell between vertices.
    samples = []
    for v in mv.vertices:
        c = comp_of.get(v.index)
        if c in teeth:
            samples.append((v.co.copy(), v.co.x))
    for p in mv.polygons:
        c = comp_of.get(p.vertices[0])
        if c not in teeth:
            continue
        cen = p.center.copy()
        samples.append((cen, cen.x))
        for vi in p.vertices:
            samples.append((cen.lerp(mv.vertices[vi].co, 0.55), cen.x))

    exposed = 0
    worst = None
    for co, _ in samples:
        org = Vector((co.x, co.y - 0.0004, co.z))
        if bvh.ray_cast(org, Vector((0.0, -1.0, 0.0)), 0.6)[0] is None:
            exposed += 1
            if worst is None or abs(co.x) > abs(worst[0]):
                worst = (co.x, co.y, co.z)
    oe.to_mesh_clear()
    if pb is not None:
        pb.rotation_euler = (0.0, 0.0, 0.0)
    out = {"samples": len(samples), "exposed": exposed}
    if worst is not None:
        out["outermost"] = [round(v, 4) for v in worst]
    return out


def gate_bag_contained(obj, ao, profile, comp_of, bag_name="mouth_bag"):
    bag = bpy.data.objects.get(bag_name)
    if bag is None:
        return {"skipped": True}
    ao.pose.bones["jaw"].rotation_euler = (0.0, 0.0, 0.0)
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    bvh = _face_bvh(obj, dg, comp_of, profile["roles"]["face"])
    be, bmv = _eval_mesh(bag, dg)
    m = profile["mouth"]
    sy_a, sy_b = m["seam_y"]
    poke = 0
    for v in bmv.vertices:
        if bvh.ray_cast(Vector(v.co), Vector((0.0, -1.0, 0.0)), 0.6)[0] is None:
            # "no face in front" also describes a vertex seen THROUGH an open
            # mouth, which is the bag doing its job. Only count it as poking
            # through if it is in front of the lip line.
            if v.co.y < (sy_a + sy_b * v.co.x * v.co.x):
                poke += 1
    total = len(bmv.vertices)
    be.to_mesh_clear()
    return {"bag_verts": total, "poking_out": poke}


def gate_lips_sealed(obj, ao, profile, comp_of, jaw_deg=0.0):
    """Residual aperture at the midline after mouthClose."""
    if comp_of is None:
        comp_of, _ = util.islands(obj.data)
    if ao is not None:
        ao.pose.bones["jaw"].rotation_euler = (math.radians(jaw_deg), 0.0, 0.0)
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    oe, mv = _eval_mesh(obj, dg)
    m = profile["mouth"]
    occl = m["occlusion_z"]
    S = profile["scale"]
    face = profile["roles"]["face"]
    win = 0.008 * S
    cand = []
    for v in mv.vertices:
        if comp_of.get(v.index) != face:
            continue
        if abs(v.co.x) > win:
            continue
        if abs(v.co.z - occl) > 0.09 * S:
            continue
        if v.co.y > m["front_cut"]:
            continue
        cand.append(v.co.z)
    oe.to_mesh_clear()
    if ao is not None:
        ao.pose.bones["jaw"].rotation_euler = (0.0, 0.0, 0.0)
    cand.sort()
    gap = 0.0
    for i in range(len(cand) - 1):
        a, b = cand[i], cand[i + 1]
        if a <= occl <= b and (b - a) > gap:
            gap = b - a
    return {"residual_aperture": gap, "as_fraction_of_original": (
        gap / m["aperture_centre"] if m["aperture_centre"] else None)}


def gate_weights(obj, profile, opts=None):
    """The five probes that catch the basis-coords trap and the frozen chin."""
    from .build import DEFAULTS
    o = dict(DEFAULTS)
    if opts:
        o.update(opts)
    P = derive_params(profile, o)
    S = P["S"]
    sz0 = seam_z(P, 0.0)
    sy0 = seam_y(P, 0.0)
    A0 = P["A0"]

    probes = {
        "upper_lip": (0.0, sy0, sz0 + 0.55 * A0),
        "lower_lip": (0.0, sy0, sz0 - 0.55 * A0),
        "chin":      (0.0, sy0 + 0.01 * S, sz0 - 0.16 * S),
        "chin_low":  (0.0, sy0 + 0.02 * S, sz0 - 0.24 * S),
        "neck":      (0.0, sy0 + 0.19 * S, sz0 - 0.30 * S),
        "nape":      (0.0, 0.11 * S, sz0 - 0.20 * S),
    }
    out = {}
    for k, (x, y, z) in probes.items():
        out[k] = round(jaw_weight(P, x, y, z), 3)

    # corner gradient along the lower lip must not increase outboard
    grad = []
    steps = 7
    for i in range(steps):
        x = P["corner_x"] * i / float(steps - 1)
        grad.append(round(jaw_weight(P, x, sy0, seam_z(P, x) - 0.5 * A0), 3))
    monotonic = all(grad[i + 1] <= grad[i] + 0.02 for i in range(len(grad) - 1))
    out["corner_gradient"] = grad
    out["corner_monotonic"] = monotonic
    return out


def verify(obj, ao, profile, baseline_boundary=None, open_deg=18.0, opts=None,
           baseline_teeth=0, baseline_lips=None):
    comp_of, _ = util.islands(obj.data)
    res = {}
    res["lips_sealed"] = gate_lips_sealed(obj, ao, profile, comp_of)
    res["lips_when_open"] = gate_lips_sealed(obj, ao, profile, comp_of, open_deg)
    res["teeth_at_rest"] = gate_teeth_hidden(obj, ao, profile, comp_of, 0.0)
    res["teeth_when_open"] = gate_teeth_hidden(obj, ao, profile, comp_of, open_deg)
    res["bag"] = gate_bag_contained(obj, ao, profile, comp_of)
    res["weights"] = gate_weights(obj, profile, opts)
    skip = mouth_region(profile) if (opts or {}).get("split_seam") else None
    nb = boundary_edges(obj.data, skip)
    res["boundary_edges"] = {"count": nb, "baseline": baseline_boundary,
                             "unchanged": (baseline_boundary is None or nb == baseline_boundary)}

    A0 = profile["mouth"]["aperture_centre"]
    w = res["weights"]
    invaginated = profile["mouth"].get("mode") == "invaginated"
    face_id = profile["roles"]["face"]
    face_info = profile.get("shells", {}).get(str(face_id), {})
    face_fraction = face_info.get("verts", 0) / max(profile.get("verts", 1), 1)
    fused_face = face_fraction > 0.45
    # On an invaginated mouth the rest pose is the artist's: the lips are
    # already sealed, mouth_close is skipped, and a mouth modelled slightly
    # open legitimately shows teeth at rest. Demanding zero there would force
    # a seal that flattens the lips. What still matters is that opening the
    # jaw reveals MORE than rest -- i.e. the mouth actually opens.
    checks = {
        "lips_sealed": (
            res["lips_sealed"]["residual_aperture"]
            <= max(0.20 * A0,
                   1.05 * baseline_lips["residual_aperture"])
            if invaginated and baseline_lips else
            res["lips_sealed"]["residual_aperture"] < 0.20 * A0),
        "teeth_hidden_at_rest": (
            res["teeth_at_rest"]["exposed"] <= max(4, int(1.35 * baseline_teeth))
            if invaginated else res["teeth_at_rest"]["exposed"] == 0),
        # Direct evidence wins. If teeth are actually exposed when the mouth
        # opens, that is exactly what this gate asks and no proxy should
        # override it. The fused_face branch is a fallback for heads whose teeth
        # never show at all, and its residual_aperture proxy COLLAPSES TO ZERO
        # once the mouth genuinely opens (the rim search stops locating the
        # lips) - so it reported a failure on a rig that had just improved from
        # 0 to 115 exposed teeth samples.
        "teeth_visible_when_open": (
            res["teeth_when_open"]["exposed"] > res["teeth_at_rest"]["exposed"]
            if res["teeth_when_open"]["exposed"] > 0 else
            res["lips_when_open"]["residual_aperture"]
            > res["lips_sealed"]["residual_aperture"] + 0.002 * profile["scale"]
            if fused_face else
            res["teeth_when_open"]["exposed"] > res["teeth_at_rest"]["exposed"]
            if invaginated else res["teeth_when_open"]["exposed"] > 0),
        "bag_contained": res["bag"].get("poking_out", 0) == 0,
        "upper_lip_free": w["upper_lip"] <= 0.10,
        "lower_lip_driven": w["lower_lip"] >= 0.85,
        "chin_driven": w["chin"] >= 0.85 and w["chin_low"] >= 0.60,
        "neck_free": w["neck"] <= 0.15,
        "nape_free": w["nape"] <= 0.15,
        "corner_monotonic": w["corner_monotonic"],
        "no_new_holes": res["boundary_edges"]["unchanged"],
    }
    res["checks"] = checks
    res["passed"] = all(checks.values())
    res["failed"] = [k for k, v in checks.items() if not v]
    return res
