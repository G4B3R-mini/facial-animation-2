"""Make detached islands (eyelashes, brow cards, tear lines) follow the shape
keys that deform the surface they sit on.

    blender HEAD.blend -b --python attach_lashes.py -- OUT.blend
        [--keys eyeBlinkLeft,eyeBlinkRight,...] [--radius 0.05] [--dry]

Why this exists: the expression builder works on the FACE SHELL. Eyelashes are
usually modelled as separate flat islands floating just off the lid, so nothing
ever writes blink deltas onto them and they hang in mid-air while the eye
closes. Measured on a Tripo head: the eyeBlink keys moved 100 face-shell verts
around the eyes and exactly 0 of the 146 lash verts.

Method: for every vertex of a detached island, find the nearest vertices on the
DRIVING surface that the key actually moves, and copy an inverse-distance
weighted average of their deltas. Side-correctness falls out for free -
eyeBlinkLeft only moves the left lid, so right-hand lash verts have no moved
neighbours in range and stay put.

Islands are only treated as followers when they are small and thin relative to
the driving surface, so eyeballs (round, and driven by bones) are left alone.

KNOWN LIMITATION - do not ship a result from this without looking at it.
Nearest-neighbour transfer does not know that in a blink the UPPER lid travels
far while the lower lid barely moves. On a test head the lower lash picked up
0.0325 of travel from upper-lid drivers and converged on the upper lash,
collapsing the eye into a black band. Verified the script moved only the two
lash islands (40 and 33 verts) and left brows and eyeballs alone, so the fault
is the transfer rule, not the island selection. The fix is to band the transfer
- upper lash driven only by lid verts above the eye centre, lower lash only by
those below - which is not implemented yet.
"""
import sys, json
from collections import defaultdict
import bpy
from mathutils import Vector, kdtree

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
out_path = argv[0] if argv and not argv[0].startswith("--") else None
DRY = "--dry" in argv


def arg(name, default, cast=str):
    if name in argv:
        return cast(argv[argv.index(name) + 1])
    return default


KEYS = arg("--keys", "eyeBlinkLeft,eyeBlinkRight,blink_L,blink_R,"
                     "eyeSquintLeft,eyeSquintRight,eyeWideLeft,eyeWideRight")
RADIUS = arg("--radius", 0.05, float)     # x head scale
NEIGHBOURS = arg("--neighbours", 4, int)
MAX_ISLAND = arg("--max-island", 200, int)

try:
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
except Exception:
    pass

def pick_face_mesh():
    """The face is the mesh whose shape keys actually DEFORM the most vertices.

    "Densest mesh" is not safe: separating hair by loose parts can leave the
    hair object with more vertices than the head (measured 2987 hair against
    2864 head), and the split copies all the shape keys onto both halves - so
    the hair looks like a rigged face to any vertex-count heuristic while its
    keys are entirely inert.
    """
    forced = arg("--object", None)
    if forced and forced in bpy.data.objects:
        return bpy.data.objects[forced]
    best, best_n = None, -1
    for o in bpy.data.objects:
        if o.type != 'MESH' or not o.data.shape_keys:
            continue
        kbs = o.data.shape_keys.key_blocks
        if len(kbs) <= 5:
            continue
        bz = kbs["Basis"].data
        n = 0
        for k in kbs:
            if k.name == "Basis":
                continue
            n += sum(1 for i in range(len(o.data.vertices))
                     if (k.data[i].co - bz[i].co).length > 1e-6)
        if n > best_n:
            best, best_n = o, n
    return best


ob = pick_face_mesh()
if ob is None:
    raise SystemExit("no mesh with expression shape keys found")
me = ob.data
kb = me.shape_keys.key_blocks
basis = kb["Basis"].data
N = len(me.vertices)
co = [basis[i].co.copy() for i in range(N)]
S = max(c.z for c in co) - min(c.z for c in co)
R = RADIUS * S

adj = defaultdict(set)
for p in me.polygons:
    vs = list(p.vertices)
    for k in range(len(vs)):
        a, b = vs[k], vs[(k + 1) % len(vs)]
        adj[a].add(b)
        adj[b].add(a)
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
        for n in adj[v]:
            if n not in seen:
                seen.add(n)
                st.append(n)
    comps.append(g)
comps.sort(key=len, reverse=True)
main = set(comps[0])

# Follower candidates: small islands that are FLAT. Eyeballs are round and are
# driven by the eye bones, so they must not be swept up here.
followers = []
for g in comps[1:]:
    if not (6 <= len(g) <= MAX_ISLAND):
        continue
    xs = [co[i].x for i in g]
    ys = [co[i].y for i in g]
    zs = [co[i].z for i in g]
    ext = sorted((max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)))
    if ext[2] < 1e-9:
        continue
    if ext[0] / ext[2] > 0.55:        # roughly isotropic -> not a card/lash
        continue
    followers.append(g)

report = {"head": ob.name, "islands": len(comps),
          "follower_islands": [len(g) for g in followers], "keys": {}}

if not followers:
    print("ATTACH_LASHES " + json.dumps(report))
    sys.exit(0)

follow_ids = [i for g in followers for i in g]

for name in [k.strip() for k in KEYS.split(",") if k.strip()]:
    if name not in kb:
        continue
    data = kb[name].data
    # driving verts: main-shell verts this key actually moves
    drivers = [i for i in main if (data[i].co - co[i]).length > 1e-6]
    if not drivers:
        report["keys"][name] = {"drivers": 0, "moved": 0}
        continue
    kd = kdtree.KDTree(len(drivers))
    for n, i in enumerate(drivers):
        kd.insert(co[i], n)
    kd.balance()

    moved = 0
    for vi in follow_ids:
        hits = kd.find_range(co[vi], R)
        if not hits:
            continue
        hits.sort(key=lambda h: h[2])
        hits = hits[:NEIGHBOURS]
        tot = 0.0
        acc = Vector((0.0, 0.0, 0.0))
        for _pos, idx, dist in hits:
            src = drivers[idx]
            w = 1.0 / max(dist, 1e-6)
            acc += (data[src].co - co[src]) * w
            tot += w
        if tot <= 0.0:
            continue
        if not DRY:
            data[vi].co = co[vi] + acc / tot
        moved += 1
    report["keys"][name] = {"drivers": len(drivers), "moved": moved}

if not DRY and out_path:
    me.update()
    bpy.ops.wm.save_as_mainfile(filepath=out_path)
    report["saved"] = out_path
print("ATTACH_LASHES " + json.dumps(report))
