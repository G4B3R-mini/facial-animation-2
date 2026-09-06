"""Constrained local mouth-topology tools.

The production path densifies the measured lip band without moving existing
vertices.  A fitted all-quad template is also available as a non-destructive
preview.  The cut-and-stitch replacement function remains experimental and is
deliberately not exposed by the command-line pipeline.
"""
import math

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree
from mathutils.geometry import barycentric_transform, closest_point_on_tri

from . import util


DEFAULTS = {
    "segments": 32,
    "rings": 6,
    "radial_width": 0.030,
    "tube_depth": 0.055,
    "cut_margin": 1.035,
    "cut_depth": 0.060,
    "neutral_gap": 0.003,
    "transition_blend": 0.58,
    "bake_size": 1024,
}


def _clamp(value, lo=0.0, hi=1.0):
    return max(lo, min(hi, value))


def _seam_z(mouth, x):
    a, b = mouth["seam_z"]
    return a + b * x * x


def _sample_rim(mouth, x, upper):
    slices = sorted(mouth.get("slices") or [], key=lambda item: item["x"])
    if not slices:
        return None
    field_z = "hi" if upper else "lo"
    field_y = "yhi" if upper else "ylo"
    if x <= slices[0]["x"]:
        item = slices[0]
        return item[field_y], item[field_z]
    if x >= slices[-1]["x"]:
        item = slices[-1]
        return item[field_y], item[field_z]
    for left, right in zip(slices, slices[1:]):
        if left["x"] <= x <= right["x"]:
            span = max(right["x"] - left["x"], 1e-8)
            t = (x - left["x"]) / span
            y = left[field_y] * (1.0 - t) + right[field_y] * t
            z = left[field_z] * (1.0 - t) + right[field_z] * t
            return y, z
    return None


def _face_bvh(mesh, face_component):
    comp_of, _ = util.islands(mesh)
    coords = [vertex.co.copy() for vertex in mesh.vertices]
    polygons = [list(poly.vertices) for poly in mesh.polygons
                if all(comp_of.get(index) == face_component
                       for index in poly.vertices)]
    return BVHTree.FromPolygons(coords, polygons, all_triangles=False)


def _front_sampler(mesh, face_component, front_limit):
    """Return a smooth y sampler that cannot jump onto teeth/interior shells."""
    comp_of, _ = util.islands(mesh)
    points = [(vertex.co.copy(), vertex.index) for vertex in mesh.vertices
              if comp_of.get(vertex.index) == face_component
              and vertex.co.y <= front_limit]
    tree = KDTree(len(points))
    coords = {}
    for co, index in points:
        tree.insert(Vector((co.x, co.z, 0.0)), index)
        coords[index] = co
    tree.balance()

    def sample(x, z):
        hits = tree.find_n(Vector((x, z, 0.0)), min(10, len(points)))
        if not hits:
            return None
        weighted = total = 0.0
        for _position, index, distance in hits:
            weight = 1.0 / max(distance, 0.001)
            weighted += coords[index].y * weight
            total += weight
        return weighted / total
    return sample


def _uv_sampler(mesh, face_component, front_limit, ray_y):
    if not mesh.uv_layers or mesh.uv_layers.active is None:
        return None
    comp_of, _ = util.islands(mesh)
    polygon_indices = [poly.index for poly in mesh.polygons
                       if all(comp_of.get(index) == face_component
                              for index in poly.vertices)
                       and poly.center.y <= front_limit
                       and poly.normal.y < -0.12]
    polygons = [list(mesh.polygons[index].vertices) for index in polygon_indices]
    bvh = BVHTree.FromPolygons([vertex.co.copy() for vertex in mesh.vertices],
                               polygons, all_triangles=False)
    uv_data = mesh.uv_layers.active.data

    def sample(co):
        nearest, _normal, local_index, _distance = bvh.find_nearest(co)
        if nearest is None:
            nearest, _normal, local_index, _distance = bvh.ray_cast(
                Vector((co.x, ray_y, co.z)), Vector((0.0, 1.0, 0.0)))
        if nearest is None:
            return Vector((0.5, 0.5))
        polygon = mesh.polygons[polygon_indices[local_index]]
        best = None
        loops = list(polygon.loop_indices)
        for offset in range(1, len(loops) - 1):
            tri_loops = (loops[0], loops[offset], loops[offset + 1])
            tri_verts = [mesh.loops[loop].vertex_index for loop in tri_loops]
            points = [mesh.vertices[index].co for index in tri_verts]
            closest = closest_point_on_tri(nearest, points[0], points[1], points[2])
            distance = (closest - nearest).length_squared
            if best is None or distance < best[0]:
                uvs = [Vector((*uv_data[loop].uv, 0.0)) for loop in tri_loops]
                uv = barycentric_transform(closest, points[0], points[1], points[2],
                                           uvs[0], uvs[1], uvs[2])
                best = (distance, Vector((uv.x, uv.y)))
        return best[1] if best else Vector((0.5, 0.5))
    return sample


