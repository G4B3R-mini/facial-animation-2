bl_info = {
    "name": "Tripo Face Rig Wizard",
    "author": "Local pipeline",
    "version": (0, 2, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Face Rig",
    "description": "Guided facial landmarks and ARKit rig generation",
    "category": "Rigging",
}

import json
import hashlib
import heapq
import math
import os
from pathlib import Path
import struct
import subprocess
import sys

import bpy
import bmesh
from bpy_extras import view3d_utils
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, PointerProperty,
                       StringProperty)
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup
from mathutils import Matrix, Vector


MARKERS = (
    ("mouth_corner_R", "Right corner", "Place at the exact right commissure."),
    ("upper_lip_R", "Upper lip right", "Place on the upper vermilion ridge, halfway to the corner."),
    ("upper_lip_center", "Upper lip center", "Place at the center of the upper lip's visible edge."),
    ("upper_lip_L", "Upper lip left", "Place on the upper vermilion ridge, halfway to the corner."),
    ("mouth_corner_L", "Left corner", "Place at the exact left commissure."),
    ("lower_lip_R", "Lower lip right", "Place on the lower vermilion ridge, halfway to the corner."),
    ("lower_lip_center", "Lower lip center", "Place at the center of the lower lip's visible edge."),
    ("lower_lip_L", "Lower lip left", "Place on the lower vermilion ridge, halfway to the corner."),
    ("chin_center", "Chin center", "Place on the front-center of the chin."),
)
MARKER_MAP = {name: (label, help_text) for name, label, help_text in MARKERS}
PAIRS = {
    "mouth_corner_R": "mouth_corner_L", "mouth_corner_L": "mouth_corner_R",
    "upper_lip_R": "upper_lip_L", "upper_lip_L": "upper_lip_R",
    "lower_lip_R": "lower_lip_L", "lower_lip_L": "lower_lip_R",
}
COLLECTION_NAME = "Face Rig Guides"
SEAM_PROPERTY = "face_rig_mouth_seam"
CALIBRATION_KEYS = (
    "jawOpen", "mouthClose", "mouthFunnel", "mouthPucker",
    "mouthSmileLeft", "mouthSmileRight",
)
_build_process = None


def _addon_key():
    return __package__ or __name__


def _preferences(context):
    addon = context.preferences.addons.get(_addon_key())
    return addon.preferences if addon else None


def _default_repo():
    candidate = Path(__file__).resolve().parents[2]
    return str(candidate) if (candidate / "autorig.py").is_file() else ""


def _repo_path(context):
    prefs = _preferences(context)
    path = bpy.path.abspath(prefs.repo_path) if prefs else ""
    return os.path.abspath(path) if path else _default_repo()


def _core(context):
    repo = _repo_path(context)
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from tripo_face_rig import face_guides
    return face_guides


def _guide_collection(scene):
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION_NAME)
        scene.collection.children.link(collection)
    return collection


def _marker(role):
    for obj in bpy.data.objects:
        if obj.get("face_guide_role") == role:
            return obj
    return None


def _head(settings):
    obj = settings.head
    return obj if obj and obj.type == "MESH" else None


def _basis_signature(obj):
    block = (obj.data.shape_keys.key_blocks.get("Basis")
             if obj and obj.data.shape_keys else None)
    points = block.data if block else obj.data.vertices
    digest = hashlib.sha256()
    for point in points:
        digest.update(struct.pack("<3d", point.co.x, point.co.y, point.co.z))
    return digest.hexdigest()


def _marker_scale(head):
    return max(head.dimensions) * 0.012


def _ensure_marker(context, role, local_position=None):
    settings = context.scene.face_rig_wizard
    head = _head(settings)
    if head is None:
        raise RuntimeError("Assign a mesh as the Head first")
    obj = _marker(role)
    if obj is None:
        obj = bpy.data.objects.new("FRG_" + role, None)
        _guide_collection(context.scene).objects.link(obj)
        obj.empty_display_type = "SPHERE"
        obj["face_guide_role"] = role
    obj.parent = head
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.empty_display_size = _marker_scale(head)
    obj.show_in_front = True
    obj.color = ((0.95, 0.25, 0.12, 1.0) if "corner" in role else
                 (0.20, 0.72, 1.0, 1.0) if "upper" in role else
                 (0.30, 1.0, 0.42, 1.0) if "lower" in role else
                 (0.95, 0.72, 0.10, 1.0))
    if local_position is not None:
        obj.location = Vector(local_position)
    return obj


def _select_only(obj):
    for other in bpy.context.view_layer.objects:
        try:
            other.select_set(False)
        except Exception:
            pass
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _front_surface(head, x, z):
    # A ray through a sealed or slightly open mouth can hit the oral cavity or
    # tongue.  For automatic placement, use the frontmost of the nearby skin
    # samples in x/z instead. Interactive placement still uses a true view ray.
    candidates = sorted(
        head.data.vertices,
        key=lambda vertex: ((vertex.co.x - x) ** 2
                            + (vertex.co.z - z) ** 2))[:24]
    return min(candidates, key=lambda vertex: vertex.co.y).co.copy() if candidates else Vector((x, 0.0, z))


def _bounds_in_head(obj, head):
    if obj is None:
        return None
    inverse = head.matrix_world.inverted()
    points = [inverse @ (obj.matrix_world @ Vector(corner)) for corner in obj.bound_box]
    return {
        "x": (min(p.x for p in points), max(p.x for p in points)),
        "y": (min(p.y for p in points), max(p.y for p in points)),
        "z": (min(p.z for p in points), max(p.z for p in points)),
    }


def _default_guide_path():
    blend = bpy.data.filepath
    if blend:
        return os.path.splitext(blend)[0] + ".faceguide.json"
    return os.path.join(bpy.app.tempdir, "character.faceguide.json")


