"""Render one neutral frame plus every ARKit or VRChat expression.

Usage:
  blender rigged.blend -b -P render_expression_atlas.py -- output_directory [size] [arkit|vrc]
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector


HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from tripo_face_rig.expressions import ARKIT_52, VRC_15


argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not argv:
    raise SystemExit("output directory required")
out_dir = os.path.abspath(argv[0])
size = int(argv[1]) if len(argv) > 1 else 320
mode = argv[2].lower() if len(argv) > 2 else "arkit"
if mode not in {"arkit", "vrc"}:
    raise SystemExit("mode must be arkit or vrc")
expressions = ARKIT_52 if mode == "arkit" else VRC_15
os.makedirs(out_dir, exist_ok=True)

meshes = [o for o in bpy.data.objects if o.type == 'MESH' and o.data.shape_keys]
if not meshes:
    raise SystemExit("no mesh with shape keys")
face = max(meshes, key=lambda o: len(o.data.vertices))
rig = bpy.data.objects.get("face_rig")
tongue = bpy.data.objects.get("tongue")

if face.data.shape_keys.animation_data:
    face.data.shape_keys.animation_data_clear()
if rig and rig.animation_data:
    rig.animation_data_clear()
if tongue and tongue.data.shape_keys and tongue.data.shape_keys.animation_data:
    tongue.data.shape_keys.animation_data_clear()
if rig:
    for pb in rig.pose.bones:
        pb.rotation_mode = 'XYZ'
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)

# Derive a close facial crop from the generated rig, not the bust bounds.
S = 1.0
eye_z = None
target_y = 0.0
if rig:
    head = rig.data.bones.get("head")
    if head and head.length:
        S = head.length / 0.42
    eyes = [rig.data.bones.get(n) for n in ("eye_L", "eye_R")]
    eyes = [b for b in eyes if b]
    if eyes:
        eye_z = sum(b.head_local.z for b in eyes) / len(eyes)
        target_y = sum(b.head_local.y for b in eyes) / len(eyes)
    jaw = rig.data.bones.get("jaw")
    chin_z = jaw.tail_local.z if jaw else None
else:
    chin_z = None

if eye_z is None or chin_z is None:
    points = [face.matrix_world @ Vector(c) for c in face.bound_box]
    z0, z1 = min(p.z for p in points), max(p.z for p in points)
    eye_z = z0 + 0.70 * (z1 - z0)
    chin_z = z0 + 0.27 * (z1 - z0)
center = Vector((0.0, target_y, 0.5 * (eye_z + chin_z) + 0.03 * S))

cam_data = bpy.data.cameras.new("_expression_camera")
cam = bpy.data.objects.new("_expression_camera", cam_data)
bpy.context.scene.collection.objects.link(cam)
bpy.context.scene.camera = cam
cam_data.type = 'ORTHO'
cam_data.ortho_scale = 0.62 * S
cam.location = center + Vector((0.0, -2.8 * S, 0.0))
cam.rotation_euler = ((center - cam.location).to_track_quat("-Z", "Y")).to_euler()

for name, offset, energy, area_size in (
        ("_expression_key", Vector((1.1, -1.8, 1.2)), 900, 1.4),
        ("_expression_fill", Vector((-1.2, -1.2, 0.5)), 550, 1.7),
        ("_expression_rim", Vector((0.0, 1.0, 1.2)), 700, 1.2)):
    data = bpy.data.lights.new(name, 'AREA')
    data.energy = energy
    data.shape = 'DISK'
    data.size = area_size * S
    light = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(light)
    light.location = center + offset * S
    light.rotation_euler = ((center - light.location).to_track_quat("-Z", "Y")).to_euler()

world = bpy.context.scene.world or bpy.data.worlds.new("_expression_world")
bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.018, 0.018, 0.018, 1.0)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.28

scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = size
scene.render.resolution_y = size
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.film_transparent = False
scene.render.image_settings.color_mode = 'RGBA'

face_keys = face.data.shape_keys.key_blocks
tongue_keys = tongue.data.shape_keys.key_blocks if tongue and tongue.data.shape_keys else None
controlled = set(ARKIT_52 + VRC_15 + ["mouthWide", "lipsPressed", "mouthFF"])
neutral_close = face_keys.get("mouthClose").value if face_keys.get("mouthClose") else 0.0


def reset_keys():
    for key in face_keys:
        if key.name in controlled:
            key.value = 0.0
    if face_keys.get("mouthClose"):
        face_keys["mouthClose"].value = neutral_close
    if tongue_keys:
        for key in tongue_keys:
            if key.name in controlled:
                key.value = 0.0


manifest = []
for index, name in enumerate(["neutral"] + expressions):
    reset_keys()
    target = None
    if name != "neutral":
        target = face_keys.get(name)
        if target is None and tongue_keys:
            target = tongue_keys.get(name)
        if target is not None:
            target.value = 1.0
    bpy.context.view_layer.update()
    filename = f"{index:02d}_{name}.png"
    scene.render.filepath = os.path.join(out_dir, filename)
    bpy.ops.render.render(write_still=True)
    manifest.append({"index": index, "expression": name,
                     "target": target.id_data.name if target else None,
                     "file": filename})

with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as stream:
    json.dump(manifest, stream, indent=2)
print(f"Rendered {len(manifest)} {mode.upper()} expression frames to {out_dir}")