def eligibility(obj, profile):
    mouth = profile.get("mouth")
    reasons = []
    if mouth is None:
        reasons.append("no measured mouth")
    if obj.data.shape_keys is not None:
        reasons.append("shape keys already exist; retopology must run on raw input")
    if mouth:
        ratio_x = mouth["corner_x"] / max(profile["scale"], 1e-8)
        ratio_a = mouth["aperture_centre"] / max(profile["scale"], 1e-8)
        if not 0.045 <= ratio_x <= 0.22:
            reasons.append("mouth width outside supported humanoid range")
        if not 0.004 <= ratio_a <= 0.14:
            reasons.append("mouth aperture outside supported range")
        if len(mouth.get("slices") or []) < 8:
            reasons.append("too few reliable rim samples")

    score = 1.0
    score -= 0.28 * len(reasons)
    if mouth:
        slices = mouth.get("slices") or []
        left = [item for item in slices if item["x"] < 0.0]
        right = [item for item in slices if item["x"] > 0.0]
        if left and right:
            l_amp = sum(item["amp"] for item in left) / len(left)
            r_amp = sum(item["amp"] for item in right) / len(right)
            asym = abs(l_amp - r_amp) / max(l_amp, r_amp, 1e-8)
            score -= 0.35 * _clamp(asym / 0.35)
    return {
        "eligible": not reasons,
        "confidence": round(_clamp(score), 3),
        "reasons": reasons,
    }