def _gather_guide(context):
    settings = context.scene.face_rig_wizard
    head = _head(settings)
    markers = {}
    for role, _label, _help in MARKERS:
        obj = _marker(role)
        if obj is None or head is None:
            continue
        local = head.matrix_world.inverted() @ obj.matrix_world.translation
        markers[role] = {"local": list(local), "object": obj.name}
    masks = {}
    if head:
        for name in ("FRG_upper_lip", "FRG_lower_lip", "FRG_corners", "FRG_jaw"):
            group = head.vertex_groups.get(name)
            if group is None:
                continue
            values = {}
            for vertex in head.data.vertices:
                try:
                    weight = group.weight(vertex.index)
                except RuntimeError:
                    continue
                if weight > 0.001:
                    values[str(vertex.index)] = round(weight, 5)
            masks[name] = values
    return {
        "schema_version": 2,
        "objects": {
            "head": head.name if head else None,
            "upper_teeth": settings.upper_teeth.name if settings.upper_teeth else None,
            "lower_teeth": settings.lower_teeth.name if settings.lower_teeth else None,
            "tongue": settings.tongue.name if settings.tongue else None,
        },
        "markers": markers,
        "masks": masks,
        "topology": {
            "mouth_seam": json.loads(head.get(SEAM_PROPERTY, "{}")) if head else {},
        },
        "calibration": {
            "approved": bool(head and head.get("face_rig_calibration_approved", False)),
        },
        "settings": {
            "lip_influence": settings.lip_influence,
            "jaw_open_deg": settings.jaw_open_deg,
            "pucker_strength": settings.pucker_strength,
            "funnel_strength": settings.funnel_strength,
            "smile_strength": settings.smile_strength,
        },
        "source_blend": bpy.data.filepath,
    }


def _guide_status(context):
    try:
        core = _core(context)
        return core.validate(_gather_guide(context))
    except Exception as exc:
        return {"valid": False, "issues": [str(exc)], "missing": []}


def _build_status(context):
    try:
        return _core(context).validate_for_build(_gather_guide(context))
    except Exception as exc:
        return {"valid": False, "issues": [str(exc)], "missing": []}


def _ordered_edge_path(edges):
    """Return ordered vertices for a single open, unbranched selected path."""
    adjacency = {}
    for edge in edges:
        a, b = edge.verts
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)
    endpoints = [vertex for vertex, linked in adjacency.items() if len(linked) == 1]
    if len(endpoints) != 2 or any(len(linked) > 2 for linked in adjacency.values()):
        raise RuntimeError("Select one open, unbranched edge path with exactly two endpoints")
    ordered = [endpoints[0]]
    previous = None
    current = endpoints[0]
    while True:
        choices = [vertex for vertex in adjacency[current] if vertex is not previous]
        if not choices:
            break
        following = choices[0]
        ordered.append(following)
        previous, current = current, following
        if len(ordered) > len(adjacency) + 1:
            raise RuntimeError("The selected mouth seam contains a cycle")
    if len(ordered) != len(adjacency):
        raise RuntimeError("The selected mouth seam is disconnected")
    return ordered


def _best_seam_path(edges, right, left, guide_rail):
    """Extract one corner-to-corner path from a roughly selected edge band.

    Artists naturally select a few parallel/branching edges around an uneven
    lip contact line. Requiring an already perfect graph path just moves graph
    bookkeeping onto the user. Dijkstra chooses the shortest route while a
    rail-distance penalty keeps it on the guided wet line.
    """
    vertices = {vertex for edge in edges for vertex in edge.verts}
    if len(vertices) < 4:
        raise RuntimeError("Select the curved lip-contact band from corner to corner")
    start = min(vertices, key=lambda vertex: (vertex.co - right).length_squared)
    goal = min(vertices, key=lambda vertex: (vertex.co - left).length_squared)
    adjacency = {vertex: [] for vertex in vertices}
    mouth_width = max((left - right).length, 1e-8)

    def rail_distance(point):
        best = float("inf")
        for a, b in zip(guide_rail, guide_rail[1:]):
            segment = b - a
            t = max(0.0, min(1.0, (point - a).dot(segment) /
                                 max(segment.length_squared, 1e-12)))
            best = min(best, (point - (a + t * segment)).length)
        return best

    for edge in edges:
        a, b = edge.verts
        midpoint = (a.co + b.co) * 0.5
        penalty = 1.0 + 18.0 * rail_distance(midpoint) / mouth_width
        cost = max((a.co - b.co).length, 1e-8) * penalty
        adjacency[a].append((b, cost))
        adjacency[b].append((a, cost))

    distance = {start: 0.0}
    previous = {}
    queue = [(0.0, start.index, start)]
    while queue:
        cost, _index, current = heapq.heappop(queue)
        if current is goal:
            break
        if cost != distance.get(current):
            continue
        for following, edge_cost in adjacency[current]:
            candidate = cost + edge_cost
            if candidate < distance.get(following, float("inf")):
                distance[following] = candidate
                previous[following] = current
                heapq.heappush(queue, (candidate, following.index, following))
    if goal not in distance:
        raise RuntimeError(
            "The selected lip band has a gap between the two mouth corners")
    ordered = [goal]
    while ordered[-1] is not start:
        ordered.append(previous[ordered[-1]])
    ordered.reverse()
    return ordered


class FACE_RIG_AddonPreferences(AddonPreferences):
    bl_idname = _addon_key()
    repo_path: StringProperty(
        name="Pipeline repository",
        subtype="DIR_PATH",
        default=_default_repo(),
        description="Folder containing autorig.py and tripo_face_rig")

    def draw(self, context):
        self.layout.prop(self, "repo_path")


class FACE_RIG_Settings(PropertyGroup):
    head: PointerProperty(name="Head", type=bpy.types.Object)
    upper_teeth: PointerProperty(name="Upper Teeth", type=bpy.types.Object)
    lower_teeth: PointerProperty(name="Lower Teeth", type=bpy.types.Object)
    tongue: PointerProperty(name="Tongue", type=bpy.types.Object)
    guide_path: StringProperty(name="Guide File", subtype="FILE_PATH")
    output_path: StringProperty(name="Rigged Copy", subtype="FILE_PATH")
    status: StringProperty(name="Status", default="Assign the character objects to begin.")
    active_step: EnumProperty(
        name="Step", default="OBJECTS",
        items=(("OBJECTS", "1 Objects", "Assign source objects"),
               ("MOUTH", "2 Mouth Guides", "Place and refine mouth guides"),
               ("SEAM", "3 Mouth Seam", "Author and validate the opening path"),
               ("MASKS", "4 Weights", "Paint direct deformation regions"),
               ("BUILD", "5 Calibrate", "Build and approve calibration poses")))
    lip_influence: FloatProperty(name="Lip Influence", default=1.0,
                                 min=0.55, max=1.65, soft_min=0.75, soft_max=1.3)
    jaw_open_deg: FloatProperty(name="Jaw Open Degrees", default=9.0,
                                min=3.0, max=18.0)
    pucker_strength: FloatProperty(name="Pucker", default=1.0, min=0.4, max=1.8)
    funnel_strength: FloatProperty(name="Funnel", default=1.0, min=0.4, max=1.8)
    smile_strength: FloatProperty(name="Smile", default=1.0, min=0.4, max=1.8)
    final_output_path: StringProperty(name="Final ARKit Rig", subtype="FILE_PATH")


