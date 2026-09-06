"""Phase 3: objective diagnosis of a built face rig.

    blender RIG.blend -b --python diagnose_rig.py -- diag.json [--step 2]

Ground truth is the per-face area blow-up of the REAL evaluated mesh (armature
+ shape keys together) versus rest. A shape key evaluated alone under-reports
badly. Read-only.

See references/diagnostics.md for thresholds and how to map centroids to regions.
"""
import sys, json, math
from collections import defaultdict
import bpy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import pick_face, object_argument, face_armature
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
out_path = argv[0] if argv else None
step = 2
if "--step" in argv:
    step = int(argv[argv.index("--step") + 1])

try:
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
except Exception:
    pass

ob = pick_face(object_argument(argv))
me = ob.data
kb = me.shape_keys.key_blocks if me.shape_keys else None
arm = face_armature(ob)
sc = bpy.context.scene
D = {"head": ob.name, "verts": len(me.vertices), "polys": len(me.polygons),
     "shape_keys": len(kb) if kb else 0, "armature": arm.name if arm else None}

basis = kb["Basis"].data if kb else me.vertices
co = [basis[i].co.copy() for i in range(len(me.vertices))]
S = max(c.z for c in co) - min(c.z for c in co)


def centroid(fi):
    p = me.polygons[fi]
    return [round(q, 4) for q in
            (sum((co[v] for v in p.vertices), Vector()) / len(p.vertices))]


def areas():
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    m = ev.to_mesh()
    a = [p.area for p in m.polygons]
    ev.to_mesh_clear()
    return a


saved_frame = sc.frame_current
saved_keys = {k.name: k.value for k in kb} if kb else {}
saved_pose = {pb.name: pb.matrix_basis.copy() for pb in arm.pose.bones} if arm else {}

# ---- rest
if kb:
    for k in kb:
        k.value = 0.0
if arm:
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()
bpy.context.view_layer.update()
rest = areas()

# ---- sweep the animation if there is one, else a synthetic pose set
has_anim = bool(
    (arm and arm.animation_data and arm.animation_data.action)
    or (me.shape_keys and me.shape_keys.animation_data
        and me.shape_keys.animation_data.action))
agg = {}
jerk = {}
prev = None
if has_anim:
    D["driver"] = "animation frames %d-%d step %d" % (sc.frame_start, sc.frame_end, step)
    for f in range(sc.frame_start, sc.frame_end + 1, step):
        sc.frame_set(f)
        bpy.context.view_layer.update()
        a = areas()
        r = [a[i] / rest[i] if rest[i] > 1e-12 else 0.0 for i in range(len(rest))]
        for i, x in enumerate(r):
            if x > agg.get(i, 0):
                agg[i] = x
            if prev is not None:
                j = abs(x - prev[i])
                if j > jerk.get(i, 0):
                    jerk[i] = j
        prev = r
else:
    POSES = ["jawOpen", "mouthClose", "vrc.v_aa", "vrc.v_O", "vrc.v_E",
             "mouthSmileLeft", "mouthSmileRight", "mouthPucker", "mouthFunnel"]
    used = [p for p in POSES if kb and p in kb]
    D["driver"] = "synthetic pose set: %s" % ", ".join(used)
    for name in used:
        for val in (0.5, 1.0):
            for k in kb:
                k.value = 0.0
            kb[name].value = val
            bpy.context.view_layer.update()
            a = areas()
            r = [a[i] / rest[i] if rest[i] > 1e-12 else 0.0 for i in range(len(rest))]
            for i, x in enumerate(r):
                if x > agg.get(i, 0):
                    agg[i] = x
    # Basic rigs may have no jawOpen shape key. Exercise their actual jaw too.
    if arm and 'jaw' in arm.pose.bones:
        jaw = arm.pose.bones['jaw']
        mode = jaw.rotation_mode
        jaw.rotation_mode = 'XYZ'
        D['jaw_test_degrees'] = [9, 18]
        D['jaw_limit_degrees'] = [math.degrees(c.max_x) for c in jaw.constraints
                                 if c.type == 'LIMIT_ROTATION' and c.use_limit_x]
        for deg in D['jaw_test_degrees']:
            if kb:
                for k in kb:
                    k.value = 0.0
            jaw.rotation_euler = (math.radians(deg), 0, 0)
            bpy.context.view_layer.update()
            a = areas()
            for i in range(len(rest)):
                ratio = a[i] / rest[i] if rest[i] > 1e-12 else 0.0
                agg[i] = max(agg.get(i, 0), ratio)
        jaw.rotation_mode = mode

top = sorted(agg.items(), key=lambda kv: -kv[1])[:15]
D["max_area_ratio"] = round(max(agg.values()), 2) if agg else 0.0
D["n_over_2p6x"] = sum(1 for v in agg.values() if v > 2.6)
D["n_over_3x"] = sum(1 for v in agg.values() if v > 3.0)
D["worst_faces"] = [{"face": i, "ratio": round(v, 2), "at": centroid(i)} for i, v in top]
if jerk:
    jt = sorted(jerk.items(), key=lambda kv: -kv[1])[:8]
    D["max_jerk"] = round(max(jerk.values()), 3)
    D["worst_jerk"] = [{"face": i, "jerk": round(v, 3), "at": centroid(i)} for i, v in jt]

# ---- neutral must be untouched
sc.frame_set(sc.frame_start)
if kb:
    for k in kb:
        k.value = 0.0
if arm:
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()
bpy.context.view_layer.update()
a = areas()
D["neutral_max_ratio"] = round(max(
    (a[i] / rest[i] if rest[i] > 1e-12 else 0.0) for i in range(len(rest))), 3)

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