def template_geometry(obj, profile, options=None):
    """Return fitted canonical vertices, quad faces and landmark metadata."""
    opts = dict(DEFAULTS)
    if options:
        opts.update(options)
    check = eligibility(obj, profile)
    if not check["eligible"]:
        raise RuntimeError("mouth retopo ineligible: " + "; ".join(check["reasons"]))

    mouth = profile["mouth"]
    S = profile["scale"]
    XC = mouth["corner_x"]
    A0 = mouth["aperture_centre"]
    # Measurement aperture spans the detected upper/lower surfaces and can be
    # much larger than the visible neutral opening.  Keep the replacement
    # nearly sealed; jawOpen and the expression shapes create the performance
    # aperture later.
    visible_gap = min(opts["neutral_gap"] * S, 0.08 * A0)
    segments = max(16, int(opts["segments"]))
    if segments % 4 and not opts.get("exact_segments"):
        segments += 4 - segments % 4
    rings = max(4, int(opts["rings"]))
    radial = opts["radial_width"] * S
    fbb = profile["shells"][str(profile["roles"]["face"])]["bbox"]
    front_limit = mouth["front_cut"] + 0.045 * S
    sample_front = _front_sampler(obj.data, profile["roles"]["face"], front_limit)

    verts = []
    ring_rows = []
    misses = 0
    anchors = []
    for index in range(segments):
        phi = 2.0 * math.pi * index / segments
        cs, sn = math.cos(phi), math.sin(phi)
        inner_x = XC * cs
        falloff = max(0.0, 1.0 - (abs(inner_x) / max(XC, 1e-8)) ** 1.75)
        # The invaginated detector's A0 spans the folded inner lip surfaces,
        # not the visible neutral opening.  Using it as the wet-line aperture
        # creates a permanently gaping mouth.  Fit a conservative visible gap
        # while retaining the measured seam and corner positions.
        rim_z = (_seam_z(mouth, inner_x) +
                 sn * 0.5 * visible_gap * falloff)
        sampled = _sample_rim(mouth, inner_x, sn >= 0.0)
        # Preserve the measured front profile of each lip even though z is
        # collapsed to a neutral wet line. Sampling the generic face surface
        # here tends to jump between upper lip, lower lip and oral cavity and
        # produces the characteristic flat shelf seen on generated heads.
        rim_y = sampled[0] if sampled else sample_front(inner_x, rim_z)
        if rim_y is None:
            misses += 1
            rim_y = mouth["seam_y"][0]

        outer_x = (XC + radial) * cs
        outer_z = (_seam_z(mouth, inner_x) +
                   sn * (0.5 * visible_gap * falloff +
                         radial * (0.72 + 0.28 * abs(sn))))
        outer_y = sample_front(outer_x, outer_z)
        if outer_y is None:
            misses += 1
            outer_y = rim_y
        anchors.append((Vector((inner_x, rim_y, rim_z)),
                        Vector((outer_x, outer_y, outer_z))))

    # Smooth only the sampled cheek depth.  x/z remain landmark constrained.
    for _pass in range(2):
        smoothed = []
        for index, (rim, outer) in enumerate(anchors):
            prev_y = anchors[(index - 1) % segments][1].y
            next_y = anchors[(index + 1) % segments][1].y
            smooth_y = 0.25 * prev_y + 0.50 * outer.y + 0.25 * next_y
            smoothed.append((rim, Vector((outer.x, smooth_y, outer.z))))
        anchors = smoothed

    for ring in range(rings):
        t = ring / float(rings - 1)
        row_coords = []
        for rim, outer in anchors:
            co = rim.lerp(outer, t)
            sampled_y = sample_front(co.x, co.z)
            if sampled_y is not None:
                co.y = sampled_y
            co.y -= 0.0014 * S * math.sin(math.pi * t)
            row_coords.append(co)
        if ring not in {0, rings - 1}:
            row_coords = [Vector((co.x,
                                  0.20 * row_coords[(index - 1) % segments].y +
                                  0.60 * co.y +
                                  0.20 * row_coords[(index + 1) % segments].y,
                                  co.z))
                          for index, co in enumerate(row_coords)]
        row = []
        for co in row_coords:
            row.append(len(verts))
            verts.append(co)
        ring_rows.append(row)

    faces = []
    for ring in range(rings - 1):
        inner, outer = ring_rows[ring], ring_rows[ring + 1]
        for index in range(segments):
            nxt = (index + 1) % segments
            faces.append((inner[index], inner[nxt], outer[nxt], outer[index]))

    return {
        "vertices": verts,
        "faces": faces,
        "rings": ring_rows,
        "segments": segments,
        "ring_count": rings,
        "surface_misses": misses,
        "confidence": check["confidence"],
        "centre": Vector((0.0, mouth["seam_y"][0], mouth["seam_z"][0])),
    }


def create_preview(obj, profile, name="mouth_retopo_preview", options=None):
    geo = template_geometry(obj, profile, options)
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(geo["vertices"], [], geo["faces"])
    mesh.update()
    preview = bpy.data.objects.new(name, mesh)
    obj.users_collection[0].objects.link(preview)
    preview.matrix_world = obj.matrix_world.copy()
    material = bpy.data.materials.get("mouth_retopo_preview")
    if material is None:
        material = bpy.data.materials.new("mouth_retopo_preview")
        material.diffuse_color = (0.02, 0.45, 0.8, 1.0)
        material.metallic = 0.05
        material.roughness = 0.38
    mesh.materials.append(material)
    preview["retopo_confidence"] = geo["confidence"]
    preview["retopo_segments"] = geo["segments"]
    preview["retopo_rings"] = geo["ring_count"]
    return preview, geo