class FACE_RIG_OT_assign_selected(Operator):
    bl_idname = "face_rig.assign_selected"
    bl_label = "Assign Selected"
    bl_options = {"REGISTER", "UNDO"}
    target: EnumProperty(items=(("HEAD", "Head", ""), ("UPPER", "Upper Teeth", ""),
                               ("LOWER", "Lower Teeth", ""), ("TONGUE", "Tongue", "")))

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "Select one mesh object first")
            return {"CANCELLED"}
        settings = context.scene.face_rig_wizard
        setattr(settings, {"HEAD": "head", "UPPER": "upper_teeth",
                           "LOWER": "lower_teeth", "TONGUE": "tongue"}[self.target], obj)
        settings.status = "%s assigned." % self.target.title()
        return {"FINISHED"}


class FACE_RIG_OT_auto_seed(Operator):
    bl_idname = "face_rig.auto_seed"
    bl_label = "Auto Place Mouth Guides"
    bl_description = "Create an editable first guess from the head and dental objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.face_rig_wizard
        head = _head(settings)
        if head is None:
            self.report({"ERROR"}, "Assign the Head first")
            return {"CANCELLED"}
        corners = [Vector(corner) for corner in head.bound_box]
        z_min, z_max = min(p.z for p in corners), max(p.z for p in corners)
        height = z_max - z_min
        dental = [_bounds_in_head(settings.upper_teeth, head),
                  _bounds_in_head(settings.lower_teeth, head)]
        dental = [bounds for bounds in dental if bounds]
        if dental:
            tx0 = min(bounds["x"][0] for bounds in dental)
            tx1 = max(bounds["x"][1] for bounds in dental)
            center_x = 0.5 * (tx0 + tx1)
            mouth_z = 0.5 * (min(bounds["z"][0] for bounds in dental)
                             + max(bounds["z"][1] for bounds in dental))
            half_width = max(0.045 * height, 0.90 * 0.5 * (tx1 - tx0))
        else:
            mouth_z = z_min + 0.39 * height
            half_width = 0.105 * height
            center_x = 0.5 * (min(point.x for point in corners)
                              + max(point.x for point in corners))
        lip_half = max(0.018 * height, 0.23 * half_width)
        positions = {
            "mouth_corner_R": (center_x - half_width, mouth_z),
            "upper_lip_R": (center_x - 0.52 * half_width, mouth_z + 0.72 * lip_half),
            "upper_lip_center": (center_x, mouth_z + lip_half),
            "upper_lip_L": (center_x + 0.52 * half_width, mouth_z + 0.72 * lip_half),
            "mouth_corner_L": (center_x + half_width, mouth_z),
            "lower_lip_R": (center_x - 0.52 * half_width, mouth_z - 0.62 * lip_half),
            "lower_lip_center": (center_x, mouth_z - lip_half),
            "lower_lip_L": (center_x + 0.52 * half_width, mouth_z - 0.62 * lip_half),
            "chin_center": (center_x, z_min + 0.22 * height),
        }
        for role, (x, z) in positions.items():
            _ensure_marker(context, role, _front_surface(head, x, z))
        settings.active_step = "MOUTH"
        settings.status = ("Guides placed. Inspect them from front and side; "
                           "move incorrect markers with G or use Place on Surface.")
        return {"FINISHED"}


class FACE_RIG_OT_place_marker(Operator):
    bl_idname = "face_rig.place_marker"
    bl_label = "Place Guide on Surface"
    bl_description = "Click once on the visible head surface; Esc cancels"
    bl_options = {"REGISTER", "UNDO"}
    role: StringProperty()

    def invoke(self, context, event):
        if context.area.type != "VIEW_3D" or _head(context.scene.face_rig_wizard) is None:
            self.report({"ERROR"}, "Run this from a 3D View after assigning the Head")
            return {"CANCELLED"}
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set("Click the requested facial landmark. Esc cancels.")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            context.workspace.status_text_set(None)
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            head = _head(context.scene.face_rig_wizard)
            region, rv3d = context.region, context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)
            origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
            direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
            inverse = head.matrix_world.inverted()
            local_origin = inverse @ origin
            local_direction = (inverse.to_3x3() @ direction).normalized()
            hit, location, _normal, _face = head.ray_cast(local_origin, local_direction)
            if not hit:
                self.report({"WARNING"}, "No head surface under the cursor; try again")
                return {"RUNNING_MODAL"}
            marker = _ensure_marker(context, self.role, location)
            _select_only(marker)
            context.scene.face_rig_wizard.status = "%s placed." % MARKER_MAP[self.role][0]
            context.workspace.status_text_set(None)
            return {"FINISHED"}
        return {"RUNNING_MODAL"}


class FACE_RIG_OT_mirror_marker(Operator):
    bl_idname = "face_rig.mirror_marker"
    bl_label = "Mirror Guide"
    bl_options = {"REGISTER", "UNDO"}
    role: StringProperty()

    def execute(self, context):
        source = _marker(self.role)
        target_role = PAIRS.get(self.role)
        if source is None or not target_role:
            return {"CANCELLED"}
        head = _head(context.scene.face_rig_wizard)
        local = head.matrix_world.inverted() @ source.matrix_world.translation
        local.x *= -1.0
        target = _ensure_marker(context, target_role, _front_surface(head, local.x, local.z))
        _select_only(target)
        return {"FINISHED"}


