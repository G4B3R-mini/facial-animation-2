"""Phase 5: honest QA renders.

    blender RIG.blend -b --python qa_render.py -- out_dir [--tag NAME] [--closeup]

Renders a pose set at BUST distance (the judgment view - what the player sees)
and optionally a mouth closeup. Build the contact sheet afterwards with
make_sheet.py, which runs outside Blender.

Before rendering it repairs the QA-only material hazard: Workbench TEXTURE mode
falls back to a material's viewport display colour when the material has no
image texture, so an untextured dark mouth interior renders as a bright grey
slab and reads as a catastrophic defect. See references/traps.md.
"""
import sys, os, math, json
import bpy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import pick_face, object_argument, face_armature
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
out_dir = os.path.abspath(argv[0])
tag = argv[argv.index("--tag") + 1] if "--tag" in argv else "qa"
closeup = "--closeup" in argv
os.makedirs(out_dir, exist_ok=True)

try:
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
except Exception:
    pass

# ---------------- repair viewport colours (QA correctness, not a rig change)
repaired = []
for m in bpy.data.materials:
    if not m.use_nodes:
        continue
    if any(n.type == 'TEX_IMAGE' and n.image for n in m.node_tree.nodes):
        continue
    bsdf = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if not bsdf:
        continue
    bc = list(bsdf.inputs["Base Color"].default_value)
    vp = list(m.diffuse_color)
    if max(abs(a - b) for a, b in zip(bc[:3], vp[:3])) > 0.02:
        m.diffuse_color = (bc[0], bc[1], bc[2], 1.0)
        repaired.append(m.name)

ob = pick_face(object_argument(argv))
kb = ob.data.shape_keys.key_blocks if ob.data.shape_keys else None
arm = face_armature(ob)
sc = bpy.context.scene

sc.render.engine = 'BLENDER_WORKBENCH'
sc.display.shading.light = 'FLAT'
sc.display.shading.color_type = 'TEXTURE'
sc.display.shading.show_shadows = False
sc.render.image_settings.file_format = 'PNG'

mw = ob.matrix_world
pts = [mw @ v.co for v in ob.data.vertices]
xs = [p.x for p in pts]
ys = [p.y for p in pts]
zs = [p.z for p in pts]
cx = 0.5 * (min(xs) + max(xs))
cy = 0.5 * (min(ys) + max(ys))
bust_span = max(max(xs) - min(xs), max(zs) - min(zs)) * 1.02
bust_cz = 0.5 * (min(zs) + max(zs))

# closeup framing from the mouth bag if present, else the lower-front third
bag = bpy.data.objects.get("mouth_bag")
if bag:
    bb = [bag.matrix_world @ Vector(c) for c in bag.bound_box]
    m_cx = 0.5 * (min(c.x for c in bb) + max(c.x for c in bb))
    m_cz = 0.5 * (min(c.z for c in bb) + max(c.z for c in bb))
    m_span = (max(c.x for c in bb) - min(c.x for c in bb)) * 2.0
else:
    m_cx = cx
    m_cz = min(zs) + 0.36 * (max(zs) - min(zs))
    m_span = (max(xs) - min(xs)) * 0.45

cam_data = bpy.data.cameras.new("QA")
cam_data.type = 'ORTHO'
cam = bpy.data.objects.new("QA", cam_data)
sc.collection.objects.link(cam)
sc.camera = cam


def shot(kind):
    if kind == "bust":
        cam_data.ortho_scale = bust_span
        cam.location = (cx, min(ys) - 3.0, bust_cz)
    else:
        cam_data.ortho_scale = m_span
        cam.location = (m_cx, min(ys) - 3.0, m_cz)
    cam.rotation_euler = (math.pi / 2, 0.0, 0.0)


def render(path, res):
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)


POSES = [
    ("neutral", {}),
    ("jawBone_09", {"__jaw_degrees__": 9}),
    ("jawBone_18", {"__jaw_degrees__": 18}),
    ("jawOpen_030", {"jawOpen": 0.30}),
    ("jawOpen_060", {"jawOpen": 0.60}),
    ("viseme_AA", {"vrc.v_aa": 1.0}),
    ("viseme_O", {"vrc.v_O": 1.0}),
    ("viseme_E", {"vrc.v_E": 1.0}),
    ("smile", {"mouthSmileLeft": 1.0, "mouthSmileRight": 1.0}),
    ("blink", {"eyeBlinkLeft": 1.0, "eyeBlinkRight": 1.0}),
]

saved = {k.name: k.value for k in kb} if kb else {}
saved_pose = {pb.name: pb.matrix_basis.copy() for pb in arm.pose.bones} if arm else {}
saved_rotation_modes = {pb.name: pb.rotation_mode for pb in arm.pose.bones} if arm else {}
# QA runs on background copies. Disable existing animation while posing;
# retain shape-key drivers so jaw-driven correctives are included.
saved_actions, saved_nla = [], []
for item in bpy.data.objects:
    ids = [item]
    if item.type == 'MESH' and item.data.shape_keys:
        ids.append(item.data.shape_keys)
    for data in ids:
        if data.animation_data:
            ad = data.animation_data
            saved_actions.append((ad, ad.action))
            ad.action = None
            for track in ad.nla_tracks:
                saved_nla.append((track, track.mute))
                track.mute = True
if arm:
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()

done = []
for name, vals in POSES:
    if arm:
        for pb in arm.pose.bones:
            pb.matrix_basis.identity()
    if kb:
        for k in kb:
            k.value = 0.0
    applied = {}
    for k, v in vals.items():
        if k == '__jaw_degrees__' and arm and 'jaw' in arm.pose.bones:
            jaw = arm.pose.bones['jaw']
            jaw.rotation_mode = 'XYZ'
            jaw.rotation_euler.x = math.radians(v)
            applied[k] = v
            continue
        if kb and k in kb:
            kb[k].value = v
            applied[k] = v
    if vals and not applied:
        continue
    bpy.context.view_layer.update()
    shot("bust")
    render(os.path.join(out_dir, "%s_bust_%s.png" % (tag, name)), 640)
    if closeup:
        shot("mouth")
        render(os.path.join(out_dir, "%s_mouth_%s.png" % (tag, name)), 900)
    done.append(name)

if kb:
    for k in kb:
        k.value = saved.get(k.name, 0.0)
if arm:
    for pb in arm.pose.bones:
        if pb.name in saved_pose:
            pb.rotation_mode = saved_rotation_modes[pb.name]
            pb.matrix_basis = saved_pose[pb.name]
for ad, action in saved_actions:
    ad.action = action
for track, mute in saved_nla:
    track.mute = mute

meta = {"tag": tag, "poses": done, "materials_repaired": repaired,
        "closeup": closeup, "out_dir": out_dir, "head": ob.name,
        "jaw_limit_degrees": [math.degrees(c.max_x) for c in arm.pose.bones['jaw'].constraints
                              if c.type == 'LIMIT_ROTATION' and c.use_limit_x]
                              if arm and 'jaw' in arm.pose.bones else []}
json.dump(meta, open(os.path.join(out_dir, "%s_meta.json" % tag), "w"), indent=1)

# Contact sheets are built OUTSIDE Blender by make_sheet.py: Blender's embedded
# interpreter usually cannot pip-install Pillow into Program Files.
print("QA_DONE " + json.dumps(meta))
print("NEXT: python make_sheet.py %s --kind bust   (and --kind mouth)" % out_dir)