def densify(obj, profile, cuts=1):
    """Add local deformation resolution without moving the neutral surface.

    This is the production-safe first stage: UVs/materials are interpolated by
    BMesh, all old vertex coordinates remain byte-identical, and only edges in
    the measured front lip band are subdivided.
    """
    check = eligibility(obj, profile)
    if not check["eligible"]:
        raise RuntimeError("mouth densify ineligible: " + "; ".join(check["reasons"]))
    mouth = profile["mouth"]
    S = profile["scale"]
    XC = mouth["corner_x"]
    centre_z = mouth["seam_z"][0]
    half_z = max(0.72 * mouth["aperture_centre"], 0.048 * S)
    front_limit = mouth["front_cut"] + 0.075 * S
    comp_of, _ = util.islands(obj.data)
    face_component = profile["roles"]["face"]
    original_coords = [vertex.co.copy() for vertex in obj.data.vertices]
    old_vertices = len(obj.data.vertices)
    old_faces = len(obj.data.polygons)

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    selected = []
    for edge in bm.edges:
        if not all(comp_of.get(vertex.index) == face_component
                   for vertex in edge.verts):
            continue
        midpoint = 0.5 * (edge.verts[0].co + edge.verts[1].co)
        if (abs(midpoint.x) <= 1.20 * XC
                and abs(midpoint.z - _seam_z(mouth, midpoint.x)) <= half_z
                and midpoint.y <= front_limit):
            selected.append(edge)
    if len(selected) < 16:
        bm.free()
        raise RuntimeError("mouth densify selected too few edges")

    applied_cuts = min(2, max(1, int(cuts)))
    result = bmesh.ops.subdivide_edges(
        bm, edges=selected, cuts=applied_cuts, smooth=0.0,
        use_grid_fill=True, use_only_quads=False)
    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()

    unchanged = all((obj.data.vertices[index].co - co).length <= 1e-8
                    for index, co in enumerate(original_coords))
    return {
        "status": "applied" if unchanged else "review",
        "confidence": check["confidence"],
        "edges_selected": len(selected),
        "cuts": applied_cuts,
        "vertices_before": old_vertices,
        "vertices_after": len(obj.data.vertices),
        "vertices_added": len(obj.data.vertices) - old_vertices,
        "faces_before": old_faces,
        "faces_after": len(obj.data.polygons),
        "original_vertices_unchanged": unchanged,
        "new_geometry_items": len(result.get("geom_inner", [])),
    }


def _skin_material_index(obj, profile):
    face_component = profile["roles"]["face"]
    comp_of, _ = util.islands(obj.data)
    counts = {}
    for poly in obj.data.polygons:
        if all(comp_of.get(index) == face_component for index in poly.vertices):
            counts[poly.material_index] = counts.get(poly.material_index, 0) + 1
    return max(counts, key=counts.get) if counts else 0


def _mouth_material_index(obj):
    material = bpy.data.materials.get("mouth_interior")
    if material is None:
        material = bpy.data.materials.new("mouth_interior")
        material.diffuse_color = (0.035, 0.008, 0.009, 1.0)
        material.roughness = 0.82
    for index, slot in enumerate(obj.material_slots):
        if slot.material == material:
            return index
    obj.data.materials.append(material)
    return len(obj.data.materials) - 1


def _patch_bake_material(obj, size=1024):
    image = bpy.data.images.new("mouth_retopo_bake", width=size, height=size,
                                alpha=False, float_buffer=False)
    material = bpy.data.materials.new("mouth_retopo_skin")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    nodes.active = texture
    material.node_tree.links.new(texture.outputs["Color"],
                                 shader.inputs["Base Color"])
    material.node_tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    obj.data.materials.append(material)
    return len(obj.data.materials) - 1, material, image