class FACE_RIG_OT_edit_seam(Operator):
    bl_idname = "face_rig.edit_seam"
    bl_label = "Select Mouth Seam Edges"
    bl_description = "Enter Edit Mode and prepare to select the wet-line edge path"

    def execute(self, context):
        head = _head(context.scene.face_rig_wizard)
        if head is None:
            self.report({"ERROR"}, "Assign the Head first")
            return {"CANCELLED"}
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        _select_only(head)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="EDGE")
        context.scene.face_rig_wizard.active_step = "SEAM"
        context.scene.face_rig_wizard.status = (
            "Select a narrow curved band along the wet line from mouth corner to corner. "
            "Branches are okay; if no edge follows the line, use Knife (K) first.")
        return {"FINISHED"}


class FACE_RIG_OT_reconnect_head(Operator):
    bl_idname = "face_rig.reconnect_head"
    bl_label = "Reconnect Exact Split Vertices"
    bl_description = "Merge only exactly coincident export duplicates so a continuous seam can be selected"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Reconnect split export vertices?",
            message="Vertex positions do not move. Existing seam capture and masks will be cleared.")

    def execute(self, context):
        settings = context.scene.face_rig_wizard
        head = _head(settings)
        if head is None:
            self.report({"ERROR"}, "Assign the Head first")
            return {"CANCELLED"}
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        before = len(head.data.vertices)
        bm = bmesh.new()
        bm.from_mesh(head.data)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-7)
        bm.to_mesh(head.data)
        bm.free()
        head.data.update()
        after = len(head.data.vertices)
        if SEAM_PROPERTY in head:
            del head[SEAM_PROPERTY]
        for name in ("FRG_mouth_seam", "FRG_upper_lip", "FRG_lower_lip",
                     "FRG_corners", "FRG_jaw"):
            group = head.vertex_groups.get(name)
            if group is not None:
                head.vertex_groups.remove(group)
        settings.status = (
            "Reconnected %d exact duplicate vertices without moving the surface. "
            "Now create/select the wet-line seam, then regenerate weights." %
            (before - after))
        return {"FINISHED"}


class FACE_RIG_OT_capture_seam(Operator):
    bl_idname = "face_rig.capture_seam"
    bl_label = "Validate Selected Seam"
    bl_description = "Validate and store the selected corner-to-corner edge path"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.face_rig_wizard
        head = _head(settings)
        if head is None or context.object != head or head.mode != "EDIT":
            self.report({"ERROR"}, "Select seam edges on the assigned Head in Edit Mode")
            return {"CANCELLED"}
        bm = bmesh.from_edit_mesh(head.data)
        bm.verts.ensure_lookup_table()
        selected = [edge for edge in bm.edges if edge.select]
        if len(selected) < 5:
            self.report({"ERROR"}, "Select at least five connected mouth-seam edges")
            return {"CANCELLED"}
        right = head.matrix_world.inverted() @ _marker("mouth_corner_R").matrix_world.translation
        left = head.matrix_world.inverted() @ _marker("mouth_corner_L").matrix_world.translation
        guide_rail = []
        for upper_name, lower_name in (
                ("mouth_corner_R", "mouth_corner_R"),
                ("upper_lip_R", "lower_lip_R"),
                ("upper_lip_center", "lower_lip_center"),
                ("upper_lip_L", "lower_lip_L"),
                ("mouth_corner_L", "mouth_corner_L")):
            upper = head.matrix_world.inverted() @ _marker(upper_name).matrix_world.translation
            lower = head.matrix_world.inverted() @ _marker(lower_name).matrix_world.translation
            guide_rail.append((upper + lower) * 0.5)
        try:
            ordered = _best_seam_path(selected, right, left, guide_rail)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            settings.status = str(exc)
            return {"CANCELLED"}

        mouth_width = max((left - right).length, 1e-6)
        first, last = ordered[0].co.copy(), ordered[-1].co.copy()
        direct = (first - right).length + (last - left).length
        reverse = (first - left).length + (last - right).length
        if reverse < direct:
            ordered.reverse()
            first, last = ordered[0].co.copy(), ordered[-1].co.copy()
        endpoint_error = max((first - right).length, (last - left).length)
        span = (last - first).length
        if endpoint_error > 0.20 * mouth_width:
            message = "Seam endpoints must finish at the two mouth-corner guides"
            self.report({"ERROR"}, message); settings.status = message
            return {"CANCELLED"}
        if span < 0.70 * mouth_width:
            message = "Selected seam is too short; trace it from corner to corner"
            self.report({"ERROR"}, message); settings.status = message
            return {"CANCELLED"}

        seam = {
            "validated": True,
            "vertex_indices": [vertex.index for vertex in ordered],
            "local_points": [list(vertex.co) for vertex in ordered],
            "edge_pairs": [[a.index, b.index] for a, b in zip(ordered, ordered[1:])],
            "anchor_endpoints": True,
            "edge_count": len(ordered) - 1,
            "selected_edge_count": len(selected),
            "ignored_edge_count": len(selected) - (len(ordered) - 1),
            "endpoint_error": endpoint_error,
        }
        head[SEAM_PROPERTY] = json.dumps(seam)
        bpy.ops.object.mode_set(mode="OBJECT")
        group = head.vertex_groups.get("FRG_mouth_seam")
        if group is not None:
            head.vertex_groups.remove(group)
        group = head.vertex_groups.new(name="FRG_mouth_seam")
        group.add(seam["vertex_indices"], 1.0, "REPLACE")
        settings.active_step = "MASKS"
        settings.status = (
            "Mouth seam validated: extracted a %d-edge curved path from %d selected "
            "edges. The endpoints stay anchored; %d surrounding branch edges were ignored." %
            (len(ordered) - 1, len(selected), len(selected) - (len(ordered) - 1)))
        return {"FINISHED"}


