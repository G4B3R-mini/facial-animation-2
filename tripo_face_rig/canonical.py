"""Landmark-guided fitting of the MIT-licensed ICT FaceKit topology.

This module deliberately leaves the generated character mesh untouched.  The
canonical neutral and every expression are passed through the same smooth
warp, so topology, UVs, mouth volume, and expression deltas remain coherent.
"""

from __future__ import annotations

import json
import os

import bpy
import numpy as np
from mathutils import Vector


# The complete connected facial skin. The smaller ICT "narrow face" prefix
# leaves artificial holes in the forehead; the full skin is the correct
# production source even though its 9.2k faces are above the initial 5k target.
ICT_VERTEX_LIMIT = 9409
CANONICAL_OBJECT = "CFG_CanonicalFace"

# Multi-PIE 68 landmark number for each concise artist-facing guide.
LANDMARKS = {
    "jaw_R": 4,
    "chin_center": 8,
    "jaw_L": 12,
    "brow_outer_R": 17,
    "brow_inner_R": 21,
    "brow_inner_L": 22,
    "brow_outer_L": 26,
    "nose_bridge": 27,
    "nose_tip": 30,
    "nostril_R": 31,
    "nostril_L": 35,
    "eye_outer_R": 36,
    "eye_inner_R": 39,
    "eye_inner_L": 42,
    "eye_outer_L": 45,
    "mouth_corner_R": 48,
    "upper_lip_R": 50,
    "upper_lip_center": 51,
    "upper_lip_L": 52,
    "mouth_corner_L": 54,
    "lower_lip_L": 56,
    "lower_lip_center": 57,
    "lower_lip_R": 58,
    # Boundary anchors prevent the thin-plate spline from extrapolating the
    # facial mask past the scalp and neck. These are direct ICT vertex indices.
    "forehead_center": None,
    "hairline_R": None,
    "hairline_L": None,
    "temple_R": None,
    "temple_L": None,
    "neck_R": None,
    "neck_center": None,
    "neck_L": None,
}
EXTRA_LANDMARK_VERTICES = {
    "forehead_center": 976,
    "hairline_R": 1309, "hairline_L": 3526,
    "temple_R": 1698, "temple_L": 3903,
    "neck_R": 1480, "neck_center": 1596, "neck_L": 3694,
}

ARKIT_RENAMES = {
    "browDown_L": "browDownLeft", "browDown_R": "browDownRight",
    "browOuterUp_L": "browOuterUpLeft", "browOuterUp_R": "browOuterUpRight",
    "cheekSquint_L": "cheekSquintLeft", "cheekSquint_R": "cheekSquintRight",
    "eyeBlink_L": "eyeBlinkLeft", "eyeBlink_R": "eyeBlinkRight",
    "eyeLookDown_L": "eyeLookDownLeft", "eyeLookDown_R": "eyeLookDownRight",
    "eyeLookIn_L": "eyeLookInLeft", "eyeLookIn_R": "eyeLookInRight",
    "eyeLookOut_L": "eyeLookOutLeft", "eyeLookOut_R": "eyeLookOutRight",
    "eyeLookUp_L": "eyeLookUpLeft", "eyeLookUp_R": "eyeLookUpRight",
    "eyeSquint_L": "eyeSquintLeft", "eyeSquint_R": "eyeSquintRight",
    "eyeWide_L": "eyeWideLeft", "eyeWide_R": "eyeWideRight",
    "mouthDimple_L": "mouthDimpleLeft", "mouthDimple_R": "mouthDimpleRight",
    "mouthFrown_L": "mouthFrownLeft", "mouthFrown_R": "mouthFrownRight",
    "mouthLowerDown_L": "mouthLowerDownLeft", "mouthLowerDown_R": "mouthLowerDownRight",
    "mouthPress_L": "mouthPressLeft", "mouthPress_R": "mouthPressRight",
    "mouthSmile_L": "mouthSmileLeft", "mouthSmile_R": "mouthSmileRight",
    "mouthStretch_L": "mouthStretchLeft", "mouthStretch_R": "mouthStretchRight",
    "mouthUpperUp_L": "mouthUpperUpLeft", "mouthUpperUp_R": "mouthUpperUpRight",
    "noseSneer_L": "noseSneerLeft", "noseSneer_R": "noseSneerRight",
}


def ict_folder(repo_path):
    return os.path.join(repo_path, "third_party", "ICT-FaceKit", "FaceXModel")


def _read_obj(path, topology=False, limit=ICT_VERTEX_LIMIT):
    vertices, uvs, faces, face_uvs = [], [], [], []
    with open(path, "r", encoding="utf-8", errors="ignore") as stream:
        for line in stream:
            if line.startswith("v "):
                if len(vertices) < limit:
                    x, y, z = map(float, line.split()[1:4])
                    # ICT: X horizontal, Y vertical, Z forward. Pipeline:
                    # X horizontal, Z vertical, -Y forward.
                    vertices.append((x, -z, y))
            elif topology and line.startswith("vt "):
                u, v = map(float, line.split()[1:3])
                uvs.append((u, v))
            elif topology and line.startswith("f "):
                fv, ft = [], []
                valid = True
                for token in line.split()[1:]:
                    fields = token.split("/")
                    index = int(fields[0]) - 1
                    if index >= limit:
                        valid = False
                        break
                    fv.append(index)
                    ft.append(int(fields[1]) - 1 if len(fields) > 1 and fields[1] else -1)
                if valid:
                    faces.append(tuple(fv))
                    face_uvs.append(tuple(ft))
    return vertices, faces, uvs, face_uvs


def _model_config(folder):
    with open(os.path.join(folder, "vertex_indices.json"), "r", encoding="utf-8") as stream:
        return json.load(stream)


