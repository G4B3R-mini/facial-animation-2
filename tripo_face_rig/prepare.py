"""Stage 0: get a head into the shape the rest of the pipeline assumes.

Two assumptions run through measure/build: the face is centred on x=0, and the
teeth are shells of the head mesh. Neither held on the second head tested --
its midline sits at x=+0.024, and its teeth were supplied as separate objects.

Rather than thread a midline offset through every downstream function, this
stage moves the mesh so x=0 IS the midline, and absorbs the teeth objects into
the head mesh so shell classification finds them the usual way.
"""
import bpy
import bmesh
from . import util


def normalize_transform(obj):
    """Bake a source object's transform so local axes match pipeline axes.

    Tripo exports can carry a small Z rotation and translation even though the
    character looks upright in world space.  All landmark math intentionally
    runs in mesh-local coordinates, so leaving that transform unapplied makes
    bilateral shells appear vertically/depth-offset and defeats pairing.
    """
    loc = list(obj.location)
    rot = list(obj.rotation_euler)
    scale = list(obj.scale)
    changed = (max(abs(v) for v in loc) > 1e-6
               or max(abs(v) for v in rot) > 1e-6
               or max(abs(v - 1.0) for v in scale) > 1e-6)
    if changed:
        for other in bpy.context.view_layer.objects:
            try:
                other.select_set(False)
            except Exception:
                pass
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        with bpy.context.temp_override(active_object=obj, object=obj,
                                       selected_objects=[obj],
                                       selected_editable_objects=[obj]):
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return {"changed": changed, "location": loc, "rotation": rot, "scale": scale}


def weld_coincident(obj, distance=1e-7):
    """Reconnect an export whose shared quad corners were split into vertices.

    Some Tripo quad exports arrive triangulated with every quad boundary split,
    producing hundreds of false mesh islands.  Exact-position welding restores
    the intended connectivity while retaining per-loop UVs and face materials.
    This is opt-in because genuinely separate coincident lip surfaces should
    not be welded indiscriminately on other topology families.
    """
    if distance <= 0.0:
        raise ValueError("weld distance must be positive")
    _comp_of, before_groups = util.islands(obj.data)
    vertices_before = len(obj.data.vertices)
    faces_before = len(obj.data.polygons)

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=distance)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()

    _comp_of, after_groups = util.islands(obj.data)
    return {
        "distance": distance,
        "vertices_before": vertices_before,
        "vertices_after": len(obj.data.vertices),
        "vertices_merged": vertices_before - len(obj.data.vertices),
        "faces_before": faces_before,
        "faces_after": len(obj.data.polygons),
        "islands_before": len(before_groups),
        "islands_after": len(after_groups),
        "largest_island_after": max((len(v) for v in after_groups.values()),
                                    default=0),
        "uv_layers": len(obj.data.uv_layers),
    }