class FACE_RIG_OT_generate_masks(Operator):
    bl_idname = "face_rig.generate_masks"
    bl_label = "Generate Lip Region Preview"
    bl_description = "Create editable upper/lower lip vertex groups from the guides"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.face_rig_wizard
        head = _head(settings)
        check = _guide_status(context)
        if not check["valid"]:
            self.report({"ERROR"}, "; ".join(check["issues"]))
            return {"CANCELLED"}
        scale = max(head.dimensions)
        radius = 0.060 * scale * settings.lip_influence
        rails = {}
        for side in ("upper", "lower"):
            roles = (("mouth_corner_R", f"{side}_lip_R", f"{side}_lip_center",
                      f"{side}_lip_L", "mouth_corner_L"))
            rails[side] = [head.matrix_world.inverted() @ _marker(role).matrix_world.translation
                           for role in roles]

        def point_segment_distance(point, a, b):
            ab = b - a
            t = max(0.0, min(1.0, (point-a).dot(ab) / max(ab.length_squared, 1e-12)))
            return (point - (a + t * ab)).length

        groups = {}
        for name in ("FRG_upper_lip", "FRG_lower_lip", "FRG_corners", "FRG_jaw"):
            old = head.vertex_groups.get(name)
            if old:
                head.vertex_groups.remove(old)
            groups[name] = head.vertex_groups.new(name=name)
        right = rails["upper"][0]
        left = rails["upper"][-1]
        upper_center = rails["upper"][2]
        lower_center = rails["lower"][2]
        chin = head.matrix_world.inverted() @ _marker("chin_center").matrix_world.translation
        jaw_top = upper_center.z
        lip_span = max(upper_center.z - lower_center.z, 0.012 * scale)
        jaw_bottom = chin.z - 0.45 * max(lower_center.z - chin.z, 1e-6)
        mouth_front = 0.5 * (upper_center.y + lower_center.y)
        for vertex in head.data.vertices:
            co = vertex.co
            distances = {}
            for side in ("upper", "lower"):
                distances[side] = min(point_segment_distance(co, a, b)
                                      for a, b in zip(rails[side], rails[side][1:]))
            for side in ("upper", "lower"):
                distance = distances[side]
                if distance >= radius or distance > distances["lower" if side == "upper" else "upper"]:
                    continue
                t = 1.0 - distance / radius
                weight = t * t * (3.0 - 2.0 * t)
                groups[f"FRG_{side}_lip"].add([vertex.index], weight, "REPLACE")
            corner_distance = min((co-right).length, (co-left).length)
            if corner_distance < 1.25 * radius:
                t = 1.0 - corner_distance / (1.25 * radius)
                groups["FRG_corners"].add([vertex.index], t*t*(3.0-2.0*t), "REPLACE")
            # This is an editable first guess, but unlike the old analytic jaw
            # ramp it becomes the authoritative deformation weight downstream.
            # Limit it to the front facial region so torso/hair shells sharing
            # the same object cannot accidentally follow the jaw.
            if (jaw_bottom <= co.z <= jaw_top
                    and abs(co.x - upper_center.x) <= 1.65 * abs(left.x - right.x) * 0.5
                    and co.y <= mouth_front + 0.16 * scale):
                if co.z >= chin.z:
                    vertical = max(0.0, min(1.0,
                        (jaw_top - co.z) / (1.15 * lip_span)))
                else:
                    vertical = max(0.0, min(1.0,
                        (co.z - jaw_bottom) / max(chin.z - jaw_bottom, 1e-6)))
                vertical = vertical * vertical * (3.0 - 2.0 * vertical)
                depth = max(0.0, min(1.0,
                    1.0 - max(0.0, co.y - mouth_front) / (0.16 * scale)))
                weight = vertical * depth
                groups["FRG_jaw"].add([vertex.index], weight, "REPLACE")
        settings.active_step = "MASKS"
        settings.status = ("Direct lip and jaw groups created. Review all three: the upper "
                           "lip stays static, while lower lip, chin and jaw fade smoothly.")
        return {"FINISHED"}


class FACE_RIG_OT_show_group(Operator):
    bl_idname = "face_rig.show_group"
    bl_label = "Show Region"
    group: StringProperty()

    def execute(self, context):
        head = _head(context.scene.face_rig_wizard)
        group = head.vertex_groups.get(self.group) if head else None
        if group is None:
            return {"CANCELLED"}
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        _select_only(head)
        head.vertex_groups.active_index = group.index
        try:
            bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
        except RuntimeError:
            pass
        context.scene.face_rig_wizard.status = (
            "Weight Paint is active. Red is strong influence; blue is none. "
            "Use Draw/Subtract sparingly, then return to Object Mode.")
        return {"FINISHED"}


class FACE_RIG_OT_save_guide(Operator):
    bl_idname = "face_rig.save_guide"
    bl_label = "Validate and Save Guide"

    def execute(self, context):
        settings = context.scene.face_rig_wizard
        check = _guide_status(context)
        if not check["valid"]:
            self.report({"ERROR"}, "; ".join(check["issues"]))
            settings.status = "Guide needs correction: " + "; ".join(check["issues"])
            return {"CANCELLED"}
        path = bpy.path.abspath(settings.guide_path or _default_guide_path())
        core = _core(context)
        core.save(path, _gather_guide(context))
        settings.guide_path = path
        settings.status = "Guide validated and saved: " + path
        self.report({"INFO"}, "Face guide saved")
        return {"FINISHED"}


class FACE_RIG_OT_load_guide(Operator):
    bl_idname = "face_rig.load_guide"
    bl_label = "Load Guide"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.face_rig_wizard
        path = bpy.path.abspath(settings.guide_path)
        try:
            guide = _core(context).load(path)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        objects = guide.get("objects") or {}
        settings.head = bpy.data.objects.get(objects.get("head"))
        settings.upper_teeth = bpy.data.objects.get(objects.get("upper_teeth"))
        settings.lower_teeth = bpy.data.objects.get(objects.get("lower_teeth"))
        settings.tongue = bpy.data.objects.get(objects.get("tongue"))
        for role, data in (guide.get("markers") or {}).items():
            if role in MARKER_MAP:
                _ensure_marker(context, role, data["local"])
        head = _head(settings)
        seam = (guide.get("topology") or {}).get("mouth_seam") or {}
        if head is not None and seam:
            head[SEAM_PROPERTY] = json.dumps(seam)
        if head is not None:
            for name, values in (guide.get("masks") or {}).items():
                group = head.vertex_groups.get(name)
                if group is not None:
                    head.vertex_groups.remove(group)
                group = head.vertex_groups.new(name=name)
                for index, weight in values.items():
                    vertex_index = int(index)
                    if vertex_index < len(head.data.vertices):
                        group.add([vertex_index], float(weight), "REPLACE")
        values = guide.get("settings") or {}
        for name in ("lip_influence", "jaw_open_deg", "pucker_strength",
                     "funnel_strength", "smile_strength"):
            if name in values:
                setattr(settings, name, values[name])
        settings.status = "Guide loaded. Inspect its markers, seam and direct weights before building."
        return {"FINISHED"}


