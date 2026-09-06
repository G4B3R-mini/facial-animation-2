"""Merge an artist-assembled head/body in a copy and export a Unity FBX.

blender -b assembled.blend --python-exit-code 1 --python unity_prep.py --
  --body-armature Armature --face-armature face_rig --head-bone Head
  --out work/character/unity.blend --fbx work/character/character.fbx
Use --apply-body-booleans BODY_MESH only for an intentional non-destructive head cut.
"""
import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix


def evaluated_vertices(objects):
    graph = bpy.context.evaluated_depsgraph_get()
    result = {}
    for obj in objects:
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        result[obj.name] = [evaluated.matrix_world @ v.co for v in mesh.vertices]
        evaluated.to_mesh_clear()
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--body-armature', required=True)
    p.add_argument('--face-armature', required=True)
    p.add_argument('--head-bone', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--fbx', required=True)
    p.add_argument('--apply-body-booleans', help='Explicit body mesh whose Boolean cut should be applied')
    args = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    source = Path(bpy.data.filepath).resolve()
    out, fbx = Path(args.out).resolve(), Path(args.fbx).resolve()
    if out == source or out.suffix.lower() != '.blend' or fbx.suffix.lower() != '.fbx':
        raise ValueError('Use separate .blend and .fbx output paths; preserve the source')
    body = bpy.data.objects.get(args.body_armature)
    face = bpy.data.objects.get(args.face_armature)
    if not body or not face or body == face or body.type != 'ARMATURE' or face.type != 'ARMATURE':
        raise ValueError('Specify two distinct armature objects from the assembled scene')
    if args.head_bone not in body.data.bones:
        raise ValueError('Body head bone does not exist: ' + args.head_bone)
    face_names = set(face.data.bones.keys())
    collisions = face_names & set(body.data.bones.keys())
    if collisions:
        raise ValueError('Resolve bone name collisions before merge: ' + ', '.join(sorted(collisions)))
    face_roots = [b.name for b in face.data.bones if b.parent is None]
    # Export the runtime character in neutral. Keep preview actions in the input file.
    objects = [o for o in bpy.context.scene.objects if o.type == 'MESH' and
               (any(m.type == 'ARMATURE' and m.object in (body, face) for m in o.modifiers)
                or o.parent in (body, face))]
    if not objects:
        raise ValueError('No character meshes bound to the supplied armatures')
    for obj in objects:
        if not any(m.type == 'ARMATURE' and m.object in (body, face) for m in obj.modifiers):
            raise ValueError('Rigid accessory needs bone weights before export: ' + obj.name)
        unsupported = [m.name for m in obj.modifiers if m.show_viewport and m.type not in ('ARMATURE', 'BOOLEAN')]
        if unsupported:
            raise ValueError('Finalize non-skin modifiers while preserving shape keys before export: %s: %s' % (obj.name, unsupported))
    face_meshes = [o for o in objects if any(m.type == 'ARMATURE' and m.object == face for m in o.modifiers)]
    for obj in [body, face] + objects:
        if obj.animation_data:
            obj.animation_data.action = None
            for track in obj.animation_data.nla_tracks:
                track.mute = True
        if obj.type == 'ARMATURE':
            for bone in obj.pose.bones:
                bone.matrix_basis = Matrix.Identity(4)
        elif obj.data.shape_keys:
            keys = obj.data.shape_keys
            if keys.animation_data:
                keys.animation_data.action = None
                for track in keys.animation_data.nla_tracks:
                    track.mute = True
            for key in keys.key_blocks:
                key.value = 0
    bpy.context.view_layer.update()
    before = evaluated_vertices(face_meshes)
    shape_counts = {o.name: len(o.data.shape_keys.key_blocks) for o in objects if o.data.shape_keys}
    report = {'source': str(source), 'body': body.name, 'face': face.name,
              'head_bone': args.head_bone, 'runtime_export': True}
    if args.apply_body_booleans:
        mesh = bpy.data.objects.get(args.apply_body_booleans)
        if mesh not in objects or mesh in face_meshes:
            raise ValueError('Boolean target must be a mesh bound to the body armature')
        booleans = [m for m in mesh.modifiers if m.type == 'BOOLEAN']
        if not booleans:
            raise ValueError('Requested head cut but body has no Boolean modifier')
        keys = mesh.data.shape_keys
        if keys:
            basis = keys.key_blocks[0]
            if any(any((v.co - basis.data[i].co).length > 1e-6 for i, v in enumerate(k.data)) for k in keys.key_blocks[1:]):
                raise ValueError('Body has live shape keys; finalize the head cut manually without dropping them')
            mesh.shape_key_clear()
            shape_counts.pop(mesh.name, None)
        bpy.ops.object.select_all(action='DESELECT')
        mesh.select_set(True)
        bpy.context.view_layer.objects.active = mesh
        for mod in booleans:
            bpy.ops.object.modifier_apply(modifier=mod.name)
        report['body_cut'] = mesh.name
    elif any(m.type == 'BOOLEAN' for o in objects for m in o.modifiers):
        raise ValueError('Unapplied Boolean on character: finalize it manually or pass --apply-body-booleans BODY_MESH')
    # Preserve the evaluated attachment transform when removing object constraints.
    # Face and body bone rest poses remain independent until the armature join.
    attached_world = face.matrix_world.copy()
    for constraint in list(face.constraints):
        face.constraints.remove(constraint)
    face.matrix_world = attached_world
    bpy.context.view_layer.update()
    unbound = evaluated_vertices(face_meshes)
    detach_drift = max(((v - unbound[name][i]).length for name, verts in before.items() for i, v in enumerate(verts)), default=0)
    if detach_drift > 1e-4:
        raise ValueError('Attachment changes the rest position (drift %.6g). Apply the placement to the face rig and meshes before merging.' % detach_drift)
    worlds = {o.name: o.matrix_world.copy() for o in objects}
    driver_targets = []
    for obj in objects + [body, face]:
        for owner in (obj, obj.data, getattr(obj.data, 'shape_keys', None)):
            ad = getattr(owner, 'animation_data', None)
            if ad:
                for curve in ad.drivers:
                    for variable in curve.driver.variables:
                        for target in variable.targets:
                            if target.id == face:
                                driver_targets.append(target)
    bpy.ops.object.select_all(action='DESELECT')
    face.select_set(True)
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    bpy.ops.object.mode_set(mode='EDIT')
    for name in face_roots:
        bone = body.data.edit_bones[name]
        bone.parent = body.data.edit_bones[args.head_bone]
        bone.use_connect = False
    bpy.ops.object.mode_set(mode='OBJECT')
    for target in driver_targets:
        target.id = body
    for obj in objects:
        for mod in obj.modifiers:
            if mod.type == 'ARMATURE' and (obj in face_meshes or mod.object is None):
                mod.object = body
        obj.parent = None
        obj.matrix_world = worlds[obj.name]
    bpy.context.view_layer.update()
    after = evaluated_vertices(face_meshes)
    drift = max(((v - after[name][i]).length for name, verts in before.items() for i, v in enumerate(verts)), default=0)
    if drift > 1e-4:
        raise ValueError('Merge moved evaluated face vertices by %.6g; review source bind transforms' % drift)
    for name, count in shape_counts.items():
        assert len(bpy.data.objects[name].data.shape_keys.key_blocks) == count, name
    report.update(face_vertex_drift=drift, face_roots=face_roots, shape_keys=shape_counts,
                  meshes=[o.name for o in objects], bones=len(body.data.bones), drivers_retargeted=len(driver_targets))
    out.parent.mkdir(parents=True, exist_ok=True)
    fbx.parent.mkdir(parents=True, exist_ok=True)
    # Write only material images used by this character, with distinct filenames.
    images = set()
    for obj in objects:
        for slot in obj.material_slots:
            if slot.material and slot.material.use_nodes:
                images.update(n.image for n in slot.material.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image)
    texture_dir = fbx.parent / (fbx.stem + '_textures')
    texture_dir.mkdir(exist_ok=True)
    for index, img in enumerate(sorted(images, key=lambda im: im.name)):
        # Packed images can be lazily loaded in background Blender.
        if not img.has_data:
            _ = img.pixels[0] if len(img.pixels) else None
        if not img.has_data:
            raise ValueError('Missing texture pixels: ' + img.name)
        img.file_format = 'PNG'
        dest = texture_dir / ('%03d_%s.png' % (index, bpy.path.clean_name(Path(img.name).stem)))
        img.save(filepath=str(dest))
        if img.packed_file:
            img.unpack(method='REMOVE')
        img.filepath = str(dest)
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects + [body]:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = body
    # Modifiers must be disabled in FBX export to retain blendshapes. The explicit
    # body cut was already applied; armature skinning is exported independently.
    bpy.ops.export_scene.fbx(filepath=str(fbx), use_selection=True,
        object_types={'ARMATURE', 'MESH'}, use_mesh_modifiers=False,
        add_leaf_bones=False, bake_anim=False, path_mode='COPY', embed_textures=False,
        axis_forward='-Z', axis_up='Y', apply_scale_options='FBX_SCALE_ALL')
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    out.with_suffix('.export.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('UNITY_PREP_PASS ' + json.dumps(report))


if __name__ == '__main__':
    main()
