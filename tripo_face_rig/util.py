"""Shared helpers. No Blender-version-specific API outside of compat shims."""
import bmesh


def smoothstep(t):
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * (3.0 - 2.0 * t)


def ramp(v, lo, hi):
    """0 at lo, 1 at hi, smoothstepped. Works for lo > hi (descending)."""
    if hi == lo:
        return 0.0 if v < lo else 1.0
    return smoothstep((v - lo) / (hi - lo))


def islands(mesh):
    """Connected components. Returns (comp_of, groups) keyed by vertex index."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    comp_of = {}
    cid = 0
    for v in bm.verts:
        if v.index in comp_of:
            continue
        stack = [v]
        comp_of[v.index] = cid
        while stack:
            cur = stack.pop()
            for e in cur.link_edges:
                o = e.other_vert(cur)
                if o.index not in comp_of:
                    comp_of[o.index] = cid
                    stack.append(o)
        cid += 1
    bm.free()
    groups = {}
    for vi, c in comp_of.items():
        groups.setdefault(c, []).append(vi)
    return comp_of, groups


def bbox(mesh, indices):
    xs = []
    ys = []
    zs = []
    for i in indices:
        co = mesh.vertices[i].co
        xs.append(co.x)
        ys.append(co.y)
        zs.append(co.z)
    return {"x": [min(xs), max(xs)], "y": [min(ys), max(ys)], "z": [min(zs), max(zs)]}


def centre(bb):
    return [(bb["x"][0] + bb["x"][1]) * 0.5,
            (bb["y"][0] + bb["y"][1]) * 0.5,
            (bb["z"][0] + bb["z"][1]) * 0.5]


def self_symmetry(mesh, indices, tol):
    """Fraction of verts in this shell having a mirrored partner within the shell."""
    from mathutils.kdtree import KDTree
    n = len(indices)
    if n == 0:
        return 0.0
    kd = KDTree(n)
    for k, i in enumerate(indices):
        kd.insert(mesh.vertices[i].co, k)
    kd.balance()
    hit = 0
    for i in indices:
        co = mesh.vertices[i].co
        _, _, d = kd.find((-co.x, co.y, co.z))
        if d is not None and d < tol:
            hit += 1
    return hit / float(n)


def crosses_midline(bb):
    return bb["x"][0] < 0.0 < bb["x"][1]


def mirror_pairs(mesh, groups, tol_frac=0.12):
    """Find shells that are mirror images of each other across x=0."""
    ids = sorted(groups.keys())
    boxes = {c: bbox(mesh, groups[c]) for c in ids}
    used = set()
    pairs = []
    for a in ids:
        if a in used or crosses_midline(boxes[a]):
            continue
        ba = boxes[a]
        for b in ids:
            if b == a or b in used or crosses_midline(boxes[b]):
                continue
            if abs(len(groups[a]) - len(groups[b])) > max(4, 0.15 * len(groups[a])):
                continue
            bb2 = boxes[b]
            span = max(1e-6, ba["z"][1] - ba["z"][0])
            dz = abs(ba["z"][0] - bb2["z"][0]) + abs(ba["z"][1] - bb2["z"][1])
            dy = abs(ba["y"][0] - bb2["y"][0]) + abs(ba["y"][1] - bb2["y"][1])
            dx = abs(ba["x"][0] + bb2["x"][1]) + abs(ba["x"][1] + bb2["x"][0])
            if (dz + dy + dx) < tol_frac * span * 6.0:
                pairs.append((a, b))
                used.add(a)
                used.add(b)
                break
    return pairs


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


def remove_fcurve(action, fcurve):
    """Delete one fcurve, on either the legacy or the layered action API."""
    fcs = getattr(action, "fcurves", None)
    if fcs is not None:
        try:
            fcs.remove(fcurve)
            return True
        except Exception:
            return False
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for cb in getattr(strip, "channelbags", []):
                if fcurve in list(cb.fcurves):
                    try:
                        cb.fcurves.remove(fcurve)
                        return True
                    except Exception:
                        return False
    return False


def clear_action(id_data):
    import bpy
    ad = getattr(id_data, "animation_data", None)
    if ad and ad.action:
        act = ad.action
        # An action is not the whole animation-data block. Keep corrective
        # drivers (including the resting lip seal) when replacing a voice take.
        ad.action = None
        if act.users == 0:
            bpy.data.actions.remove(act)
