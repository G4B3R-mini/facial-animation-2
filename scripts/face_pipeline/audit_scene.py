"""Phase 0: audit a head before rigging. Reports hazards and recommends prep.

    blender HEAD.blend -b --python audit_scene.py -- report.json

Read-only. Never modifies the scene.
"""
import sys, json
from collections import defaultdict
import bpy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import pick_face, object_argument, face_armature
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
out_path = argv[0] if argv else None

try:
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
except Exception:
    pass

R = {"meshes": [], "recommend": [], "warn": []}


def add(sev, msg):
    (R["recommend"] if sev == "prep" else R["warn"]).append(msg)


meshes = [o for o in bpy.data.objects if o.type == 'MESH']
if not meshes:
    print("AUDIT_FAIL no mesh objects")
    sys.exit(1)
head = pick_face(object_argument(argv))
meshes = [head] + [o for o in meshes if o != head]

# ---------------- materials: the QA render hazard
mat_report = []
for m in bpy.data.materials:
    has_img = False
    base = None
    if m.use_nodes:
        has_img = any(n.type == 'TEX_IMAGE' and n.image for n in m.node_tree.nodes)
        for n in m.node_tree.nodes:
            if n.type == 'BSDF_PRINCIPLED':
                base = [round(x, 3) for x in n.inputs["Base Color"].default_value[:3]]
    vp = [round(x, 3) for x in m.diffuse_color[:3]]
    mismatch = (not has_img and base is not None
                and max(abs(a - b) for a, b in zip(base, vp)) > 0.15)
    mat_report.append({"name": m.name, "image_texture": has_img,
                       "base_color": base, "viewport_color": vp,
                       "qa_colour_mismatch": mismatch})
    if mismatch:
        add("warn", "Material %s has no image texture and its viewport colour %s does "
                    "not match its base colour %s. Workbench QA will render it wrong. "
                    "qa_render.py repairs this automatically." % (m.name, vp, base))
R["materials"] = mat_report

# ---------------- per-mesh inventory
for o in meshes:
    md = o.data
    bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
    smooth = sum(1 for p in md.polygons if p.use_smooth)
    ng = sum(1 for p in md.polygons if len(p.vertices) > 4)
    R["meshes"].append({
        "name": o.name, "verts": len(md.vertices), "polys": len(md.polygons),
        "materials": [mm.name if mm else None for mm in md.materials],
        "shape_keys": len(md.shape_keys.key_blocks) if md.shape_keys else 0,
        "vertex_groups": [g.name for g in o.vertex_groups],
        "smooth_fraction": round(smooth / max(1, len(md.polygons)), 3),
        "quad_pct": round(100.0 * sum(1 for p in md.polygons if len(p.vertices) == 4)
                          / max(1, len(md.polygons)), 1),
        "tris": sum(1 for p in md.polygons if len(p.vertices) == 3),
        "ngons": ng,
        "bbox": {"x": [round(min(c.x for c in bb), 3), round(max(c.x for c in bb), 3)],
                 "y": [round(min(c.y for c in bb), 3), round(max(c.y for c in bb), 3)],
                 "z": [round(min(c.z for c in bb), 3), round(max(c.z for c in bb), 3)]},
        "parent": o.parent.name if o.parent else None})

R["head"] = head.name
me = head.data
N = len(me.vertices)

if R["meshes"][0]["smooth_fraction"] < 0.5:
    add("prep", "Head is mostly FLAT shaded (%.0f%% smooth). This reads as low-poly "
                "blockiness and is often misdiagnosed as a texture problem. Apply "
                "Shade Smooth." % (100 * R["meshes"][0]["smooth_fraction"]))
# Quad topology is the single most predictive number measured so far: heads at
# 0% quads have no edge loops at all, so nothing can run a lip loop along them.
qp = R["meshes"][0]["quad_pct"]
if qp < 40.0:
    add("prep", "Head is only %.1f%% quads (%d triangles). Triangulated meshes have no "
                "edge loops, which caps every downstream mouth/eyelid result. If this "
                "came from Tripo with quad=true, you may have imported the TRIANGULATED "
                "GLB PREVIEW instead of the quad FBX." % (qp, R["meshes"][0]["tris"]))
R["quad_pct"] = qp

if R["meshes"][0]["ngons"]:
    add("warn", "Head has %d ngons." % R["meshes"][0]["ngons"])

# ---------------- topology: islands, coincident verts, boundary
adj = defaultdict(set)
ecount = defaultdict(int)
for p in me.polygons:
    vs = list(p.vertices)
    for k in range(len(vs)):
        a, b = vs[k], vs[(k + 1) % len(vs)]
        adj[a].add(b)
        adj[b].add(a)
        ecount[tuple(sorted((a, b)))] += 1
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
boundary = set()
for e, c in ecount.items():
    if c == 1:
        boundary.update(e)
loose = [i for i in range(N) if not adj[i]]

R["islands"] = len(comps)
R["largest_island_verts"] = len(comps[0])
R["boundary_verts"] = len(boundary)
R["loose_verts"] = len(loose)

if len(comps) > 50:
    add("warn", "Head has %d shells (largest %d of %d verts). Check whether these are "
                "intentional components or coincident export splits. Use "
                "--weld-coincident only for confirmed duplicate export vertices."
                % (len(comps), len(comps[0]), N))
if loose:
    add("warn", "%d loose vertices with no faces." % len(loose))

