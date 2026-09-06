"""Copy teeth (and optionally a tongue) from a donor .blend into a head, and
park them roughly in the mouth so the user only has to nudge and scale.

    blender HEAD.blend -b --python place_teeth.py -- OUT.blend \
        --donor DONOR.blend --mouthx 0.0 --mouthy -0.25 --mouthz 0.42 --half-width 0.10 \
        [--gap 0.012] [--tongue]

Why this exists: autorig's teeth classification falls back to a size heuristic
when there are no objects named upper_jaw / lower_jaw, and it can grab the wrong
island entirely. On the blacksmith it picked a 141-vert chest button at z 0.05
and anchored the whole mouth model there - jaw bone at z 0.221, mouth bag from
z -0.003, while the real mouth is at z 0.43. Everything downstream inherited it,
and it still reported 51/52 ARKit and 10/11 gates PASS. Named teeth are not
optional.

Flags avoid --cx/--cy/--cz: Blender's own parser treats "--cy" as ambiguous
with --cycles-* even after the "--" separator.

The placement is deliberately approximate. Scale and nudge in Blender, then
re-run autorig with --teeth upper_jaw,lower_jaw.
"""
import sys
import bpy
from mathutils import Vector


def arg(name, default=None, cast=str):
    argv = sys.argv[sys.argv.index("--") + 1:]
    if name in argv:
        return cast(argv[argv.index(name) + 1])
    return default


argv = sys.argv[sys.argv.index("--") + 1:]
out_path = argv[0]
donor = arg("--donor")
CX = arg("--mouthx", 0.0, float)
CY = arg("--mouthy", None, float)
CZ = arg("--mouthz", None, float)
HALF_W = arg("--half-width", None, float)
GAP = arg("--gap", 0.012, float)          # vertical clearance between the rows
WANT_TONGUE = "--tongue" in argv
# Teeth arch should be NARROWER than the mouth opening: an arch wider than the
# aperture pokes through the lips at the corners (measured 17% too wide on the
# female head before it was scaled down).
ARCH_FRACTION = arg("--arch-fraction", 0.85, float)

if not donor or CY is None or CZ is None or HALF_W is None:
    raise SystemExit("need --donor, --mouthy, --mouthz and --half-width")

names = ["upper_jaw", "lower_jaw"] + (["tongue"] if WANT_TONGUE else [])
before = set(o.name for o in bpy.data.objects)

for nm in names:
    bpy.ops.wm.append(directory=donor.rstrip("/") + "/Object/", filename=nm,
                      link=False)

appended = [o for o in bpy.data.objects if o.name not in before]
got = {}
for o in appended:
    base = o.name.split(".")[0]
    if base in names and base not in got:
        got[base] = o
missing = [n for n in names if n not in got]
if missing:
    raise SystemExit("donor did not provide: %s (has: %s)"
                     % (missing, [o.name for o in appended]))

report = {}
for nm, o in got.items():
    o.name = nm
    # clear any donor parenting/animation so the transform below is absolute
    o.parent = None
    o.animation_data_clear()
    bpy.context.view_layer.objects.active = o
    for ob2 in bpy.data.objects:
        ob2.select_set(False)
    o.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    vs = [v.co for v in o.data.vertices]
    xs = [p.x for p in vs]
    ys = [p.y for p in vs]
    zs = [p.z for p in vs]
    w = max(xs) - min(xs)
    target_w = 2.0 * HALF_W * ARCH_FRACTION
    s = target_w / max(w, 1e-9)

    # scale about the object's own centre, then move that centre into the mouth
    cx0 = 0.5 * (min(xs) + max(xs))
    cy0 = 0.5 * (min(ys) + max(ys))
    cz0 = 0.5 * (min(zs) + max(zs))
    for v in o.data.vertices:
        v.co = Vector((cx0 + (v.co.x - cx0) * s,
                       cy0 + (v.co.y - cy0) * s,
                       cz0 + (v.co.z - cz0) * s))

    vs = [v.co for v in o.data.vertices]
    zs = [p.z for p in vs]
    ys = [p.y for p in vs]
    xs = [p.x for p in vs]
    h = max(zs) - min(zs)
    if nm == "upper_jaw":
        # biting edge (bottom of the row) sits just above the seam
        dz = (CZ + GAP) - min(zs)
    elif nm == "lower_jaw":
        dz = (CZ - GAP) - max(zs)
    else:
        dz = (CZ - GAP * 1.5) - max(zs)
    dx = CX - 0.5 * (min(xs) + max(xs))
    # park the front of the row just behind the lip plane
    dy = (CY + 0.010) - min(ys)
    for v in o.data.vertices:
        v.co += Vector((dx, dy, dz))

    vs = [v.co for v in o.data.vertices]
    report[nm] = {
        "verts": len(o.data.vertices), "scale": round(s, 4),
        "x": [round(min(p.x for p in vs), 4), round(max(p.x for p in vs), 4)],
        "y": [round(min(p.y for p in vs), 4), round(max(p.y for p in vs), 4)],
        "z": [round(min(p.z for p in vs), 4), round(max(p.z for p in vs), 4)]}
    o.data.update()

bpy.ops.wm.save_as_mainfile(filepath=out_path)
import json
print("PLACE_TEETH " + json.dumps({"saved": out_path, "placed": report,
                                   "target": {"mouthx": CX, "mouthy": CY, "mouthz": CZ,
                                              "half_width": HALF_W}}))