def _isolate_component(obj, component):
    """Remove every mesh island except ``component`` from a transfer copy."""
    comp_of, _groups = util.islands(obj.data)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    remove = [vertex for vertex in bm.verts
              if comp_of.get(vertex.index) != component]
    if remove:
        bmesh.ops.delete(bm, geom=remove, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def _bake_patch(source, matrix_world, coords, faces, loop_uvs,
                material, image, scale):
    """Bake source diffuse color onto a temporary copy of the new patch."""
    mesh = bpy.data.meshes.new("mouth_retopo_bake_target_mesh")
    mesh.from_pydata(coords, [], faces)
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for loop, uv in zip(uv_layer.data, loop_uvs):
        loop.uv = uv
    mesh.materials.append(material)
    target = bpy.data.objects.new("mouth_retopo_bake_target", mesh)
    bpy.context.scene.collection.objects.link(target)
    target.matrix_world = matrix_world.copy()

    source.hide_render = False
    source.hide_set(False)
    for other in bpy.context.view_layer.objects:
        try:
            other.select_set(False)
        except Exception:
            pass
    source.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    scene = bpy.context.scene
    previous_engine = scene.render.engine
    scene.render.engine = "CYCLES"
    baked = False
    try:
        with bpy.context.temp_override(active_object=target, object=target,
                                       selected_objects=[source, target],
                                       selected_editable_objects=[source, target]):
            bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"},
                                use_selected_to_active=True, use_clear=True,
                                cage_extrusion=0.018 * scale,
                                max_ray_distance=0.09 * scale, margin=12)
        image.pack()
        baked = True
    finally:
        scene.render.engine = previous_engine
        bpy.data.objects.remove(target, do_unlink=True)
        source.hide_render = True
        source.hide_set(True)
    return baked


def _zipper_faces(boundary, inner):
    """Triangulate a narrow annulus between two angle-ordered loops."""
    faces = []
    n, m = len(boundary), len(inner)
    i = j = 0
    while i < n or j < m:
        next_i = (i + 1) / n if i < n else 2.0
        next_j = (j + 1) / m if j < m else 2.0
        bi = boundary[i % n]
        oj = inner[j % m]
        if next_i < next_j:
            faces.append((bi, boundary[(i + 1) % n], oj))
            i += 1
        else:
            faces.append((bi, inner[(j + 1) % m], oj))
            j += 1
    return faces


def _boundary_graph(edges):
    adjacency = {}
    for edge in edges:
        a, b = edge.verts
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    remaining = set(adjacency)
    components = []
    while remaining:
        seed = next(iter(remaining))
        todo = [seed]
        component = set()
        while todo:
            vertex = todo.pop()
            if vertex not in remaining:
                continue
            remaining.remove(vertex)
            component.add(vertex)
            todo.extend(adjacency[vertex] & remaining)
        components.append(component)
    return adjacency, sorted(components, key=len, reverse=True)


def _angle_order(component, centre_z, rx, rz):
    return sorted(component, key=lambda vertex: (math.atan2(
        (vertex.co.z - centre_z) / max(rz, 1e-8),
        vertex.co.x / max(rx, 1e-8)) + 2.0 * math.pi) % (2.0 * math.pi))


def _graph_order(adjacency, component):
    """Order a closed loop or open boundary path using its actual edges."""
    endpoints = [vertex for vertex in component
                 if len(adjacency[vertex] & component) == 1]
    if endpoints:
        start = max(endpoints, key=lambda vertex: vertex.co.x)
        previous = None
        current = start
        ordered = []
        while current is not None and len(ordered) <= len(component):
            ordered.append(current)
            following = [vertex for vertex in adjacency[current] & component
                         if vertex != previous and vertex not in ordered]
            previous, current = current, (following[0] if following else None)
        return ordered

    start = max(component, key=lambda vertex: vertex.co.x)
    neighbours = list(adjacency[start] & component)
    if len(neighbours) != 2:
        return []
    current = max(neighbours, key=lambda vertex: vertex.co.z)
    ordered = [start]
    previous = start
    while current != start and len(ordered) <= len(component):
        ordered.append(current)
        following = [vertex for vertex in adjacency[current] & component
                     if vertex != previous]
        if not following:
            break
        previous, current = current, following[0]
    return ordered if len(ordered) == len(component) else []