# ---- mouth-region jaw weight spread (explains commissure tears)
jg = ob.vertex_groups.get("jaw")
if jg:
    gi = jg.index
    w = [0.0] * len(me.vertices)
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

    # Teeth islands must be excluded from mouth-region face scans: they are rigid
    # by design, and their centroids sit BEHIND the lip line, so a frontal test
    # like in_mouth() misses them. Use the mouth-bag volume instead.
    adj2 = defaultdict(set)
    for p2 in me.polygons:
        vv = list(p2.vertices)
        for k2 in range(len(vv)):
            aa, bv = vv[k2], vv[(k2 + 1) % len(vv)]
            adj2[aa].add(bv)
            adj2[bv].add(aa)
    seen2 = set()
    comps2 = []
    for s2 in range(len(me.vertices)):
        if s2 in seen2:
            continue
        st2 = [s2]
        seen2.add(s2)
        g2 = []
        while st2:
            v2 = st2.pop()
            g2.append(v2)
            for n2 in adj2[v2]:
                if n2 not in seen2:
                    seen2.add(n2)
                    st2.append(n2)
        comps2.append(g2)
    comps2.sort(key=len, reverse=True)
    teeth_verts = set()
    for g2 in find_teeth_islands(me, comps2, co, mx, zlo, zhi, ymin, ymax, S):
        teeth_verts.update(g2)
    D["teeth_island_verts"] = len(teeth_verts)

    def in_mouth(c):
        return (abs(c.x) <= mx * 1.30 and zlo - 0.03 <= c.z <= zhi + 0.03
                and c.y < ymin + 0.05 * S)

    bridging = []
    for p in me.polygons:
        vs = list(p.vertices)
        if any(v in teeth_verts for v in vs):
            continue
        c = sum((co[v] for v in vs), Vector()) / len(vs)
        if not in_mouth(c):
            continue
        s = max(w[v] for v in vs) - min(w[v] for v in vs)
        if s > 0.35:
            bridging.append({"face": p.index, "spread": round(s, 3),
                             "at": [round(q, 4) for q in c]})
    D["mouth_weight_spread"] = round(max([b["spread"] for b in bridging], default=0.0), 3)
    D["commissure_bridging_faces"] = len(bridging)
    D["bridging_detail"] = sorted(bridging, key=lambda b: -b["spread"])[:10]

    # ---- teeth rigidity invariant
    teeth = {}
    for nm in ("teeth_upper", "teeth_lower"):
        g = ob.vertex_groups.get(nm)
        if not g:
            continue
        tgi = g.index
        ids = [v.index for v in me.vertices
               if any(gg.group == tgi and gg.weight > 0.5 for gg in v.groups)]
        if not ids:
            continue
        jw = [w[i] for i in ids]
        teeth[nm] = {"n": len(ids), "jaw_min": round(min(jw), 3),
                     "jaw_max": round(max(jw), 3),
                     "n_partial": sum(1 for x in jw if 0.05 < x < 0.95)}
    if teeth:
        D["teeth"] = teeth
        ok = True
        if "teeth_upper" in teeth:
            ok &= teeth["teeth_upper"]["jaw_max"] < 0.02
        if "teeth_lower" in teeth:
            ok &= teeth["teeth_lower"]["jaw_min"] > 0.98
        D["teeth_rigid"] = bool(ok)
    else:
        D["teeth_rigid"] = None
        D["teeth_note"] = ("no teeth_upper/teeth_lower vertex groups; run "
                           "fix_commissure.py --tag-teeth to create them")

# ---- restore
sc.frame_set(saved_frame)
if arm:
    for pb in arm.pose.bones:
        if pb.name in saved_pose:
            pb.matrix_basis = saved_pose[pb.name]
if kb:
    for k in kb:
        if k.name in saved_keys:
            k.value = saved_keys[k.name]
bpy.context.view_layer.update()

verdict = []
if D["n_over_2p6x"]:
    verdict.append("%d face(s) tear (>2.6x)" % D["n_over_2p6x"])
if D.get("max_jerk", 0) > 1.5:
    verdict.append("visible popping (jerk %.2f)" % D["max_jerk"])
# weight spread is a PROXY and over-reports: only call it a defect when the
# ground-truth area test agrees that something actually tears or pops.
if D.get("commissure_bridging_faces") and (D["n_over_2p6x"] or D.get("max_jerk", 0) > 1.5):
    verdict.append("%d commissure bridging face(s), spread %.2f - run fix_commissure.py"
                   % (D["commissure_bridging_faces"], D["mouth_weight_spread"]))
elif D.get("commissure_bridging_faces"):
    D["note_bridging"] = ("%d face(s) carry jaw-weight spread %.2f but nothing tears; "
                          "informational only, do not 'fix' this"
                          % (D["commissure_bridging_faces"], D["mouth_weight_spread"]))
if D.get("teeth_rigid") is False:
    verdict.append("teeth are NOT rigid - they will deform")
if abs(D["neutral_max_ratio"] - 1.0) > 0.02:
    verdict.append("neutral pose moved (%.3f)" % D["neutral_max_ratio"])
D["verdict"] = verdict or ["no structural defects detected - now LOOK at the renders"]

if out_path:
    json.dump(D, open(out_path, "w"), indent=1)
print("DIAG " + json.dumps({k: D[k] for k in (
    "max_area_ratio", "n_over_2p6x", "n_over_3x", "neutral_max_ratio") if k in D}))
for v in D["verdict"]:
    print("  - " + v)