class FACE_RIG_OT_build_copy(Operator):
    bl_idname = "face_rig.build_copy"
    bl_label = "Build Guided Rig Copy"
    bl_description = "Save this source Blend and run the pipeline into a new file"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Build Guided Rig Copy?",
            message="The current source Blend and guide will be saved first.")

    def execute(self, context):
        global _build_process
        settings = context.scene.face_rig_wizard
        if _build_process is not None and _build_process.poll() is None:
            self.report({"WARNING"}, "A build is already running")
            return {"CANCELLED"}
        if not bpy.data.filepath:
            self.report({"ERROR"}, "Save the source .blend once before building")
            return {"CANCELLED"}
        check = _build_status(context)
        if not check["valid"]:
            self.report({"ERROR"}, "; ".join(check["issues"]))
            return {"CANCELLED"}
        guide_path = bpy.path.abspath(settings.guide_path or _default_guide_path())
        _core(context).save(guide_path, _gather_guide(context))
        settings.guide_path = guide_path
        repo = _repo_path(context)
        output = bpy.path.abspath(settings.output_path) if settings.output_path else ""
        if not output:
            output = os.path.splitext(bpy.data.filepath)[0] + "_calibration.blend"
            settings.output_path = output
        settings.active_step = "BUILD"
        settings.status = "Launching topology-preserving calibration build."
        # Save the BUILD tab and output path into the source before the
        # background process opens it; the resulting calibration copy then
        # opens directly on the pose-review controls.
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
        report_path = os.path.splitext(output)[0] + ".json"
        command = [bpy.app.binary_path, bpy.data.filepath, "--background",
                   "--python", os.path.join(repo, "autorig.py"), "--",
                   "--face-guide", guide_path, "--weld-coincident", "--align",
                   "--split-seam", "--calibration-only",
                   "--open-deg", str(settings.jaw_open_deg),
                   "--arkit", "--out", output, "--json", report_path]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        _build_process = subprocess.Popen(command, cwd=repo, creationflags=creationflags)
        settings.status = ("Building a topology-preserving calibration copy. "
                           "Use Check Build Status in a moment.")
        return {"FINISHED"}


class FACE_RIG_OT_check_build(Operator):
    bl_idname = "face_rig.check_build"
    bl_label = "Check Build Status"

    def execute(self, context):
        global _build_process
        settings = context.scene.face_rig_wizard
        if _build_process is None:
            settings.status = "No build has been started in this Blender session."
        elif _build_process.poll() is None:
            settings.status = "Build is still running."
        elif _build_process.returncode == 0:
            settings.status = "Calibration built. Open it and approve or sculpt the six poses."
        else:
            settings.status = ("Calibration saved with validation warnings (exit %d). "
                               "Open it for visual review and inspect the JSON report." %
                               _build_process.returncode)
        return {"FINISHED"}


class FACE_RIG_OT_open_result(Operator):
    bl_idname = "face_rig.open_result"
    bl_label = "Open Rigged Copy"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Open Rigged Copy?",
            message="Unsaved changes in the current file will be lost.")

    def execute(self, context):
        path = bpy.path.abspath(context.scene.face_rig_wizard.output_path)
        if not os.path.exists(path):
            self.report({"ERROR"}, "Rigged output does not exist yet")
            return {"CANCELLED"}
        bpy.ops.wm.open_mainfile(filepath=path)
        return {"FINISHED"}


class FACE_RIG_OT_preview_pose(Operator):
    bl_idname = "face_rig.preview_pose"
    bl_label = "Preview Calibration Pose"
    pose: StringProperty()

    def execute(self, context):
        settings = context.scene.face_rig_wizard
        head = _head(settings)
        if head is None or head.data.shape_keys is None:
            self.report({"ERROR"}, "Open the rigged copy first")
            return {"CANCELLED"}
        keys = head.data.shape_keys.key_blocks
        names = ("jawOpen", "mouthClose", "mouthFunnel", "mouthPucker",
                 "mouthSmileLeft", "mouthSmileRight")
        for name in names:
            key = keys.get(name)
            if key:
                key.value = 0.0
        if self.pose != "neutral":
            key = keys.get(self.pose)
            if key is None:
                self.report({"ERROR"}, "Shape key %s is missing" % self.pose)
                return {"CANCELLED"}
            key.value = 1.0
        settings.status = ("Inspect the lips from front and three-quarter views. "
                           "If this pose is wrong, return to the source guide and adjust markers/settings.")
        return {"FINISHED"}


class FACE_RIG_OT_sculpt_pose(Operator):
    bl_idname = "face_rig.sculpt_pose"
    bl_label = "Sculpt Calibration Pose"
    bl_description = "Activate this shape key at full value and enter Sculpt Mode"
    pose: StringProperty()

    def execute(self, context):
        settings = context.scene.face_rig_wizard
        head = _head(settings)
        if head is None or head.data.shape_keys is None:
            self.report({"ERROR"}, "Open the calibration copy first")
            return {"CANCELLED"}
        keys = head.data.shape_keys.key_blocks
        key = keys.get(self.pose)
        if key is None:
            self.report({"ERROR"}, "Calibration key %s is missing" % self.pose)
            return {"CANCELLED"}
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        _select_only(head)
        for candidate in keys:
            if candidate.name != "Basis":
                candidate.value = 0.0
        head.active_shape_key_index = keys.find(self.pose)
        key.value = 1.0
        try:
            bpy.ops.object.mode_set(mode="SCULPT")
        except RuntimeError as exc:
            self.report({"ERROR"}, "Could not enter Sculpt Mode: %s" % exc)
            return {"CANCELLED"}
        settings.status = (
            "Sculpting %s. Use Grab/Smooth gently around the mouth only; do not "
            "change Basis. Return to Object Mode when satisfied." % self.pose)
        return {"FINISHED"}


