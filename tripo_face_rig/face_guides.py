"""Versioned artist-authored guide data shared by Blender and the CLI."""
import json
import os


SCHEMA_VERSION = 2

MARKERS = (
    ("mouth_corner_R", "Right mouth corner"),
    ("upper_lip_R", "Upper lip right guide"),
    ("upper_lip_center", "Upper lip center"),
    ("upper_lip_L", "Upper lip left guide"),
    ("mouth_corner_L", "Left mouth corner"),
    ("lower_lip_R", "Lower lip right guide"),
    ("lower_lip_center", "Lower lip center"),
    ("lower_lip_L", "Lower lip left guide"),
    ("chin_center", "Chin center"),
)
REQUIRED_MARKERS = tuple(name for name, _label in MARKERS)


def load(path):
    with open(os.path.abspath(path), "r", encoding="utf-8") as stream:
        guide = json.load(stream)
    version = guide.get("schema_version")
    if version not in (1, SCHEMA_VERSION):
        raise RuntimeError("unsupported face-guide schema %r (expected 1 or %d)" %
                           (version, SCHEMA_VERSION))
    # Version 1 guides remain useful for marker placement, but deliberately do
    # not invent an artist-approved seam. The build validator will ask the user
    # to capture one before any topology-changing work can run.
    if version == 1:
        guide["schema_version"] = SCHEMA_VERSION
        guide.setdefault("topology", {})
        guide.setdefault("calibration", {"approved": False})
    return guide


def save(path, guide):
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(guide, stream, indent=2)
    return path


def transform_local_markers(guide, matrix=None, dx=0.0):
    """Follow normalization/alignment changes applied to head mesh coordinates."""
    from mathutils import Matrix, Vector
    transform = matrix if matrix is not None else Matrix.Identity(4)
    for marker in (guide.get("markers") or {}).values():
        co = transform @ Vector(marker["local"])
        co.x -= dx
        marker["local"] = list(co)
    seam = (guide.get("topology") or {}).get("mouth_seam") or {}
    for index, point in enumerate(seam.get("local_points") or []):
        co = transform @ Vector(point)
        co.x -= dx
        seam["local_points"][index] = list(co)
    return guide


def validate(guide):
    markers = guide.get("markers") or {}
    missing = [name for name in REQUIRED_MARKERS if name not in markers]
    issues = []
    if missing:
        issues.append("missing markers: " + ", ".join(missing))
    objects = guide.get("objects") or {}
    if not objects.get("head"):
        issues.append("head object is not assigned")
    if all(name in markers for name in ("mouth_corner_R", "mouth_corner_L")):
        right = markers["mouth_corner_R"]["local"]
        left = markers["mouth_corner_L"]["local"]
        if right[0] >= left[0]:
            issues.append("mouth corners are reversed or cross the midline")
    if all(name in markers for name in ("upper_lip_center", "lower_lip_center")):
        upper = markers["upper_lip_center"]["local"]
        lower = markers["lower_lip_center"]["local"]
        if upper[2] <= lower[2]:
            issues.append("upper-lip center must be above lower-lip center")
    return {"valid": not issues, "issues": issues, "missing": missing}


def validate_for_build(guide):
    """Validate the non-negotiable authored inputs for a guided build."""
    check = validate(guide)
    issues = list(check["issues"])
    seam = (guide.get("topology") or {}).get("mouth_seam") or {}
    points = seam.get("local_points") or []
    edges = seam.get("edge_pairs") or []
    if not seam.get("validated") or len(points) < 4 or len(edges) < 3:
        issues.append(
            "capture a continuous corner-to-corner mouth seam in Edit Mode")
    masks = guide.get("masks") or {}
    for name in ("FRG_upper_lip", "FRG_lower_lip", "FRG_jaw"):
        if not masks.get(name):
            issues.append("missing painted deformation region: " + name)
    return {"valid": not issues, "issues": issues,
            "missing": check.get("missing", [])}


def _marker(guide, name):
    return list(guide["markers"][name]["local"])


def _rail(guide, upper):
    names = (("mouth_corner_R", "upper_lip_R", "upper_lip_center",
              "upper_lip_L", "mouth_corner_L") if upper else
             ("mouth_corner_R", "lower_lip_R", "lower_lip_center",
              "lower_lip_L", "mouth_corner_L"))
    return [_marker(guide, name) for name in names]


def apply_to_profile(profile, guide):
    """Override ambiguous automatic mouth landmarks with an artist guide."""
    check = validate(guide)
    if not check["valid"]:
        raise RuntimeError("invalid face guide: " + "; ".join(check["issues"]))
    mouth = profile.get("mouth")
    if mouth is None:
        raise RuntimeError("automatic measurement found no mouth to refine")

    right = _marker(guide, "mouth_corner_R")
    left = _marker(guide, "mouth_corner_L")
    upper = _marker(guide, "upper_lip_center")
    lower = _marker(guide, "lower_lip_center")
    centre_z = 0.5 * (upper[2] + lower[2])
    centre_y = 0.5 * (upper[1] + lower[1])
    corner_z = 0.5 * (right[2] + left[2])
    corner_y = 0.5 * (right[1] + left[1])
    corner_x = max(1e-6, 0.5 * (abs(right[0]) + abs(left[0])))

    mouth["corner_x"] = corner_x
    mouth["seam_z"] = [centre_z, (corner_z - centre_z) / (corner_x ** 2)]
    mouth["seam_y"] = [centre_y, (corner_y - centre_y) / (corner_x ** 2)]
    mouth["guide_rails"] = {
        "upper": _rail(guide, True),
        "lower": _rail(guide, False),
    }
    mouth["guide_settings"] = dict(guide.get("settings") or {})
    mouth.setdefault("detect", {})["artist_guide"] = True
    profile["face_guide"] = {
        "schema_version": guide["schema_version"],
        "path": guide.get("path"),
        "validation": check,
        "guide": guide,
    }
    return profile
