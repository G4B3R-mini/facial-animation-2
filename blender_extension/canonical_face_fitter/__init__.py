bl_info = {
    "name": "Canonical Face Fitter",
    "author": "Local pipeline; canonical model by USC ICT",
    "version": (0, 3, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Canonical Face",
    "description": "Landmark-fit a reusable ARKit face; never cuts the source mesh",
    "category": "Rigging",
}

import os
from pathlib import Path
import sys

import bpy
import numpy as np
from bpy_extras import view3d_utils
from bpy.props import FloatProperty, PointerProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup
from mathutils import Matrix, Vector


COLLECTION = "Canonical Face Guides"
GUIDES = (
    ("jaw_R", "Right jaw", "Side of the jaw, below the right mouth corner."),
    ("chin_center", "Chin", "Lowest front-center point of the chin."),
    ("jaw_L", "Left jaw", "Side of the jaw, below the left mouth corner."),
    ("brow_outer_R", "Right brow outer", "Outer end of the eyebrow ridge."),
    ("brow_inner_R", "Right brow inner", "Inner end of the eyebrow ridge."),
    ("brow_inner_L", "Left brow inner", "Inner end of the eyebrow ridge."),
    ("brow_outer_L", "Left brow outer", "Outer end of the eyebrow ridge."),
    ("nose_bridge", "Nose bridge", "Center of the bridge between the eyes."),
    ("nose_tip", "Nose tip", "Front-center tip of the nose."),
    ("nostril_R", "Right nostril", "Outside of the right nostril wing."),
    ("nostril_L", "Left nostril", "Outside of the left nostril wing."),
    ("eye_outer_R", "Right eye outer", "Outer eyelid corner, not the eyeball."),
    ("eye_inner_R", "Right eye inner", "Inner eyelid corner."),
    ("eye_inner_L", "Left eye inner", "Inner eyelid corner."),
    ("eye_outer_L", "Left eye outer", "Outer eyelid corner, not the eyeball."),
    ("mouth_corner_R", "Right mouth corner", "Exact lip commissure."),
    ("upper_lip_R", "Upper lip right", "Upper vermilion ridge halfway to corner."),
    ("upper_lip_center", "Upper lip center", "Center of the upper vermilion ridge."),
    ("upper_lip_L", "Upper lip left", "Upper vermilion ridge halfway to corner."),
    ("mouth_corner_L", "Left mouth corner", "Exact lip commissure."),
    ("lower_lip_R", "Lower lip right", "Lower vermilion ridge halfway to corner."),
    ("lower_lip_center", "Lower lip center", "Center of the lower vermilion ridge."),
    ("lower_lip_L", "Lower lip left", "Lower vermilion ridge halfway to corner."),
    ("forehead_center", "Forehead / hairline", "Center of the facial-mask boundary at the hairline."),
    ("hairline_R", "Right hairline", "Upper-right facial-mask boundary at the hairline."),
    ("hairline_L", "Left hairline", "Upper-left facial-mask boundary at the hairline."),
    ("temple_R", "Right temple", "Right facial-mask boundary beside the forehead."),
    ("temple_L", "Left temple", "Left facial-mask boundary beside the forehead."),
    ("neck_R", "Right neck boundary", "Right lower boundary below the jaw."),
    ("neck_center", "Neck center", "Front-center lower boundary below the chin."),
    ("neck_L", "Left neck boundary", "Left lower boundary below the jaw."),
)


def _default_repo():
    candidate = Path(__file__).resolve().parents[2]
    return str(candidate) if (candidate / "autorig.py").is_file() else ""


def _addon_key():
    return __package__ or __name__


def _repo(context):
    addon = context.preferences.addons.get(_addon_key())
    path = addon.preferences.repo_path if addon else _default_repo()
    return os.path.abspath(bpy.path.abspath(path))


def _core(context):
    repo = _repo(context)
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from tripo_face_rig import canonical
    return canonical


def _collection(scene):
    value = bpy.data.collections.get(COLLECTION)
    if value is None:
        value = bpy.data.collections.new(COLLECTION)
        scene.collection.children.link(value)
    return value


def _guide(role):
    # Reuse the nine guides from the abandoned wizard when present.
    for obj in bpy.data.objects:
        if obj.get("canonical_guide_role") == role or obj.get("face_guide_role") == role:
            return obj
    return None


def _head(settings):
    return settings.head if settings.head and settings.head.type == "MESH" else None


def _local_guide(head, role):
    obj = _guide(role)
    return head.matrix_world.inverted() @ obj.matrix_world.translation if obj else None


def _ensure_guide(context, role, local):
    head = _head(context.scene.canonical_face_fit)
    obj = _guide(role)
    if obj is None or obj.get("face_guide_role"):
        # Existing FRG guides remain owned by the legacy file. Reuse them in
        # place, but create only missing guides under the new namespace.
        if obj is not None:
            return obj
        obj = bpy.data.objects.new("CFG_" + role, None)
        _collection(context.scene).objects.link(obj)
        obj["canonical_guide_role"] = role
        obj.empty_display_type = "SPHERE"
    obj.parent = head
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.location = local
    obj.empty_display_size = max(head.dimensions) * 0.009
    obj.show_in_front = True
    obj.color = (0.05, 0.8, 1.0, 1.0)
    return obj


def _front_surface(head, x, z):
    candidates = sorted(head.data.vertices,
                        key=lambda v: (v.co.x - x) ** 2 + (v.co.z - z) ** 2)[:36]
    if not candidates:
        return Vector((x, 0.0, z))
    # -Y is forward in this pipeline.
    return min(candidates, key=lambda v: v.co.y).co.copy()


def _affine_seed(source, target):
    roles = [role for role in source if role in target]
    if len(roles) < 4:
        return None
    a = np.asarray([[1.0, *source[role]] for role in roles], dtype=np.float64)
    b = np.asarray([target[role] for role in roles], dtype=np.float64)
    return np.linalg.lstsq(a, b, rcond=1e-10)[0]


class CFG_Preferences(AddonPreferences):
    bl_idname = _addon_key()
    repo_path: StringProperty(name="Pipeline repository", subtype="DIR_PATH",
                              default=_default_repo())

    def draw(self, _context):
        self.layout.prop(self, "repo_path")


class CFG_Settings(PropertyGroup):
    head: PointerProperty(name="Generated Head", type=bpy.types.Object)
    status: StringProperty(name="Status", default="Assign the generated head to begin.")
    regularization: FloatProperty(name="Fit Smoothness", default=0.0001,
                                  min=0.000001, max=0.05, precision=5)


class CFG_OT_assign_head(Operator):
    bl_idname = "canonical_face.assign_head"
    bl_label = "Use Selected as Generated Head"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "Select the generated character mesh")
            return {"CANCELLED"}
        context.scene.canonical_face_fit.head = obj
        context.scene.canonical_face_fit.status = "Head assigned. Create the guide first guess."
        return {"FINISHED"}