grid = defaultdict(list)
Q = 1e-5
for i, v in enumerate(me.vertices):
    grid[(round(v.co.x / Q), round(v.co.y / Q), round(v.co.z / Q))].append(i)
dupes = sum(len(g) - 1 for g in grid.values() if len(g) > 1)
R["coincident_verts"] = dupes
if dupes:
    add("warn", "%d exactly-coincident vertices. Some may be intentional split-seam "
                "duplicates that let the lips part - do NOT merge by distance near the "
                "lip rim without checking what separates them." % dupes)

# ---------------- already rigged?
R["already_rigged"] = bool(me.shape_keys and len(me.shape_keys.key_blocks) > 5)
if R["already_rigged"]:
    add("warn", "Head already carries %d shape keys - this looks like rig OUTPUT, not a "
                "raw source. Any geometry edit must be applied to Basis AND every key "
                "block." % len(me.shape_keys.key_blocks))

# ---------------- teeth / tongue
named = {o.name.lower(): o.name for o in meshes}
found = {k: named.get(k) for k in ("upper_jaw", "lower_jaw", "tongue", "mouth_bag")}
R["teeth_tongue_objects"] = found
if not found["upper_jaw"] or not found["lower_jaw"]:
    add("prep", "No objects named upper_jaw / lower_jaw. Place and scale teeth by hand "
                "and name them so --teeth can find them. Without teeth the mouth reads "
                "as an empty cavity.")
if not found["tongue"]:
    add("prep", "No object named tongue. Place one, or pass --no-tongue.")

# ---------------- scale, orientation, aperture
zs = [v.co.z for v in me.vertices]
bbx = [v.co.x for v in me.vertices]
bby = [v.co.y for v in me.vertices]
S = max(zs) - min(zs)
R["head_scale_z"] = round(S, 4)
R["bbox_local"] = {"x": [round(min(bbx), 3), round(max(bbx), 3)],
                   "y": [round(min(bby), 3), round(max(bby), 3)],
                   "z": [round(min(zs), 3), round(max(zs), 3)]}
if abs(S - 1.0) > 0.35:
    add("warn", "Head local z-extent is %.3f. Check transforms and units; --align "
                "only shifts the midline and does not rescale the head." % S)

# Up-axis sanity. Many downloaded assets (ICT-FaceKit, most Sketchfab/glTF
# sources) are Y-up, and every mouth-region heuristic here assumes Z-up. A head
# whose Y depth clearly exceeds its Z height is the signature.
depth = max(bby) - min(bby)
if depth > S * 1.20:
    add("prep", "Y depth (%.2f) exceeds Z height (%.2f): this mesh is probably Y-UP, "
                "not Z-up. Every mouth/lip heuristic in this pipeline assumes Z-up and "
                "will target the wrong region. Rotate +90 deg about X first. Confirm by "
                "checking that the eyes sit above the mouth in +Z."
                % (depth, S))
R["y_depth"] = round(depth, 3)

front_y = min(bby)
R["front_is_negative_y"] = abs(front_y) > abs(max(bby))
if not R["front_is_negative_y"]:
    add("warn", "Head may not face -Y (crude bbox test, unreliable on off-centre "
                "heads). --align does not rotate the character; confirm visually "
                "rather than rotating on this warning alone.")

cand = [i for i in boundary
        if me.vertices[i].co.y < front_y + 0.25 * S
        and min(zs) + 0.25 * S < me.vertices[i].co.z < min(zs) + 0.55 * S]
R["lip_boundary_verts"] = len(cand)
R["mouth_mode_guess"] = "aperture" if len(cand) >= 8 else "invaginated"
if R["mouth_mode_guess"] == "invaginated":
    add("warn", "No clear boundary edge loop at the estimated lip line (%d candidate "
                "verts). An open mouth with a continuous inner cavity can also have "
                "no boundary. Inspect the visible opening and measured landmarks; "
                "do not infer that the lips are sealed or cut a seam from this alone."
                % len(cand))

# ---------------- teeth arch vs mouth width
def obj_width(name):
    o = bpy.data.objects.get(name) if name else None
    if not o:
        return None
    bb = [Vector(c) for c in o.bound_box]
    return round(max(c.x for c in bb) - min(c.x for c in bb), 4)


uw = obj_width(found["upper_jaw"])
mw = obj_width(found["mouth_bag"])
if uw and mw:
    R["teeth_arch_width"] = uw
    R["mouth_opening_width"] = mw
    if uw > mw * 1.05:
        add("prep", "Upper teeth arch (%.3f) is wider than the mouth opening (%.3f). The "
                    "arch corners will poke through the lips. Scale the teeth in X - and "
                    "if the head already has shape keys, scale across ALL key blocks, "
                    "not just Basis." % (uw, mw))

R["summary"] = {"head": head.name, "verts": N, "polys": len(me.polygons),
                "islands": len(comps), "quad_pct": R.get("quad_pct"),
                "mouth": R["mouth_mode_guess"],
                "already_rigged": R["already_rigged"],
                "n_recommend": len(R["recommend"]), "n_warn": len(R["warn"])}

if out_path:
    json.dump(R, open(out_path, "w"), indent=1)
print("AUDIT " + json.dumps(R["summary"]))
for m in R["recommend"]:
    print("  PREP: " + m)
for m in R["warn"]:
    print("  WARN: " + m)