def _ordered_boundary(edges, centre_z, rx, rz):
    adjacency, components = _boundary_graph(edges)
    closed = [component for component in components
              if all(len(adjacency[vertex] & component) == 2
                     for vertex in component)]
    component = max(closed or components, key=len)
    if not all(len(adjacency[vertex] & component) == 2 for vertex in component):
        return sorted(component, key=lambda vertex: (math.atan2(
            (vertex.co.z - centre_z) / max(rz, 1e-8),
            vertex.co.x / max(rx, 1e-8)) + 2.0 * math.pi) % (2.0 * math.pi))

    start = max(component, key=lambda vertex: vertex.co.x)
    neighbours = list(adjacency[start] & component)
    current = max(neighbours, key=lambda vertex: vertex.co.z)
    ordered = [start]
    previous = start
    while current != start and len(ordered) <= len(component):
        ordered.append(current)
        following = [vertex for vertex in adjacency[current] & component
                     if vertex != previous]
        if not following:
            break
        previous, current = current, following[0]
    if len(ordered) != len(component):
        return sorted(component, key=lambda vertex: (math.atan2(
            (vertex.co.z - centre_z) / max(rz, 1e-8),
            vertex.co.x / max(rx, 1e-8)) + 2.0 * math.pi) % (2.0 * math.pi))
    return ordered


