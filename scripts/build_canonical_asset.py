"""Build the reusable ICT canonical .blend asset and a compact JSON report."""

import json
import os
import sys

import bpy


repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo not in sys.path:
    sys.path.insert(0, repo)

from tripo_face_rig import canonical


for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

face = canonical.create_canonical(repo, expressions=True)
face["license"] = "MIT; see third_party/ICT-FaceKit/LICENSE"
face["purpose"] = "Reusable topology and ARKit expression source"

material = bpy.data.materials.new("CanonicalClay")
material.diffuse_color = (0.35, 0.22, 0.16, 1.0)
material.roughness = 0.72
face.data.materials.append(material)

asset_dir = os.path.join(repo, "assets")
os.makedirs(asset_dir, exist_ok=True)
blend_path = os.path.join(asset_dir, "ict_canonical_face.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)

report = {
    "source": "USC ICT FaceKit",
    "license": "MIT",
    "vertices": len(face.data.vertices),
    "polygons": len(face.data.polygons),
    "shape_keys": list(face.data.shape_keys.key_blocks.keys()),
    "guides": list(canonical.LANDMARKS.keys()),
    "blend": blend_path,
}
with open(os.path.join(asset_dir, "ict_canonical_face.json"), "w", encoding="utf-8") as stream:
    json.dump(report, stream, indent=2)
print("CANONICAL_REPORT=" + json.dumps(report))