def source_landmarks(repo_path):
    folder = ict_folder(repo_path)
    config = _model_config(folder)
    vertices, _faces, _uvs, _face_uvs = _read_obj(
        os.path.join(folder, "generic_neutral_mesh.obj"))
    indices = config["idx_to_landmark_verts"]
    return {
        role: Vector(vertices[(EXTRA_LANDMARK_VERTICES[role]
                               if number is None else indices[number])])
        for role, number in LANDMARKS.items()
    }


def create_canonical(repo_path, expressions=True, name=CANONICAL_OBJECT):
    folder = ict_folder(repo_path)
    neutral_path = os.path.join(folder, "generic_neutral_mesh.obj")
    if not os.path.isfile(neutral_path):
        raise RuntimeError("ICT FaceKit is missing; expected " + neutral_path)
    config = _model_config(folder)
    vertices, faces, uvs, face_uvs = _read_obj(neutral_path, topology=True)
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    if uvs and face_uvs:
        layer = mesh.uv_layers.new(name="UVMap")
        for polygon, uv_indices in zip(mesh.polygons, face_uvs):
            for loop_index, uv_index in zip(polygon.loop_indices, uv_indices):
                if 0 <= uv_index < len(uvs):
                    layer.data[loop_index].uv = uvs[uv_index]
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj["canonical_source"] = "USC ICT FaceKit (MIT)"
    obj["canonical_vertex_limit"] = ICT_VERTEX_LIMIT
    obj.shape_key_add(name="Basis")
    if expressions:
        for expression in config["expressions"]:
            path = os.path.join(folder, expression + ".obj")
            coords, _f, _u, _fu = _read_obj(path)
            if len(coords) != len(vertices):
                raise RuntimeError("Topology mismatch in " + path)
            key = obj.shape_key_add(name=ARKIT_RENAMES.get(expression, expression))
            key.data.foreach_set("co", np.asarray(coords, dtype=np.float64).reshape(-1))
        _combine_split_key(obj, "browInnerUp", "browInnerUp_L", "browInnerUp_R")
        _combine_split_key(obj, "cheekPuff", "cheekPuff_L", "cheekPuff_R")
    for role, point in source_landmarks(repo_path).items():
        number = LANDMARKS[role]
        vertex_index = (EXTRA_LANDMARK_VERTICES[role] if number is None
                        else config["idx_to_landmark_verts"][number])
        group = obj.vertex_groups.new(name="CFG_" + role)
        group.add([vertex_index], 1.0, "REPLACE")
    return obj


def _combine_split_key(obj, destination, left, right):
    keys = obj.data.shape_keys.key_blocks
    if left not in keys or right not in keys:
        return
    basis = np.empty(len(obj.data.vertices) * 3, dtype=np.float64)
    lco = np.empty_like(basis)
    rco = np.empty_like(basis)
    keys["Basis"].data.foreach_get("co", basis)
    keys[left].data.foreach_get("co", lco)
    keys[right].data.foreach_get("co", rco)
    key = obj.shape_key_add(name=destination)
    key.data.foreach_set("co", basis + (lco - basis) + (rco - basis))
    # ARKit has one combined channel for each of these expressions. Keep the
    # canonical asset at the standard 51 facial channels (tongueOut is routed
    # to the separate reusable tongue object).
    obj.shape_key_remove(keys[left])
    obj.shape_key_remove(keys[right])


def _tps_weights(source, target, regularization=1e-5):
    """Return 3D polyharmonic-spline weights and affine coefficients."""
    source = np.asarray(source, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    count = len(source)
    distances = np.linalg.norm(source[:, None, :] - source[None, :, :], axis=2)
    scale = max(float(np.median(distances[distances > 0])), 1e-8)
    kernel = distances / scale
    kernel.flat[::count + 1] += regularization
    poly = np.column_stack((np.ones(count), source))
    system = np.block([[kernel, poly], [poly.T, np.zeros((4, 4))]])
    values = np.vstack((target, np.zeros((4, 3))))
    solution = np.linalg.lstsq(system, values, rcond=1e-10)[0]
    return solution[:count], solution[count:], scale


def _warp(points, controls, weights, affine, scale):
    points = np.asarray(points, dtype=np.float64)
    controls = np.asarray(controls, dtype=np.float64)
    kernel = np.linalg.norm(points[:, None, :] - controls[None, :, :], axis=2) / scale
    poly = np.column_stack((np.ones(len(points)), points))
    return kernel @ weights + poly @ affine


def fit_object(obj, repo_path, target_points, regularization=1e-5):
    """Fit Basis and every shape key through one shared smooth landmark warp."""
    available = [role for role in LANDMARKS if role in target_points]
    if len(available) < 8:
        raise RuntimeError("Place at least 8 canonical guides before fitting")
    source_map = source_landmarks(repo_path)
    source = np.asarray([source_map[role] for role in available], dtype=np.float64)
    target = np.asarray([target_points[role] for role in available], dtype=np.float64)
    weights, affine, scale = _tps_weights(source, target, regularization)
    keys = obj.data.shape_keys.key_blocks
    for key in keys:
        coords = np.empty(len(obj.data.vertices) * 3, dtype=np.float64)
        key.data.foreach_get("co", coords)
        warped = _warp(coords.reshape((-1, 3)), source, weights, affine, scale)
        key.data.foreach_set("co", warped.reshape(-1))
    obj["canonical_fit_guides"] = len(available)
    obj["canonical_fit_regularization"] = regularization
    return {"guides": len(available), "vertices": len(obj.data.vertices),
            "shape_keys": len(keys)}


def diagnostic_key_names():
    return ("jawOpen", "mouthClose", "mouthFunnel", "mouthPucker",
            "mouthSmileLeft", "eyeBlinkLeft")
