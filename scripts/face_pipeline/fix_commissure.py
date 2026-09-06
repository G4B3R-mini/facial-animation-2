"""Phase 4 fix: stop the mouth corners tearing under jawOpen.

    blender RIG.blend -b --python fix_commissure.py -- OUT.blend [--dry] [--diter=4]

The lip aperture is an open rim medially, but at the corners the mesh stays
continuous, so a handful of faces BRIDGE the seam - they own upper-lip and
lower-lip vertices at once. No weight assignment works for them: half the face
follows the jaw and half stays on the skull, and it stretches to 4-7x area and
flips. Anatomically the commissure should not part at all; the lips part
medially and stay pinched at the corner.

Fix: find the bridging faces by jaw-weight spread, then Laplacian-smooth the
weight field under a mask that is 1 over the commissure and 0 medially, and
converge each corner onto a single weight. The medial lip split stays sharp
because the mask is 0 there.

Two things that are load-bearing:

  * TEETH ARE EXCLUDED from the mask. Teeth are absorbed into the head mesh and
    must stay rigid (upper jaw weight exactly 0, lower exactly 1). A mouth-region
    mask silently includes them, and smoothing makes them deform. The invariant
    is asserted after the fix.
  * Shape-key deltas get LAPLACIAN smoothing only, never a pull to a per-corner
    mean. Averaging is average-destroying: it removes the tear but also removes
    the corner's net travel, so the mouth stops widening (85% loss measured).
    4 Laplacian iterations erase the jump at ~7% cost.
"""
import sys, json
from collections import defaultdict
import bpy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import pick_face, object_argument, face_armature
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
out_path = argv[0] if argv and not argv[0].startswith("--") else None
DRY = "--dry" in argv
TAG_ONLY = "--tag-teeth" in argv
DITER = int(next((a.split("=")[1] for a in argv if a.startswith("--diter=")), "4"))
ITERS, LAM = 60, 0.55
SPREAD, MIN_JUMP = 0.35, 0.25

try:
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
except Exception:
    pass

ob = pick_face(object_argument(argv))
me = ob.data
kb = me.shape_keys.key_blocks
basis = kb["Basis"].data
N = len(me.vertices)
co = [basis[i].co.copy() for i in range(N)]
S = max(c.z for c in co) - min(c.z for c in co)
A0 = 0.03 * S
R = {"head": ob.name, "verts": N}

nbr = defaultdict(set)
for p in me.polygons:
    vs = list(p.vertices)
    for k in range(len(vs)):
        a, b = vs[k], vs[(k + 1) % len(vs)]
        nbr[a].add(b)
        nbr[b].add(a)

jaw_g = ob.vertex_groups.get("jaw")
head_g = ob.vertex_groups.get("head")
if jaw_g is None:
    raise RuntimeError("no 'jaw' vertex group - is this a built rig?")
gi = jaw_g.index
w = [0.0] * N
for i, v in enumerate(me.vertices):
    for g in v.groups:
        if g.group == gi:
            w[i] = g.weight

bag = bpy.data.objects.get("mouth_bag")
if bag:
    bb = [Vector(c) for c in bag.bound_box]
    mx = max(abs(c.x) for c in bb)
    zlo, zhi = min(c.z for c in bb), max(c.z for c in bb)
    ymin, ymax = min(c.y for c in bb), max(c.y for c in bb)
else:
    mx = 0.12 * S
    zlo = min(c.z for c in co) + 0.28 * S
    zhi = min(c.z for c in co) + 0.45 * S
    ymin = min(c.y for c in co) + 0.20 * S
    ymax = ymin + 0.30 * S


def in_mouth(c):
    return (abs(c.x) <= mx * 1.30 and zlo - 0.03 <= c.z <= zhi + 0.03
            and c.y < ymin + 0.05 * S)


def in_wide(c):
    return (abs(c.x) <= mx * 1.75 and zlo - 0.06 <= c.z <= zhi + 0.06
            and c.y < ymin + 0.10 * S)


def ramp(v, lo, hi):
    if hi == lo:
        return 0.0 if v < lo else 1.0
    t = (v - lo) / (hi - lo)
    t = 0.0 if t <= 0 else (1.0 if t >= 1 else t)
    return t * t * (3.0 - 2.0 * t)


