"""Self-contained Blender test: replacing actions must preserve corrective drivers.

blender -b --factory-startup --python-exit-code 1 --python tests/blender_animation_smoke.py
"""
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tripo_face_rig.util import clear_action

bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.object
obj.shape_key_add(name='Basis')
seal = obj.shape_key_add(name='mouthClose')
viseme = obj.shape_key_add(name='mouthWide')
driver = seal.driver_add('value')
driver.driver.expression = '0.5'
viseme.value = 0.2
viseme.keyframe_insert('value', frame=1)
viseme.value = 0.8
viseme.keyframe_insert('value', frame=10)
keys = obj.data.shape_keys
assert keys.animation_data.action is not None
assert len(keys.animation_data.drivers) == 1
clear_action(keys)
assert keys.animation_data.action is None
assert len(keys.animation_data.drivers) == 1
assert keys.animation_data.drivers[0].driver.expression == '0.5'
# A second clip and another clear exercise the repeated-voice path.
viseme.keyframe_insert('value', frame=4)
clear_action(keys)
assert keys.animation_data.action is None
assert len(keys.animation_data.drivers) == 1
print('ANIMATION_DRIVER_PRESERVATION_PASS')