def find_midline(mesh, scale):
    """Midline x, from mirror-pair shells (eyes, brows, ears).

    Global symmetry is useless for this -- hair and clothing swamp it. Paired
    shells are reliable: on the test head the eye pair gave +0.0240 and the
    brow pair +0.0245, and the user's hand-placed teeth independently agreed
    at +0.0214.
    """
    comp_of, groups = util.islands(mesh)
    info = {}
    for c, idx in groups.items():
        bb = util.bbox(mesh, idx)
        info[c] = {"n": len(idx),
                   "c": [0.5 * (bb[k][0] + bb[k][1]) for k in ("x", "y", "z")],
                   "bb": bb}
    votes = []
    keys = sorted(info)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            A, B = info[a], info[b]
            if A["n"] < 12 or B["n"] < 12:
                continue
            if abs(A["n"] - B["n"]) > 0.25 * max(A["n"], B["n"]):
                continue
            if abs(A["c"][1] - B["c"][1]) > 0.03 * scale:
                continue
            if abs(A["c"][2] - B["c"][2]) > 0.03 * scale:
                continue
            if abs(A["c"][0] - B["c"][0]) < 0.04 * scale:
                continue
            votes.append((0.5 * (A["c"][0] + B["c"][0]), min(A["n"], B["n"])))
    if not votes:
        return {"midline": 0.0, "votes": 0, "source": "none"}
    votes.sort(key=lambda v: -v[1])
    top = votes[:6]
    xs = sorted(v[0] for v in top)
    mid = xs[len(xs) // 2] if len(xs) % 2 else 0.5 * (xs[len(xs) // 2 - 1] + xs[len(xs) // 2])
    return {"midline": mid, "votes": len(votes),
            "spread": round(max(xs) - min(xs), 5), "source": "mirror_pairs"}


def align(obj, midline=None, companions=()):
    """Shift the mesh so the midline is x=0.

    The object transform is deliberately NOT compensated: build_armature emits
    bone positions in the head's LOCAL space and links the armature at the
    origin, so moving the head object would offset the whole rig from the mesh.
    Instead any separately-supplied objects (a user-placed tongue) are moved by
    the same amount in world space, keeping everything in one frame.
    """
    mesh = obj.data
    bb = util.bbox(mesh, list(range(len(mesh.vertices))))
    scale = bb["z"][1] - bb["z"][0]
    found = find_midline(mesh, scale) if midline is None else {
        "midline": midline, "votes": -1, "source": "given"}
    dx = found["midline"]
    if abs(dx) > 1e-6:
        from mathutils import Vector
        for v in mesh.vertices:
            v.co.x -= dx
        mesh.update()
        wd = obj.matrix_world.to_3x3() @ Vector((-dx, 0.0, 0.0))
        for c in companions:
            c.matrix_world.translation = c.matrix_world.translation + wd
    found["applied_dx"] = dx
    found["companions_moved"] = [c.name for c in companions]
    return found


def absorb(head, names):
    """Join named objects into the head mesh so they become shells."""
    others = [bpy.data.objects[n] for n in names if n in bpy.data.objects]
    if not others:
        return {"absorbed": [], "verts_added": 0}
    before = len(head.data.vertices)
    names_taken = [o.name for o in others]   # join() frees the objects
    counts = [len(o.data.vertices) for o in others]
    for o in bpy.context.view_layer.objects:
        try:
            o.select_set(False)
        except Exception:
            pass
    head.select_set(True)
    for o in others:
        o.select_set(True)
    bpy.context.view_layer.objects.active = head
    with bpy.context.temp_override(active_object=head, object=head,
                                   selected_objects=[head] + others,
                                   selected_editable_objects=[head] + others):
        bpy.ops.object.join()
    # join() appends each object's vertices in order, so the ranges are known.
    # Passing them downstream removes the need to GUESS which shells are teeth
    # -- the size heuristic breaks as soon as the teeth are subdivided and end
    # up larger than the face shell.
    ranges = {}
    at = before
    for nm, n in zip(names_taken, counts):
        ranges[nm] = [at, at + n]
        at += n
    return {"absorbed": names_taken, "ranges": ranges,
            "verts_added": len(head.data.vertices) - before}


def bind_object_to_bone(obj, ao, bone):
    """Armature-DEFORM binding -- never bone-parenting.

    Bone parenting moves the child whenever the bone's rest position is edited,
    so hand-tuning the hinge silently drags user-placed teeth out of place, and
    rebuilding the armature corrupts their transforms outright.
    """
    for g in list(obj.vertex_groups):
        obj.vertex_groups.remove(g)
    vg = obj.vertex_groups.new(name=bone)
    vg.add([v.index for v in obj.data.vertices], 1.0, 'REPLACE')
    for m in list(obj.modifiers):
        if m.type == 'ARMATURE':
            obj.modifiers.remove(m)
    obj.modifiers.new("rig", 'ARMATURE').object = ao
    return obj.name