def replace(obj, profile, options=None):
    """Experimentally replace the local lip region and return a report.

    This currently needs manual seam and UV review; use ``densify`` in the
    production pipeline.
    """
    geo = template_geometry(obj, profile, options)
    opts = dict(DEFAULTS)
    if options:
        opts.update(options)
    mouth = profile["mouth"]
    S = profile["scale"]
    centre_z = mouth["seam_z"][0]
    outer_coords = [geo["vertices"][index] for index in geo["rings"][-1]]
    rx = max(abs(co.x) for co in outer_coords) * opts["cut_margin"]
    rz = max(abs(co.z - centre_z) for co in outer_coords) * opts["cut_margin"]
    # Remove the visible perioral surface but stop before the folded inner lip.
    # The inner boundary is now stitched separately to the mouth tube below.
    front_limit = mouth["seam_y"][0] + opts["cut_depth"] * S

    source = obj.copy()
    source.data = obj.data.copy()
    source.name = obj.name + "_retopo_transfer_source"
    obj.users_collection[0].objects.link(source)
    source.hide_render = True
    source.hide_set(True)

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    comp_of, _ = util.islands(obj.data)
    face_component = profile["roles"]["face"]
    _isolate_component(source, face_component)
    fbb = profile["shells"][str(face_component)]["bbox"]
    sample_visible = _front_sampler(
        obj.data, face_component, mouth["seam_y"][0] + 0.14 * S)
    sample_uv = _uv_sampler(source.data, face_component,
                            mouth["front_cut"] + 0.06 * S,
                            fbb["y"][0] - 0.25 * S)
    doomed = set()
    for face in bm.faces:
        if not all(comp_of.get(vertex.index) == face_component
                   for vertex in face.verts):
            continue
        centre = face.calc_center_median()
        radial = (centre.x / max(rx, 1e-8)) ** 2 + (
            (centre.z - centre_z) / max(rz, 1e-8)) ** 2
        visible_y = sample_visible(centre.x, centre.z)
        if (radial < 1.0 and visible_y is not None
                and centre.y <= visible_y + 0.022 * S):
            doomed.add(face)
    if len(doomed) < 12:
        bm.free()
        bpy.data.objects.remove(source, do_unlink=True)
        raise RuntimeError("mouth retopo cut selected too few faces")

    boundary_set = set()
    cut_edges = set()
    for face in doomed:
        for edge in face.edges:
            if any(link not in doomed for link in edge.link_faces):
                cut_edges.add(edge)
                boundary_set.update(edge.verts)
    if len(boundary_set) < 12:
        bm.free()
        bpy.data.objects.remove(source, do_unlink=True)
        raise RuntimeError("mouth retopo could not recover a cut boundary")

    cut_adjacency, cut_components = _boundary_graph(cut_edges)

    def component_radius(component):
        return sum(math.sqrt((v.co.x / max(rx, 1e-8)) ** 2
                             + ((v.co.z - centre_z) / max(rz, 1e-8)) ** 2)
                   for v in component) / len(component)

    closed_components = [component for component in cut_components
                         if all(len(cut_adjacency[v] & component) == 2
                                for v in component)]
    outer_component = max(closed_components or cut_components,
                          key=component_radius)
    inner_components = [component for component in cut_components
                        if component is not outer_component and len(component) >= 12]
    inner_component = max(inner_components, key=len) if inner_components else None
    cut_component_report = [
        {"vertices": len(component),
         "closed": all(len(cut_adjacency[vertex] & component) == 2
                       for vertex in component),
         "degree_range": [min(len(cut_adjacency[v] & component) for v in component),
                          max(len(cut_adjacency[v] & component) for v in component)],
         "mean_radius": round(component_radius(component), 4),
         "y_range": [round(min(v.co.y for v in component), 5),
                     round(max(v.co.y for v in component), 5)]}
        for component in cut_components
    ]

    bmesh.ops.delete(bm, geom=list(doomed), context="FACES")
    bm.verts.ensure_lookup_table()
    boundary = (_graph_order(cut_adjacency, outer_component)
                or _angle_order(outer_component, centre_z, rx, rz))
    inner_boundary = ((_graph_order(cut_adjacency, inner_component)
                       or _angle_order(inner_component, centre_z, rx, rz))
                      if inner_component else None)

    # The cut loop itself becomes the last canonical ring. This creates a
    # genuinely shared seam and avoids a folded triangle zipper between an
    # arbitrary source-loop count and a fixed 32-vertex template.
    replacement_options = dict(opts)
    replacement_options["segments"] = len(boundary)
    replacement_options["exact_segments"] = True
    geo = template_geometry(obj, profile, replacement_options)

    skin_material = _skin_material_index(obj, profile)
    mouth_material = _mouth_material_index(obj)
    patch_material, patch_mat, patch_image = _patch_bake_material(
        obj, int(opts["bake_size"]))
    fitted_coords = [co.copy() for co in geo["vertices"]]
    outer_indices = geo["rings"][-1]
    support_indices = geo["rings"][-2]
    for index, vertex_index in enumerate(outer_indices):
        target = boundary[index].co.copy()
        fitted_coords[vertex_index] = target.copy()
        support_index = support_indices[index]
        fitted_coords[support_index] = fitted_coords[support_index].lerp(target, 0.48)
    outer_lookup = {vertex_index: boundary[index]
                    for index, vertex_index in enumerate(outer_indices)}
    new_verts = []
    added_verts = []
    for index, co in enumerate(fitted_coords):
        vertex = outer_lookup.get(index)
        if vertex is None:
            vertex = bm.verts.new(co)
            added_verts.append(vertex)
        new_verts.append(vertex)
    bm.verts.index_update()
    created_faces = []
    skin_faces = []
    for indices in geo["faces"]:
        face = bm.faces.new([new_verts[index] for index in indices])
        face.material_index = patch_material
        face.smooth = True
        created_faces.append(face)
        skin_faces.append(face)

    transition_faces = []
    transition_skipped = []

    wet = [new_verts[index] for index in geo["rings"][0]]
    tube = [bm.verts.new(vertex.co + Vector((0.0, opts["tube_depth"] * S, 0.0)))
            for vertex in wet]
    for index in range(len(wet)):
        nxt = (index + 1) % len(wet)
        face = bm.faces.new((wet[index], wet[nxt], tube[nxt], tube[index]))
        face.material_index = mouth_material
        face.smooth = True
        created_faces.append(face)

    inner_transition_faces = []
    inner_transition_skipped = []
    if inner_boundary:
        inner_transition_faces = _zipper_faces(inner_boundary, tube)
        for vertices in inner_transition_faces:
            try:
                face = bm.faces.new(vertices)
                face.material_index = mouth_material
                face.smooth = True
                created_faces.append(face)
            except ValueError:
                inner_transition_skipped.append([
                    [round(value, 5) for value in vertex.co]
                    for vertex in vertices])

    patch_vertices = set(added_verts + tube)
    unmatched_patch_edges = sum(
        1 for edge in bm.edges
        if any(vertex in patch_vertices for vertex in edge.verts)
        and len(edge.link_faces) == 1)

    bmesh.ops.recalc_face_normals(bm, faces=created_faces)
    uv_transferred = False
    uv_layer = bm.loops.layers.uv.active
    if uv_layer is None:
        uv_layer = bm.loops.layers.uv.new("UVMap")
    bake_coords = []
    bake_faces = []
    bake_loop_uvs = []
    bake_vertex_indices = {}
    for face in skin_faces:
        indices = []
        for loop in face.loops:
            vertex = loop.vert
            vertex_index = bake_vertex_indices.get(vertex)
            if vertex_index is None:
                vertex_index = len(bake_coords)
                bake_vertex_indices[vertex] = vertex_index
                bake_coords.append(vertex.co.copy())
            indices.append(vertex_index)
            u = 0.5 + 0.46 * vertex.co.x / max(rx, 1e-8)
            v = 0.5 + 0.46 * (vertex.co.z - centre_z) / max(rz, 1e-8)
            uv = Vector((_clamp(u, 0.015, 0.985),
                         _clamp(v, 0.015, 0.985)))
            loop[uv_layer].uv = uv
            bake_loop_uvs.append(uv.copy())
        bake_faces.append(indices)
    if sample_uv is not None:
        # The replacement uses a dedicated continuous UV island.  Source UVs
        # are deliberately not copied because generated heads commonly split
        # the lips across many atlas islands; their color is projected below.
        for face in skin_faces:
            if not face.loops:
                continue
        uv_transferred = True
    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()

    texture_baked = False
    try:
        texture_baked = _bake_patch(
            source, obj.matrix_world, bake_coords, bake_faces,
            bake_loop_uvs, patch_mat, patch_image, S)
    finally:
        bpy.data.objects.remove(source, do_unlink=True)
    boundary_edges = 0
    boundary_samples = []
    verify_bm = bmesh.new()
    verify_bm.from_mesh(obj.data)
    for edge in verify_bm.edges:
        if len(edge.link_faces) != 1:
            continue
        mid = 0.5 * (edge.verts[0].co + edge.verts[1].co)
        radial = (mid.x / max(rx, 1e-8)) ** 2 + (
            (mid.z - centre_z) / max(rz, 1e-8)) ** 2
        if radial < 1.35 and mid.y <= front_limit + 0.08 * S:
            boundary_edges += 1
            if len(boundary_samples) < 24:
                boundary_samples.append({
                    "mid": [round(value, 5) for value in mid],
                    "length": round(edge.calc_length(), 5),
                })
    verify_bm.free()

    expected_open = 0 if inner_boundary else geo["segments"]
    return {
        "status": "applied" if (texture_baked and unmatched_patch_edges == 0)
        else "review",
        "confidence": geo["confidence"],
        "segments": geo["segments"],
        "rings": geo["ring_count"],
        "source_faces_removed": len(doomed),
        "cut_boundary_vertices": len(boundary),
        "cut_boundary_components": cut_component_report,
        "patch_vertices": len(added_verts) + len(tube),
        "patch_quad_faces": len(geo["faces"]) + len(wet),
        "transition_ring_vertices": 0,
        "transition_quads": 0,
        "transition_triangles": len(transition_faces),
        "transition_skipped": transition_skipped,
        "inner_boundary_vertices": len(inner_boundary) if inner_boundary else 0,
        "inner_transition_triangles": len(inner_transition_faces),
        "inner_transition_skipped": inner_transition_skipped,
        "surface_misses": geo["surface_misses"],
        "uv_transferred": uv_transferred,
        "texture_baked": texture_baked,
        "bake_image": patch_image.name,
        "bake_size": int(opts["bake_size"]),
        "local_boundary_edges": boundary_edges,
        "local_boundary_samples": boundary_samples,
        "unmatched_patch_edges": unmatched_patch_edges,
        "expected_tube_boundary_edges": expected_open,
    }