def _dominant_mat(me, ids):
    from collections import Counter
    s = set(ids)
    c = Counter(p.material_index for p in me.polygons if p.vertices[0] in s)
    return c.most_common(1)[0][0] if c else -1


def find_teeth_islands(me, comps, co, mx, zlo, zhi, ymin, ymax, S):
    """Islands that are absorbed teeth.

    Discriminating teeth from head shells is subtle and both naive rules fail:
      * centroid-in-mouth alone mistakes a large head shell for teeth whenever
        its centroid lands in the mouth, wrongly excluding real lip geometry;
      * strict bbox containment misses teeth whose arch pokes in front of the
        mouth bag (common before the teeth have been scaled down).
    Absorbed teeth come from separate objects, so they carry their own material.
    Use material as the discriminator, bounded by a size sanity check, and fall
    back to geometry if the head is single-material.
    """
    N = len(me.vertices)
    head_mat = _dominant_mat(me, comps[0])
    ext = (mx * 2.0, ymax - ymin, zhi - zlo)
    out, fallback = [], []
    for g in comps[1:]:
        if not (50 <= len(g) <= 0.25 * N):
            continue
        pts = [co[i] for i in g]
        c = sum(pts, Vector()) / len(pts)
        size = (max(p.x for p in pts) - min(p.x for p in pts),
                max(p.y for p in pts) - min(p.y for p in pts),
                max(p.z for p in pts) - min(p.z for p in pts))
        if any(size[k] > ext[k] * 1.8 for k in range(3)):
            continue
        near = (abs(c.x) <= mx * 1.5
                and zlo - 0.10 * S <= c.z <= zhi + 0.10 * S
                and ymin - 0.15 * S <= c.y <= ymax + 0.15 * S)
        if not near:
            continue
        if _dominant_mat(me, g) != head_mat:
            out.append(g)
        else:
            fallback.append(g)
    return out if out else fallback

# ---------------- teeth islands: tag them and keep them OUT of the mask
seen = set()
comps = []
for s in range(N):
    if s in seen:
        continue
    st = [s]
    seen.add(s)
    g = []
    while st:
        v = st.pop()
        g.append(v)
        for n in nbr[v]:
            if n not in seen:
                seen.add(n)
                st.append(n)
    comps.append(g)
comps.sort(key=len, reverse=True)

teeth_islands = find_teeth_islands(me, comps, co, mx, zlo, zhi, ymin, ymax, S)
teeth_islands.sort(key=lambda g: -sum(co[i].z for i in g) / len(g))
teeth_verts = set()
for g in teeth_islands:
    teeth_verts.update(g)
R["teeth_islands"] = [len(g) for g in teeth_islands]

if len(teeth_islands) >= 2:
    for name, g in (("teeth_upper", teeth_islands[0]), ("teeth_lower", teeth_islands[1])):
        vg = ob.vertex_groups.get(name) or ob.vertex_groups.new(name=name)
        vg.add(list(g), 1.0, 'REPLACE')
    R["tagged"] = ["teeth_upper", "teeth_lower"]

if TAG_ONLY:
    if out_path and not DRY:
        bpy.ops.wm.save_as_mainfile(filepath=out_path, compress=False)
    print("FIX_COMMISSURE " + json.dumps(R))
    sys.exit(0)

# ---------------- bridging faces (excluding teeth)
bridging = []
for p in me.polygons:
    vs = list(p.vertices)
    if any(v in teeth_verts for v in vs):
        continue
    c = sum((co[v] for v in vs), Vector()) / len(vs)
    if not in_mouth(c):
        continue
    if max(w[v] for v in vs) - min(w[v] for v in vs) > SPREAD:
        bridging.append(p.index)

R["n_bridging_faces"] = len(bridging)
if not bridging:
    R["result"] = "no bridging faces found - nothing to do"
    print("FIX_COMMISSURE " + json.dumps(R))
    sys.exit(0)

pts = [sum((co[v] for v in me.polygons[f].vertices), Vector()) / len(me.polygons[f].vertices)
       for f in bridging]
CL = [b for b in pts if b.x < 0]
CR = [b for b in pts if b.x >= 0]
clusters = [c for c in (CL, CR) if c]
RAD = 0.070 * S