class CFG_OT_seed_guides(Operator):
    bl_idname = "canonical_face.seed_guides"
    bl_label = "Create Guide First Guess"
    bl_description = "Reuse old mouth guides and seed the remaining facial landmarks"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.canonical_face_fit
        head = _head(settings)
        if head is None:
            self.report({"ERROR"}, "Assign the generated head first")
            return {"CANCELLED"}
        source = _core(context).source_landmarks(_repo(context))
        existing = {role: _local_guide(head, role) for role, _label, _help in GUIDES}
        existing = {role: point for role, point in existing.items() if point is not None}
        transform = _affine_seed(source, existing)
        corners = [Vector(corner) for corner in head.bound_box]
        centre_x = 0.5 * (min(p.x for p in corners) + max(p.x for p in corners))
        z_min, z_max = min(p.z for p in corners), max(p.z for p in corners)
        height = z_max - z_min
        created = 0
        for role, _label, _help in GUIDES:
            if _guide(role):
                continue
            if transform is not None:
                guess = np.asarray([1.0, *source[role]], dtype=np.float64) @ transform
                local = _front_surface(head, float(guess[0]), float(guess[2]))
            else:
                # Crude fallback only until four artist guides exist.
                sx = source[role].x / 15.0
                sz = source[role].z / 15.0
                local = _front_surface(head, centre_x + sx * 0.55 * height,
                                       z_min + 0.52 * height + sz * 0.55 * height)
            _ensure_guide(context, role, local)
            created += 1
        settings.status = (f"{created} guides created. Correct eye corners, nose, mouth, "
                           "jaw, and chin; then build the fit preview.")
        return {"FINISHED"}


class CFG_OT_place_guide(Operator):
    bl_idname = "canonical_face.place_guide"
    bl_label = "Place Guide"
    bl_options = {"REGISTER", "UNDO"}
    role: StringProperty()

    def invoke(self, context, _event):
        if context.area.type != "VIEW_3D" or _head(context.scene.canonical_face_fit) is None:
            self.report({"ERROR"}, "Run this in a 3D View after assigning the head")
            return {"CANCELLED"}
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set("Click the visible skin surface. Esc cancels.")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            context.workspace.status_text_set(None)
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            head = _head(context.scene.canonical_face_fit)
            coord = (event.mouse_region_x, event.mouse_region_y)
            origin = view3d_utils.region_2d_to_origin_3d(context.region, context.region_data, coord)
            direction = view3d_utils.region_2d_to_vector_3d(context.region, context.region_data, coord)
            inverse = head.matrix_world.inverted()
            hit, location, _normal, _face = head.ray_cast(
                inverse @ origin, (inverse.to_3x3() @ direction).normalized())
            if not hit:
                self.report({"WARNING"}, "No generated-head surface under the cursor")
                return {"RUNNING_MODAL"}
            obj = _ensure_guide(context, self.role, location)
            for other in context.selected_objects:
                other.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
            context.workspace.status_text_set(None)
            return {"FINISHED"}
        return {"RUNNING_MODAL"}


