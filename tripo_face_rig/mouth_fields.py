"""Topology-independent deformation fields fitted to measured mouth rails.

The rails describe *where* a character's lips are, not what their topology
looks like.  Every source vertex receives smooth upper/lower, wet-line, body,
corner and side weights from its position relative to those rails.  This lets
the same expression rules work on irregular triangles, split quads and locally
subdivided meshes without replacing the neutral mouth surface.
"""
import math

from mathutils import Vector

from .build import seam_y, seam_z


def _clamp(value, lo=0.0, hi=1.0):
    return max(lo, min(hi, value))


def _smooth(value):
    value = _clamp(value)
    return value * value * (3.0 - 2.0 * value)


def _sample(slices, x, key):
    if not slices:
        return None
    if x <= slices[0]["x"]:
        return slices[0][key]
    if x >= slices[-1]["x"]:
        return slices[-1][key]
    for left, right in zip(slices, slices[1:]):
        if left["x"] <= x <= right["x"]:
            span = max(right["x"] - left["x"], 1e-8)
            t = (x - left["x"]) / span
            return left[key] * (1.0 - t) + right[key] * t
    return None


class MouthField:
    """Evaluate fitted per-vertex mouth controls on arbitrary topology."""

    def __init__(self, params, topology_sides=None, semantic=None):
        self.P = params
        self.S = params["S"]
        self.A0 = params["A0"]
        self.XC = params["corner_x"]
        self.slices = sorted(params.get("slices") or [],
                             key=lambda item: item["x"])
        self.guide_rails = params.get("guide_rails") or {}
        self.settings = params.get("guide_settings") or {}
        self.topology_sides = topology_sides or {}
        self.semantic = semantic or {}
        self.front_limit = params["front_cut"] + 0.045 * self.S
        radius_scale = float(self.settings.get("lip_influence", 1.0))
        self.z_radius = max(0.52 * self.A0, 0.023 * self.S) * radius_scale
        self.y_radius = max(0.046 * self.S, 0.58 * self.A0) * radius_scale

    def rail(self, x, upper):
        guide = self.guide_rails.get("upper" if upper else "lower")
        if guide:
            if x <= guide[0][0]:
                point = guide[0]
                return Vector(point)
            if x >= guide[-1][0]:
                point = guide[-1]
                return Vector(point)
            for left, right in zip(guide, guide[1:]):
                if left[0] <= x <= right[0]:
                    t = (x - left[0]) / max(right[0] - left[0], 1e-8)
                    return Vector(left).lerp(Vector(right), t)
        z = _sample(self.slices, x, "hi" if upper else "lo")
        y = _sample(self.slices, x, "yhi" if upper else "ylo")
        if z is None:
            aperture = self.A0 * max(0.0, 1.0 - (x / self.XC) ** 2)
            z = seam_z(self.P, x) + (0.5 if upper else -0.5) * aperture
        if y is None:
            offset = self.P["rim_off"][1 if upper else 0]
            y = seam_y(self.P, x) + offset
        return Vector((x, y, z))

    def side(self, index, co):
        upper_weight = self.semantic.get("upper", {}).get(index, 0.0)
        lower_weight = self.semantic.get("lower", {}).get(index, 0.0)
        if max(upper_weight, lower_weight) > 0.015:
            return 1 if upper_weight >= lower_weight else -1
        topological = self.topology_sides.get(index)
        if topological is not None and abs(topological) > 1e-8:
            return 1 if topological > 0.0 else -1
        upper = self.rail(co.x, True)
        lower = self.rail(co.x, False)
        du = ((co.z - upper.z) / self.z_radius) ** 2 + (
            (co.y - upper.y) / self.y_radius) ** 2
        dl = ((co.z - lower.z) / self.z_radius) ** 2 + (
            (co.y - lower.y) / self.y_radius) ** 2
        return 1 if du <= dl else -1

    def evaluate(self, index, co):
        if abs(co.x) > 1.32 * self.XC or co.y > self.front_limit:
            return None
        side = self.side(index, co)
        rail = self.rail(co.x, side > 0)
        dz = (co.z - rail.z) / self.z_radius
        dy = (co.y - rail.y) / self.y_radius
        distance = math.sqrt(dz * dz + dy * dy)
        if distance >= 1.55:
            return None

        axial = _smooth(1.0 - (abs(co.x) / (1.32 * self.XC)) ** 2)
        body = _smooth(1.0 - distance / 1.55) * axial
        wet = _smooth(1.0 - distance / 0.72) * axial
        corner_position = abs(co.x) / max(self.XC, 1e-8)
        corner = (_smooth((corner_position - 0.48) / 0.40)
                  * _smooth((1.28 - corner_position) / 0.28)
                  * _smooth(1.0 - distance / 1.35))
        semantic_body = max(
            self.semantic.get("upper", {}).get(index, 0.0),
            self.semantic.get("lower", {}).get(index, 0.0))
        if self.semantic.get("enabled"):
            # Vertex groups survive BMesh welding, subdivision and seam
            # splitting. Blend rather than replace so newly interpolated or
            # lightly painted boundary vertices retain a smooth falloff.
            body *= 0.30 + 0.70 * semantic_body
            wet *= 0.35 + 0.65 * semantic_body
            painted_corner = self.semantic.get("corners", {}).get(index, 0.0)
            corner *= 0.30 + 0.70 * painted_corner
        return {
            "side": side,
            "rail": rail,
            "body": body,
            "wet": wet,
            "corner": corner,
            "left": _smooth(0.5 + 0.82 * co.x / max(self.XC, 1e-8)),
            "right": _smooth(0.5 - 0.82 * co.x / max(self.XC, 1e-8)),
            "seam_z": seam_z(self.P, co.x),
        }

    def report(self, vertices, indices):
        upper = lower = wet = corners = 0
        for index in indices:
            field = self.evaluate(index, vertices[index].co)
            if not field:
                continue
            if field["side"] > 0:
                upper += 1
            else:
                lower += 1
            wet += field["wet"] > 0.05
            corners += field["corner"] > 0.05
        return {
            "upper_vertices": upper,
            "lower_vertices": lower,
            "wet_vertices": wet,
            "corner_vertices": corners,
            "z_radius": self.z_radius,
            "y_radius": self.y_radius,
            "slice_count": len(self.slices),
            "semantic_masks": bool(self.semantic.get("enabled")),
            "painted_upper": len(self.semantic.get("upper", {})),
            "painted_lower": len(self.semantic.get("lower", {})),
        }