mask = [0.0] * N
core = [0.0] * N
side = [-1] * N
for i in range(N):
    if i in teeth_verts:
        continue
    c = co[i]
    if not in_wide(c):
        continue
    bd, best = 1e18, -1
    for ci, cl in enumerate(clusters):
        d = min((c - b).length for b in cl)
        if d < bd:
            bd, best = d, ci
    side[i] = best
    mask[i] = 1.0 - ramp(bd, 0.25 * RAD, RAD)
    core[i] = 1.0 - ramp(bd, 0.05 * RAD, 0.60 * RAD)

# every vertex of a bridging face must be fully governed, even if it falls
# outside the mouth footprint - otherwise it keeps its extreme weight and tears
for f in bridging:
    vs = list(me.polygons[f].vertices)
    cxx = sum(co[v].x for v in vs) / len(vs)
    ci = 0 if (len(clusters) > 1 and cxx < 0) else len(clusters) - 1
    for v in vs:
        if v in teeth_verts:
            continue
        mask[v] = 1.0
        core[v] = max(core[v], 0.97)
        side[v] = ci
        for n in nbr[v]:
            if n in teeth_verts:
                continue
            mask[n] = max(mask[n], 0.9)
            if side[n] < 0:
                side[n] = ci
act = [i for i in range(N) if mask[i] > 0.01]
R["masked_verts"] = len(act)
R["pre_spread"] = round(max(max(w[v] for v in me.polygons[f].vertices)
                            - min(w[v] for v in me.polygons[f].vertices)
                            for f in bridging), 3)

# ---------------- weights
a = list(w)
for _ in range(ITERS):
    new = list(a)
    for i in act:
        if nbr[i]:
            new[i] = a[i] + mask[i] * LAM * (
                sum(a[j] for j in nbr[i]) / len(nbr[i]) - a[i])
    a = new
for ci in range(len(clusters)):
    idx = [i for i in act if side[i] == ci and core[i] > 0.01]
    if not idx:
        continue
    tgt = sum(a[i] * core[i] for i in idx) / sum(core[i] for i in idx)
    for i in idx:
        a[i] = a[i] * (1.0 - core[i]) + tgt * core[i]
w2 = a
R["post_spread"] = round(max(max(w2[v] for v in me.polygons[f].vertices)
                             - min(w2[v] for v in me.polygons[f].vertices)
                             for f in bridging), 3)

# ---------------- shape keys: Laplacian only, few iterations
touched = []
if not DRY:
    for k in kb:
        if k.name == "Basis":
            continue
        d = [(k.data[i].co - co[i]) for i in range(N)]
        jump = max(max(d[v].length for v in me.polygons[f].vertices)
                   - min(d[v].length for v in me.polygons[f].vertices)
                   for f in bridging)
        if jump / A0 < MIN_JUMP:
            continue
        for _ in range(DITER):
            nd = list(d)
            for i in act:
                if nbr[i]:
                    nd[i] = d[i] + mask[i] * LAM * (
                        sum((d[j] for j in nbr[i]), Vector()) / len(nbr[i]) - d[i])
            d = nd
        for i in act:
            k.data[i].co = co[i] + d[i]
        touched.append(k.name)

    for i in act:
        val = min(1.0, max(0.0, w2[i]))
        jaw_g.add([i], val, 'REPLACE')
        if head_g is not None:
            head_g.add([i], 1.0 - val, 'REPLACE')

    # ---- assert the teeth invariant (restore if anything bled through)
    if len(teeth_islands) >= 2:
        up, lo = list(teeth_islands[0]), list(teeth_islands[1])
        jaw_g.add(up, 0.0, 'REPLACE')
        jaw_g.add(lo, 1.0, 'REPLACE')
        if head_g is not None:
            head_g.add(up, 1.0, 'REPLACE')
            head_g.add(lo, 0.0, 'REPLACE')
        R["teeth_rigidity_enforced"] = True

    me.update()
    if out_path:
        bpy.ops.wm.save_as_mainfile(filepath=out_path, compress=False)
        R["saved"] = out_path

R["keys_smoothed"] = len(touched)
if out_path:
    json.dump(R, open(out_path + ".json", "w"), indent=1)
print("FIX_COMMISSURE " + json.dumps(R))
