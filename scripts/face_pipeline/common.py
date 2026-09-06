"""Shared selection for Blender pipeline helpers; never choose hair by size."""
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tripo_face_rig.identify import classify, NOT_HEAD


def object_argument(argv):
    if '--obj' not in argv:
        return None
    index = argv.index('--obj') + 1
    if index == len(argv):
        raise RuntimeError('--obj requires a mesh name')
    return argv[index]


def pick_face(name=None):
    if name:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != 'MESH':
            raise RuntimeError('No mesh named %r' % name)
        return obj
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH'
              and classify(o.name) not in NOT_HEAD]
    named = [o for o in meshes if classify(o.name) == 'head']
    if len(named) == 1:
        return named[0]
    candidates = named or meshes
    # Separated hair can inherit inert copies of every expression key.
    scored = []
    for obj in candidates:
        keys = obj.data.shape_keys
        if not keys or 'Basis' not in keys.key_blocks:
            continue
        basis = keys.key_blocks['Basis']
        count = sum((v.co - basis.data[i].co).length_squared > 1e-12
                    for key in keys.key_blocks if key != basis
                    for i, v in enumerate(key.data))
        if count:
            scored.append((count, obj))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    if len(candidates) == 1:
        return candidates[0]
    raise RuntimeError('Head selection is ambiguous; pass --obj NAME. Candidates: %s'
                       % ', '.join(o.name for o in candidates))


def face_armature(obj):
    rigs = [m.object for m in obj.modifiers
            if m.type == 'ARMATURE' and m.object is not None]
    if not rigs and obj.parent and obj.parent.type == 'ARMATURE':
        rigs = [obj.parent]
    if len(set(rigs)) > 1:
        raise RuntimeError('Selected mesh has multiple armatures; inspect its modifiers')
    return rigs[0] if rigs else None