class FACE_RIG_OT_approve_calibration(Operator):
    bl_idname = "face_rig.approve_calibration"
    bl_label = "Approve Calibration Poses"
    bl_description = "Mark the six inspected/sculpted poses ready for ARKit finalization"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Approve calibration?",
            message="Confirm Neutral and all six calibration poses look acceptable.")

    def execute(self, context):
        settings = context.scene.face_rig_wizard
        head = _head(settings)
        if head is None or head.data.shape_keys is None:
            self.report({"ERROR"}, "Open the calibration copy first")
            return {"CANCELLED"}
        missing = [name for name in CALIBRATION_KEYS
                   if head.data.shape_keys.key_blocks.get(name) is None]
        if missing:
            self.report({"ERROR"}, "Missing calibration keys: " + ", ".join(missing))
            return {"CANCELLED"}
        if not head.get("face_rig_explicit_seam", False):
            self.report({"ERROR"}, "This file was not built from a validated explicit seam")
            return {"CANCELLED"}
        expected_basis = head.get("face_rig_basis_signature")
        if not expected_basis or _basis_signature(head) != expected_basis:
            self.report({"ERROR"},
                        "Basis changed after calibration build; rebuild and sculpt pose keys only")
            return {"CANCELLED"}
        for key in head.data.shape_keys.key_blocks:
            if key.name != "Basis":
                key.value = 0.0
        head["face_rig_calibration_approved"] = True
        head["face_rig_calibration_keys"] = json.dumps(list(CALIBRATION_KEYS))
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
        settings.status = (
            "Calibration approved and saved. Finalize ARKit to generate the remaining "
            "expressions while preserving your six corrective shapes.")
        return {"FINISHED"}


class FACE_RIG_OT_finalize(Operator):
    bl_idname = "face_rig.finalize"
    bl_label = "Finalize ARKit 52 Rig"
    bl_description = "Generate remaining ARKit/VRChat shapes while preserving approved correctives"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Finalize ARKit rig?",
            message="A new final Blend will be saved; approved corrective shapes are preserved.")

    def execute(self, context):
        settings = context.scene.face_rig_wizard
        head = _head(settings)
        if head is None or not head.get("face_rig_calibration_approved", False):
            self.report({"ERROR"}, "Approve the calibration poses first")
            return {"CANCELLED"}
        if _basis_signature(head) != head.get("face_rig_basis_signature"):
            self.report({"ERROR"}, "Basis changed after approval; finalization stopped")
            return {"CANCELLED"}
        profile_json = head.get("face_rig_profile_json")
        if not profile_json:
            self.report({"ERROR"}, "Calibration profile is missing; rebuild the calibration copy")
            return {"CANCELLED"}
        armature_name = head.get("face_rig_armature", "face_rig")
        armature = bpy.data.objects.get(armature_name)
        if armature is None:
            self.report({"ERROR"}, "Calibration armature is missing")
            return {"CANCELLED"}
        repo = _repo_path(context)
        if repo not in sys.path:
            sys.path.insert(0, repo)
        from tripo_face_rig import expressions
        profile = json.loads(profile_json)
        tongue = bpy.data.objects.get(head.get("face_rig_tongue", "tongue"))
        report = expressions.generate(
            head, armature, profile, tongue_obj=tongue, include_vrc=True,
            preserve_existing=set(CALIBRATION_KEYS))
        if report["arkit_nonempty"] != report["arkit_required"]:
            self.report({"ERROR"}, "Finalization left empty ARKit expressions")
            return {"CANCELLED"}
        output = bpy.path.abspath(settings.final_output_path) if settings.final_output_path else ""
        if not output:
            stem = os.path.splitext(bpy.data.filepath)[0]
            if stem.endswith("_calibration"):
                stem = stem[:-len("_calibration")]
            output = stem + "_arkit_final.blend"
            settings.final_output_path = output
        head["face_rig_finalized"] = True
        head["face_rig_arkit_count"] = report["arkit_nonempty"]
        bpy.ops.wm.save_as_mainfile(filepath=output)
        settings.status = "Final ARKit 52 + VRChat rig saved: " + output
        return {"FINISHED"}