class CFG_OT_build_preview(Operator):
    bl_idname = "canonical_face.build_preview"
    bl_label = "Build Canonical Fit Preview"
    bl_description = "Create a new fitted ARKit face; the generated mesh is never modified"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.canonical_face_fit
        head = _head(settings)
        if head is None:
            self.report({"ERROR"}, "Assign the generated head first")
            return {"CANCELLED"}
        core = _core(context)
        old = bpy.data.objects.get(core.CANONICAL_OBJECT)
        if old is not None and old.get("canonical_source"):
            bpy.data.objects.remove(old, do_unlink=True)
        target = {}
        for role, _label, _help in GUIDES:
            point = _local_guide(head, role)
            if point is not None:
                target[role] = point
        try:
            canonical = core.create_canonical(_repo(context), expressions=True)
            result = core.fit_object(canonical, _repo(context), target,
                                     regularization=settings.regularization)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        canonical.matrix_world = head.matrix_world.copy()
        material = bpy.data.materials.get("CFG_FitPreview") or bpy.data.materials.new("CFG_FitPreview")
        material.diffuse_color = (0.12, 0.46, 0.8, 1.0)
        material.metallic = 0.0
        material.roughness = 0.48
        canonical.data.materials.append(material)
        canonical.show_in_front = True
        settings.status = (f"Fit built from {result['guides']} guides with "
                           f"{result['shape_keys'] - 1} reusable expressions. "
                           "Inspect the blue mesh and six diagnostic poses.")
        for obj in context.selected_objects:
            obj.select_set(False)
        canonical.select_set(True)
        context.view_layer.objects.active = canonical
        return {"FINISHED"}


class CFG_OT_preview_pose(Operator):
    bl_idname = "canonical_face.preview_pose"
    bl_label = "Preview Pose"
    bl_options = {"REGISTER", "UNDO"}
    pose: StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(_core(context).CANONICAL_OBJECT)
        if obj is None or obj.data.shape_keys is None:
            self.report({"ERROR"}, "Build the canonical fit preview first")
            return {"CANCELLED"}
        for key in obj.data.shape_keys.key_blocks:
            if key.name != "Basis":
                key.value = 1.0 if key.name == self.pose else 0.0
        context.scene.canonical_face_fit.status = "Previewing " + self.pose
        return {"FINISHED"}


class CFG_OT_reset_pose(Operator):
    bl_idname = "canonical_face.reset_pose"
    bl_label = "Neutral"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = bpy.data.objects.get(_core(context).CANONICAL_OBJECT)
        if obj and obj.data.shape_keys:
            for key in obj.data.shape_keys.key_blocks:
                key.value = 0.0
        return {"FINISHED"}


class CFG_PT_panel(Panel):
    bl_label = "Canonical Face Fitter"
    bl_idname = "CFG_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Canonical Face"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.canonical_face_fit
        notice = layout.box()
        notice.label(text="Does not cut or weight-paint the generated mesh.", icon="INFO")
        notice.label(text="Blue mesh is a non-destructive fit preview.")
        layout.prop(settings, "head")
        layout.operator("canonical_face.assign_head", icon="EYEDROPPER")
        layout.operator("canonical_face.seed_guides", icon="EMPTY_AXIS")
        guides = layout.box()
        guides.label(text="Correct these guides", icon="TRACKING")
        for role, label, help_text in GUIDES:
            row = guides.row(align=True)
            row.label(text=label, icon="CHECKMARK" if _guide(role) else "RADIOBUT_OFF")
            op = row.operator("canonical_face.place_guide", text="Place")
            op.role = role
            row.operator("object.select_pattern", text="Select").pattern = (
                _guide(role).name if _guide(role) else "__missing__")
            row = guides.row()
            row.scale_y = 0.65
            row.label(text=help_text)
        fit = layout.box()
        fit.label(text="Fit and inspect", icon="SHAPEKEY_DATA")
        fit.prop(settings, "regularization")
        fit.operator("canonical_face.build_preview", icon="MOD_SHRINKWRAP")
        row = fit.row(align=True)
        row.operator("canonical_face.reset_pose", text="Neutral")
        for pose in _core(context).diagnostic_key_names():
            op = fit.operator("canonical_face.preview_pose", text=pose)
            op.pose = pose
        status = layout.box()
        status.label(text="Status")
        status.label(text=settings.status)


CLASSES = (CFG_Preferences, CFG_Settings, CFG_OT_assign_head, CFG_OT_seed_guides,
           CFG_OT_place_guide, CFG_OT_build_preview, CFG_OT_preview_pose,
           CFG_OT_reset_pose, CFG_PT_panel)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.canonical_face_fit = PointerProperty(type=CFG_Settings)


def unregister():
    del bpy.types.Scene.canonical_face_fit
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