class FACE_RIG_PT_wizard(Panel):
    bl_label = "Face Rig Wizard"
    bl_idname = "FACE_RIG_PT_wizard"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Face Rig"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.face_rig_wizard
        layout.prop(settings, "active_step", expand=True)
        status = layout.box()
        status.label(text="Feedback", icon="INFO")
        for line in _wrap(settings.status, 48):
            status.label(text=line)

        if settings.active_step == "OBJECTS":
            self.draw_objects(layout, settings)
        elif settings.active_step == "MOUTH":
            self.draw_mouth(layout, settings)
        elif settings.active_step == "SEAM":
            self.draw_seam(layout, settings)
        elif settings.active_step == "MASKS":
            self.draw_masks(layout, settings)
        else:
            self.draw_build(layout, settings)

    def draw_objects(self, layout, settings):
        box = layout.box()
        box.label(text="Step 1: Assign Character Objects", icon="OUTLINER_OB_MESH")
        box.label(text="Select an object in the viewport or Outliner,")
        box.label(text="then use the matching Assign button.")
        for prop, target, label in (("head", "HEAD", "Head / face mesh"),
                                    ("upper_teeth", "UPPER", "Upper teeth"),
                                    ("lower_teeth", "LOWER", "Lower teeth"),
                                    ("tongue", "TONGUE", "Tongue")):
            row = box.row(align=True)
            row.prop(settings, prop, text=label)
            op = row.operator("face_rig.assign_selected", text="Assign")
            op.target = target
        box.operator("face_rig.auto_seed", icon="TRACKING")
        box.label(text="Dental objects make the first guess more accurate.", icon="LIGHTBULB")

    def draw_mouth(self, layout, settings):
        box = layout.box()
        box.label(text="Step 2: Correct the Mouth Guides", icon="EMPTY_AXIS")
        for line in ("Work in Front Orthographic view first (Numpad 1).",
                     "Use Place to click the surface, or select a guide and press G.",
                     "Check a side view: guides must sit on the visible skin, not teeth."):
            box.label(text=line)
        box.operator("face_rig.auto_seed", text="Reset Automatic Guess", icon="FILE_REFRESH")
        for role, label, help_text in MARKERS:
            row = box.row(align=True)
            row.label(text=label, icon="CHECKMARK" if _marker(role) else "RADIOBUT_OFF")
            op = row.operator("face_rig.place_marker", text="Place")
            op.role = role
            if role in PAIRS:
                mirror = row.operator("face_rig.mirror_marker", text="Mirror")
                mirror.role = role
            hint = box.row()
            hint.scale_y = 0.72
            hint.label(text=help_text)
        row = box.row(align=True)
        row.prop(settings, "guide_path")
        row.operator("face_rig.load_guide", text="Load")
        box.operator("face_rig.save_guide", icon="CHECKMARK")
        box.operator("face_rig.edit_seam", icon="EDGESEL")

    def draw_seam(self, layout, settings):
        box = layout.box()
        box.label(text="Step 3: Author the Mouth Opening", icon="EDGESEL")
        for line in ("The neutral face will not be reshaped or subdivided.",
                     "Select a narrow curved edge band along the wet line.",
                     "Start at one corner guide and finish at the other."):
            box.label(text=line)
        help_box = box.box()
        help_box.label(text="If no suitable edge path exists:", icon="QUESTION")
        help_box.label(text="1. Front view, Tab into Edit Mode, press K for Knife.")
        help_box.label(text="2. Trace the visible lip contact line corner-to-corner.")
        help_box.label(text="3. Press Enter, then select only the new seam edges.")
        box.operator("face_rig.reconnect_head", icon="AUTOMERGE_ON")
        box.operator("face_rig.edit_seam", icon="EDITMODE_HLT")
        box.operator("face_rig.capture_seam", icon="CHECKMARK")
        head = _head(settings)
        seam = json.loads(head.get(SEAM_PROPERTY, "{}")) if head else {}
        if seam.get("validated"):
            box.label(text="Validated: %d edges" % seam.get("edge_count", 0),
                      icon="CHECKMARK")

    def draw_masks(self, layout, settings):
        box = layout.box()
        box.label(text="Step 3: Review Lip Regions", icon="WPAINT_HLT")
        box.label(text="Red should cover the lip; blue should be unaffected skin.")
        box.label(text="Minor imprecision is fine. Correct only obvious mistakes.")
        row = box.row(align=True)
        op = row.operator("face_rig.show_group", text="Show Upper Lip")
        op.group = "FRG_upper_lip"
        op = row.operator("face_rig.show_group", text="Show Lower Lip")
        op.group = "FRG_lower_lip"
        op = box.operator("face_rig.show_group", text="Show Direct Jaw / Chin Weight")
        op.group = "FRG_jaw"
        box.prop(settings, "lip_influence")
        box.operator("face_rig.generate_masks", text="Regenerate with New Influence")
        help_box = box.box()
        help_box.label(text="Basic correction:", icon="QUESTION")
        help_box.label(text="1. Use Draw to add influence; hold Ctrl to subtract.")
        help_box.label(text="2. Upper lip must stay out of the jaw group.")
        help_box.label(text="3. Lower lip/chin are red; fade to blue before the neck.")
        help_box.label(text="4. Return to Object Mode when finished.")
        box.operator("face_rig.save_guide", icon="CHECKMARK")
        box.operator("face_rig.build_copy", icon="MOD_ARMATURE")

    def draw_build(self, layout, settings):
        box = layout.box()
        box.label(text="Step 5: Build, Sculpt, Approve", icon="MOD_ARMATURE")
        box.prop(settings, "jaw_open_deg")
        box.prop(settings, "pucker_strength")
        box.prop(settings, "funnel_strength")
        box.prop(settings, "smile_strength")
        box.prop(settings, "output_path")
        box.operator("face_rig.build_copy", text="Build Calibration Copy", icon="MOD_ARMATURE")
        row = box.row(align=True)
        row.operator("face_rig.check_build", icon="TIME")
        row.operator("face_rig.open_result", icon="FILE_BLEND")
        preview = layout.box()
        preview.label(text="Calibration Poses", icon="SHAPEKEY_DATA")
        preview.label(text="Open the calibration copy; inspect these one at a time.")
        for label, pose in (("Neutral", "neutral"), ("Jaw Open", "jawOpen"),
                            ("Mouth Close", "mouthClose"), ("Funnel", "mouthFunnel"),
                            ("Pucker", "mouthPucker"), ("Smile Left", "mouthSmileLeft")):
            op = preview.operator("face_rig.preview_pose", text=label)
            op.pose = pose
            if pose in CALIBRATION_KEYS:
                sculpt = preview.operator("face_rig.sculpt_pose", text="Sculpt " + label)
                sculpt.pose = pose
        note = preview.box()
        note.label(text="Good result checklist:", icon="CHECKMARK")
        note.label(text="No teeth pierce the lips; corners do not tear.")
        note.label(text="Upper lip stays mostly still during Jaw Open.")
        note.label(text="Funnel is rounded; Pucker moves forward and inward.")
        approve = layout.box()
        approve.label(text="Approval Gate", icon="CHECKMARK")
        approve.label(text="The remaining expressions cannot be finalized first.")
        approve.operator("face_rig.approve_calibration", icon="CHECKMARK")
        approve.prop(settings, "final_output_path")
        approve.operator("face_rig.finalize", icon="SHAPEKEY_DATA")


def _wrap(text, width):
    words = (text or "").split()
    lines, line = [], []
    for word in words:
        if line and len(" ".join(line + [word])) > width:
            lines.append(" ".join(line)); line = [word]
        else:
            line.append(word)
    if line:
        lines.append(" ".join(line))
    return lines or [""]


CLASSES = (
    FACE_RIG_AddonPreferences, FACE_RIG_Settings,
    FACE_RIG_OT_assign_selected, FACE_RIG_OT_auto_seed,
    FACE_RIG_OT_place_marker, FACE_RIG_OT_mirror_marker,
    FACE_RIG_OT_edit_seam, FACE_RIG_OT_reconnect_head,
    FACE_RIG_OT_capture_seam,
    FACE_RIG_OT_generate_masks, FACE_RIG_OT_show_group,
    FACE_RIG_OT_save_guide, FACE_RIG_OT_load_guide,
    FACE_RIG_OT_build_copy, FACE_RIG_OT_check_build,
    FACE_RIG_OT_open_result, FACE_RIG_OT_preview_pose,
    FACE_RIG_OT_sculpt_pose, FACE_RIG_OT_approve_calibration,
    FACE_RIG_OT_finalize,
    FACE_RIG_PT_wizard,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.face_rig_wizard = PointerProperty(type=FACE_RIG_Settings)


def unregister():
    if hasattr(bpy.types.Scene, "face_rig_wizard"):
        del bpy.types.Scene.face_rig_wizard
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
