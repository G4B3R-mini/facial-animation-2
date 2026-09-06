"""Stage 1: derive every landmark the build stage needs.

Nothing here is hardcoded to a particular head. All thresholds are expressed
as fractions of the model's own bounding box, so the numbers this produces
(seam curve, corner, condyle, cavity depth) are per-model by construction.
"""
import math
from . import util


def _fit_quadratic_in_x2(xs, vals):
    """Least squares fit  v = a + b*x^2 . Returns (a, b)."""
    n = len(xs)
    if n < 3:
        return (vals[0] if vals else 0.0), 0.0
    su = suu = sv = suv = 0.0
    for x, v in zip(xs, vals):
        u = x * x
        su += u
        suu += u * u
        sv += v
        suv += u * v
    den = n * suu - su * su
    if abs(den) < 1e-12:
        return sv / n, 0.0
    b = (n * suv - su * sv) / den
    a = (sv - b * su) / n
    return a, b


def _median(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    s = sorted(vals)
    return s[len(s) // 2]


def classify_shells(mesh, comp_of, groups, scale, teeth_hint=None):
    """Assign a role to each connected shell.

    teeth_hint maps a name to a [start, end) vertex range (from prepare.absorb).
    When present the teeth are taken from it rather than guessed: the size-based
    heuristic below assumes teeth are SMALL shells, which stops being true the
    moment someone subdivides them to clean up the silhouette.
    """
    total = len(mesh.vertices)
    info = {}
    for c, idx in groups.items():
        bb = util.bbox(mesh, idx)
        info[c] = {"verts": len(idx), "bbox": bb, "centre": util.centre(bb),
                   "sym": util.self_symmetry(mesh, idx, scale * 0.0065),
                   "crosses": util.crosses_midline(bb)}

    # FACE: when placed teeth are supplied, prefer the substantial shell that
    # encloses them in x/z and actually sits in front of them.  This resolves
    # Tripo busts where the face is fused to clothing (large/asymmetric) or a
    # symmetric hairstyle sits higher than the skin and wins the old heuristic.
    face = None
    if teeth_hint:
        hinted = [vi for lo, hi in teeth_hint.values()
                  for vi in range(lo, min(hi, total)) if vi in comp_of]
        if hinted:
            hinted_components = {comp_of[vi] for vi in hinted}
            tbb = util.bbox(mesh, hinted)
            tx = max(abs(tbb["x"][0]), abs(tbb["x"][1]))
            tz = 0.5 * (tbb["z"][0] + tbb["z"][1])
            front_limit = tbb["y"][0] + 0.035 * scale
            dental_candidates = []
            for c, d in info.items():
                bb = d["bbox"]
                if (c in hinted_components or d["verts"] < 0.04 * total
                        or not d["crosses"]):
                    continue
                half_width = max(abs(bb["x"][0]), abs(bb["x"][1]))
                if (bb["y"][0] <= front_limit
                        and bb["z"][0] <= tz <= bb["z"][1]
                        and half_width >= 0.75 * tx):
                    dental_candidates.append(c)
            if dental_candidates:
                face = max(dental_candidates,
                           key=lambda c: (info[c]["sym"], info[c]["verts"]))

    # Without dental evidence, use the tallest-sitting large symmetric shell.
    # Hair usually fails symmetry; body/armour usually fails height.
    best_z = -1e9
    if face is None:
        for c, d in info.items():
            if d["verts"] < 0.04 * total or not d["crosses"] or d["sym"] < 0.55:
                continue
            if d["centre"][2] > best_z:
                best_z = d["centre"][2]
                face = c
    if face is None:
        # Asymmetric topology can make an otherwise centred face score poorly
        # on vertex-for-vertex symmetry (Gwen is 0.37).  Hair is commonly the
        # largest shell, but the face is the tall shell that reaches furthest
        # down into the neck.  Prefer vertical span over raw vertex count.
        large = [c for c, d in info.items()
                 if d["verts"] >= 0.12 * total and d["crosses"]]
        face = max(large or list(info),
                   key=lambda c: (info[c]["bbox"]["z"][1]
                                  - info[c]["bbox"]["z"][0]))

    fbb = info[face]["bbox"]
    fdepth = fbb["y"][1] - fbb["y"][0]
    fheight = fbb["z"][1] - fbb["z"][0]

    # TEETH: small shells that cross the midline and sit inside the face,
    # forward of centre. Eyes and brows never cross the midline.
    teeth = []
    for c, d in info.items():
        if c == face or not d["crosses"]:
            continue
        if d["verts"] > 0.12 * total:
            continue
        cen = d["centre"]
        if cen[2] < fbb["z"][0] or cen[2] > fbb["z"][0] + 0.75 * fheight:
            continue
        if cen[1] > fbb["y"][0] + 0.55 * fdepth:
            continue
        yspan = d["bbox"]["y"][1] - d["bbox"]["y"][0]
        teeth.append((yspan, c))
    teeth.sort(reverse=True)
    teeth = [c for _, c in teeth[:2]]

    upper_all = []
    lower_all = []
    if teeth_hint:
        unnamed = []
        for nm, (lo, hi) in teeth_hint.items():
            cs = sorted(set(comp_of[vi] for vi in range(lo, min(hi, total))
                            if vi in comp_of and comp_of[vi] != face))
            low_name = nm.lower()
            if "upper" in low_name or "top" in low_name or "maxilla" in low_name:
                upper_all.extend(c for c in cs if c not in upper_all)
            elif "lower" in low_name or "bottom" in low_name or "mandible" in low_name:
                lower_all.extend(c for c in cs if c not in lower_all)
            else:
                unnamed.extend(c for c in cs if c not in unnamed)
        if unnamed:
            mid_z = _median([info[c]["centre"][2] for c in unnamed])
            upper_all.extend(c for c in unnamed if info[c]["centre"][2] >= mid_z)
            lower_all.extend(c for c in unnamed if info[c]["centre"][2] < mid_z)

    upper = lower = None
    if upper_all and lower_all:
        upper = max(upper_all, key=lambda c: info[c]["verts"])
        lower = max(lower_all, key=lambda c: info[c]["verts"])
    elif len(teeth) == 2:
        a, b = teeth
        if info[a]["centre"][2] >= info[b]["centre"][2]:
            upper, lower = a, b
        else:
            upper, lower = b, a
        upper_all = [upper]
        lower_all = [lower]

    # EYES / BROWS: mirror pairs, largest pair is the eyes
    teeth_set = set(upper_all + lower_all)
    pair_groups = {c: indices for c, indices in groups.items()
                   if c != face and c not in teeth_set}
    pairs = util.mirror_pairs(mesh, pair_groups)

    def pair_metrics(pair):
        boxes = [info[c]["bbox"] for c in pair]
        inv_n = 1.0 / len(pair)
        zc = sum(info[c]["centre"][2] for c in pair) * inv_n
        yc = sum(info[c]["centre"][1] for c in pair) * inv_n
        rounds = []
        for bb in boxes:
            sx = max(1e-8, bb["x"][1] - bb["x"][0])
            sz = max(1e-8, bb["z"][1] - bb["z"][0])
            rounds.append(min(sx, sz) / max(sx, sz))
        return zc, yc, sum(rounds) * inv_n

    eye_candidates = []
    for pair in pairs:
        zc, yc, roundness = pair_metrics(pair)
        zf = (zc - fbb["z"][0]) / max(fheight, 1e-8)
        if 0.48 <= zf <= 0.86 and yc <= fbb["y"][0] + 0.72 * fdepth:
            eye_candidates.append((roundness, min(len(groups[pair[0]]),
                                                   len(groups[pair[1]])), pair))
    eye_candidates.sort(reverse=True)
    eyes = eye_candidates[0][2] if eye_candidates else (pairs[0] if pairs else None)

    # A hairstyle or fused eyelid can leave only one eyeball as a separate
    # island.  Do not promote the paired, flat eyebrow shells to eyes merely
    # because they are bilateral.  A substantially rounder singleton below
    # that pair is better evidence; the build stage mirrors its lid landmark
    # so both eyelids can still blink even when only one eyeball is movable.
    excluded = {face} | teeth_set
    singleton_candidates = []
    for c, d in info.items():
        if c in excluded or d["verts"] < 20:
            continue
        bb = d["bbox"]
        sx = max(1e-8, bb["x"][1] - bb["x"][0])
        sz = max(1e-8, bb["z"][1] - bb["z"][0])
        roundness = min(sx, sz) / max(sx, sz)
        zf = (d["centre"][2] - fbb["z"][0]) / max(fheight, 1e-8)
        if 0.48 <= zf <= 0.78 and d["centre"][1] <= fbb["y"][0] + 0.72 * fdepth:
            singleton_candidates.append((roundness, d["verts"], c))
    singleton_candidates.sort(reverse=True)
    if singleton_candidates:
        pair_roundness = pair_metrics(eyes)[2] if eyes else 0.0
        best_single = singleton_candidates[0]
        eye_z = pair_metrics(eyes)[0] if eyes else float("inf")
        if (best_single[0] >= 0.72
                and best_single[0] > 1.35 * pair_roundness
                and info[best_single[2]]["centre"][2] < eye_z):
            eyes = (best_single[2],)
    brows = None
    if eyes:
        eye_z = pair_metrics(eyes)[0]
        above = []
        for pair in pairs:
            if pair == eyes:
                continue
            zc, _, roundness = pair_metrics(pair)
            if zc > eye_z + 0.012 * scale and zc < eye_z + 0.19 * scale:
                above.append((zc - eye_z, -roundness, pair))
        if above:
            above.sort()
            brows = above[0][2]

    # BODY: lowest-sitting wide shell
    body = None
    best = 1e9
    fwidth = fbb["x"][1] - fbb["x"][0]
    for c, d in info.items():
        if c == face or c in teeth:
            continue
        wide = (d["bbox"]["x"][1] - d["bbox"]["x"][0]) > 0.6 * fwidth
        if wide and d["centre"][2] < best:
            best = d["centre"][2]
            body = c

    assigned = set([face, body]) | teeth_set
    if eyes:
        assigned.update(eyes)
    if brows:
        assigned.update(brows)
    hair = [c for c in info if c not in assigned]
    hair.sort(key=lambda c: -info[c]["verts"])

    return {"info": info, "face": face, "teeth_upper": upper, "teeth_lower": lower,
            "teeth_upper_all": upper_all, "teeth_lower_all": lower_all,
            "eyes": list(eyes) if eyes else [], "brows": list(brows) if brows else [],
            "body": body, "hair": hair}


def lip_boundary_count(mesh, comp_of, face, half_w, front_cut, z_mid, scale):
    """Boundary edges at the lip line -- the signature of a real aperture.

    An INVAGINATED mouth (lips fold inward and run back into the head) is
    genuinely open and shows teeth, but has NO boundary edge here, and the
    z-column gap detector below cannot find it: the inner lip surfaces fill in
    the column, so the gap search locks onto the wrong feature and returns a
    seam curving the wrong way. Reference head: 9 such edges. Second head: 0.
    """
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(mesh)
    n = 0
    for e in bm.edges:
        if len(e.link_faces) != 1:
            continue
        if all(comp_of.get(v.index) == face
               and abs(v.co.x) <= 1.3 * half_w and v.co.y <= front_cut
               and abs(v.co.z - z_mid) < 0.09 * scale for v in e.verts):
            n += 1
    bm.free()
    return n


def measure_mouth(mesh, comp_of, roles, scale, mode="auto"):
    """Occlusion line, lip aperture per slice, fitted seam curve, corner."""
    face = roles["face"]
    up_ids = roles.get("teeth_upper_all") or ([roles["teeth_upper"]]
                                                if roles["teeth_upper"] is not None else [])
    lo_ids = roles.get("teeth_lower_all") or ([roles["teeth_lower"]]
                                                if roles["teeth_lower"] is not None else [])
    if not up_ids or not lo_ids:
        return None

    fbb = roles["info"][face]["bbox"]
    fdepth = fbb["y"][1] - fbb["y"][0]
    front_cut = fbb["y"][0] + 0.22 * fdepth

    up_indices = [vi for vi, c in comp_of.items() if c in up_ids]
    lo_indices = [vi for vi, c in comp_of.items() if c in lo_ids]
    tbb = util.bbox(mesh, up_indices)
    lbb = util.bbox(mesh, lo_indices)
    half_w = max(abs(tbb["x"][0]), abs(tbb["x"][1]),
                 abs(lbb["x"][0]), abs(lbb["x"][1]))
    z_lo = min(tbb["z"][0], lbb["z"][0])
    z_hi = max(tbb["z"][1], lbb["z"][1])
    z_mid = 0.5 * (z_lo + z_hi)
    z_win = max(0.09 * scale, 2.2 * (z_hi - z_lo))

    # bucket the relevant verts once, keyed by shell, to keep this O(n)
    face_pts = []
    up_pts = []
    lo_pts = []
    for vi, c in comp_of.items():
        co = mesh.vertices[vi].co
        if c == face:
            if co.y <= front_cut and (z_mid - z_win) <= co.z <= (z_mid + z_win):
                face_pts.append((co.x, co.y, co.z, mesh.vertices[vi].normal.y))
        elif c in up_ids:
            up_pts.append((co.x, co.y, co.z))
        elif c in lo_ids:
            lo_pts.append((co.x, co.y, co.z))

    if mode == "auto":
        nb = lip_boundary_count(mesh, comp_of, face, half_w, front_cut, z_mid, scale)
        mode = "aperture" if nb >= 4 else "invaginated"
        detected = {"lip_boundary_edges": nb}
    else:
        detected = {"lip_boundary_edges": None}

    step = scale * 0.0055
    win = step * 1.25
    min_gap = scale * 0.006
    slices = []
    x = -half_w * 1.25
    while x <= half_w * 1.25 + 1e-9:
        u_min = 9e9
        l_max = -9e9
        t_front = 9e9
        for px, py, pz in up_pts:
            if abs(px - x) <= win:
                if pz < u_min:
                    u_min = pz
                if py < t_front:
                    t_front = py
        for px, py, pz in lo_pts:
            if abs(px - x) <= win:
                if pz > l_max:
                    l_max = pz
                if py < t_front:
                    t_front = py
        occl = 0.5 * (u_min + l_max) if (u_min < 8e9 and l_max > -8e9) else z_mid

        gl = gh = 0.0
        amp = 0.0
        if mode == "invaginated":
            # the lip band is the run of surface whose normal points BACK into
            # the head; its z-extent is the opening at this column
            # A wider column than the aperture detector uses: the band has to
            # catch BOTH inner lip surfaces, and on a coarse face shell (1345
            # verts here against 2152 on the reference head) a step-sized
            # window picks up only the upper one.
            # Mirrored column: the align stage guarantees symmetry about x=0,
            # and doubling the sample count is what lets a coarse shell resolve
            # both lips at the midline, where one side alone has too few verts.
            win_i = max(win, 0.012 * scale)
            inner = [pz for px, py, pz, pn in face_pts
                     if abs(abs(px) - abs(x)) <= win_i and pn > 0.25]
            if len(inner) >= 3:
                inner.sort()
                # Walk OUTWARD from the occlusion line while the spacing
                # stays tight. The upper and lower inner-lip surfaces are two
                # separate runs bracketing occl, so picking a single run gets
                # only half the band; walking merges them and still stops
                # before the nose base, which also faces backward and would
                # otherwise stretch hi to 0.4497 against a true rim of 0.3931.
                # Loose enough to bridge the two inner-lip surfaces on a coarse
                # shell (their spacing reaches ~0.02 at the midline), tight
                # enough to stay off the nose base, which sits ~0.057 above the
                # upper rim.
                jump = max(3.5 * step, 0.032 * scale)
                i0 = min(range(len(inner)), key=lambda k: abs(inner[k] - occl))
                a_i = b_i = i0
                while a_i > 0 and (inner[a_i] - inner[a_i - 1]) <= jump:
                    a_i -= 1
                while b_i < len(inner) - 1 and (inner[b_i + 1] - inner[b_i]) <= jump:
                    b_i += 1
                if b_i - a_i >= 2:
                    gl, gh = inner[a_i], inner[b_i]
                    amp = gh - gl
                if amp < min_gap:
                    gl = gh = 0.0
                    amp = 0.0
        else:
            cand = []
            for px, py, pz, pn in face_pts:
                if abs(px - x) <= win:
                    cand.append((pz, py))
            cand.sort()
            for k in range(len(cand) - 1):
                a, b = cand[k][0], cand[k + 1][0]
                if (b - a) > min_gap and a <= occl <= b:
                    gl, gh, amp = a, b, b - a
                    break

        yl = yh = None
        if amp > 0.0:
            yl = 9e9
            yh = 9e9
            rw = max(min_gap * 0.45, amp * 0.18)
            for px, py, pz, pn in face_pts:
                if abs(px - x) > win:
                    continue
                if abs(pz - gl) < rw and py < yl:
                    yl = py
                if abs(pz - gh) < rw and py < yh:
                    yh = py
            yl = None if yl > 8e9 else yl
            yh = None if yh > 8e9 else yh

        slices.append({"x": x, "occl": occl,
                       "teeth_front": (t_front if t_front < 8e9 else None),
                       "amp": amp, "lo": gl, "hi": gh, "ylo": yl, "yhi": yh})
        x += step

    if mode == "invaginated":
        # Drop columns that resolved only part of the band. On a coarse shell a
        # column here and there catches just one inner lip surface and reports a
        # third of the true opening; left in, those outliers invert the fitted
        # seam curvature. The interpolation below fills them from neighbours.
        peak = max((s["amp"] for s in slices), default=0.0)
        for s in slices:
            if 0.0 < s["amp"] < 0.35 * peak:
                s["amp"] = 0.0
                s["lo"] = s["hi"] = 0.0
                s["ylo"] = s["yhi"] = None

    live = [s for s in slices if s["amp"] > 0.0 and s["ylo"] is not None and s["yhi"] is not None]
    if len(live) < 5:
        return None

    a0 = max(s["amp"] for s in live)

    # corner: where the modelled aperture A0*(1-(x/xc)^2) reaches zero
    xcs = []
    for s in live:
        r = s["amp"] / a0
        if 0.15 < r < 0.92 and abs(s["x"]) > 1e-6:
            xcs.append(abs(s["x"]) / math.sqrt(max(1e-6, 1.0 - r)))
    corner_x = _median(xcs) or (half_w * 1.15)
    corner_x = min(corner_x, half_w * 1.8)

    # Fit the seam over the RELIABLE CENTRAL BAND only. Outboard of ~0.6*corner
    # the gap detector starts locking onto the nasolabial crease instead of the
    # mouth, and including those slices flattens the curve so badly that the
    # seal leaves holes at the commissures.
    band = 0.62 * corner_x
    core = [s for s in live if abs(s["x"]) <= band]
    if len(core) < 4:
        core = live
    xs = [s["x"] for s in core]
    sz = [0.5 * (s["lo"] + s["hi"]) for s in core]
    sy = [min(s["ylo"], s["yhi"]) for s in core]

    seam_z_a, seam_z_b = _fit_quadratic_in_x2(xs, sz)
    seam_y_a, seam_y_b = _fit_quadratic_in_x2(xs, sy)
    live = core

    rim_lo_off = _median([s["ylo"] - (seam_y_a + seam_y_b * s["x"] ** 2) for s in live])
    rim_hi_off = _median([s["yhi"] - (seam_y_a + seam_y_b * s["x"] ** 2) for s in live])
    teeth_front = _median([s["teeth_front"] for s in live])

    # Keep the per-slice rims. A quadratic cannot represent a seam that rises
    # toward the corner then falls again, and fitting one leaves gaps at the
    # commissure. The build stage interpolates these measured values instead.
    first = min(slices.index(s) for s in live)
    last = max(slices.index(s) for s in live)
    kept = []
    for i in range(first, last + 1):
        s = slices[i]
        ok = s["amp"] > 0.0 and s["ylo"] is not None and s["yhi"] is not None
        kept.append({"x": s["x"],
                     "amp": s["amp"] if ok else None,
                     "lo": s["lo"] if ok else None,
                     "hi": s["hi"] if ok else None,
                     "ylo": s["ylo"] if ok else None,
                     "yhi": s["yhi"] if ok else None})
    # fill interior holes by linear interpolation between measured neighbours
    keys = ["amp", "lo", "hi", "ylo", "yhi"]
    for i in range(len(kept)):
        if kept[i]["amp"] is not None:
            continue
        p = i - 1
        while p >= 0 and kept[p]["amp"] is None:
            p -= 1
        n = i + 1
        while n < len(kept) and kept[n]["amp"] is None:
            n += 1
        if p < 0 or n >= len(kept):
            continue
        t = float(i - p) / float(n - p)
        for k in keys:
            kept[i][k] = kept[p][k] + (kept[n][k] - kept[p][k]) * t
    kept = [s for s in kept if s["amp"] is not None]
    # 3-tap smooth
    sm = [dict(s) for s in kept]
    for i in range(1, len(kept) - 1):
        for k in ["lo", "hi", "ylo", "yhi"]:
            sm[i][k] = (kept[i - 1][k] + 2.0 * kept[i][k] + kept[i + 1][k]) * 0.25

    return {"slices": sm,
            "mode": mode,
            "detect": detected,
            "slice_step": step,
            "aperture_centre": a0,
            "seam_z": [seam_z_a, seam_z_b],
            "seam_y": [seam_y_a, seam_y_b],
            "corner_x": corner_x,
            "rim_offsets": [rim_lo_off or 0.0, rim_hi_off or 0.0],
            "teeth_front_y": teeth_front,
            "occlusion_z": _median([s["occl"] for s in live]),
            "front_cut": front_cut,
            "n_slices": len(live)}


RIG_SCALE_PER_XC = 10.278   # reference head: bust z extent 0.8901 / XC 0.0866

CONDYLE_Z_XC = 1.50   # hinge height above the seam, in mouth-corner units
CONDYLE_Y_XC = 3.54   # hinge depth behind the seam, same units


def measure_condyle(mesh, comp_of, roles, scale, mouth=None):
    """Jaw hinge, anchored on the mouth corner.

    The old rule -- widest point of the face shell in its upper half -- is not
    robust to stylised proportions. On a big-cranium/narrow-jaw head it locks
    onto the TEMPLE instead of the ear and puts the hinge ~12% of head height
    too high and ~0.1 too far back, which visibly drags the whole face when the
    jaw opens.

    The mouth corner XC is a far stabler facial unit: XC/head_height measured
    0.121 and 0.128 on two very different heads. Expressed in those units the
    hinge that actually works sits at a fixed offset from the seam, and the
    hand-tuned and auto-generated rigs for the reference head agree to 2%:

        (cz - seam_z)/XC   1.536 hand   1.375 auto
        (cy - seam_y)/XC   3.531 hand   3.554 auto

    ear_half_width is still measured the old way; derive_params needs it for
    jaw_slope, and it is only a width there, not a position.
    """
    face = roles["face"]
    fbb = roles["info"][face]["bbox"]
    z0 = fbb["z"][0] + 0.45 * (fbb["z"][1] - fbb["z"][0])
    z1 = fbb["z"][0] + 0.85 * (fbb["z"][1] - fbb["z"][0])
    pts = []
    for vi, c in comp_of.items():
        if c != face:
            continue
        co = mesh.vertices[vi].co
        if z0 <= co.z <= z1:
            pts.append((co.x, co.y, co.z))
    band = scale * 0.011
    best_ax = -1.0
    best = (0.0, 0.5 * (z0 + z1))
    z = z0
    while z <= z1:
        mx = -1.0
        my = 0.0
        for px, py, pz in pts:
            if abs(pz - z) <= band and abs(px) > mx:
                mx = abs(px)
                my = py
        if mx > best_ax:
            best_ax = mx
            best = (my, z)
        z += band

    if mouth is None:
        # no mouth landmarks: nothing better to go on than the old heuristic
        return {"pivot": [0.0, best[0], best[1]], "ear_half_width": best_ax,
                "source": "widest_point"}

    XC = mouth["corner_x"]
    sz = mouth["seam_z"][0]
    sy = mouth["seam_y"][0]
    pivot = [0.0, sy + CONDYLE_Y_XC * XC, sz + CONDYLE_Z_XC * XC]
    return {"pivot": pivot, "ear_half_width": best_ax, "source": "mouth_anchored",
            "widest_point": [0.0, best[0], best[1]],
            "z_frac_of_widest": round((pivot[2] - sz) / max(1e-6, best[1] - sz), 3)}


def measure_cavity(mesh, comp_of, roles, mouth, scale):
    """Find the NEAREST interior surface sitting behind the mouth opening.

    The bag's rear wall has to be placed in front of this so the old crude
    cavity is occluded rather than interpenetrating. Searching for the
    *deepest* surface instead finds the back of the neck, which is useless.
    Restricted to a narrow column on the sight line through the lips.
    """
    face = roles["face"]
    sy = mouth["seam_y"][0]
    col = mouth["corner_x"] * 0.45
    zc = mouth["seam_z"][0]
    zw = max(scale * 0.02, mouth["aperture_centre"] * 1.2)
    margin = 0.045 * scale
    nearest = None
    for vi, c in comp_of.items():
        if c != face:
            continue
        co = mesh.vertices[vi].co
        if abs(co.x) > col:
            continue
        if co.z < zc - zw or co.z > zc + zw:
            continue
        if co.y < sy + margin:
            continue
        if nearest is None or co.y < nearest:
            nearest = co.y
    return {"interior_junk_y": nearest, "search_column": col, "search_z_half": zw}


def measure(obj, mouth_mode="auto", teeth_hint=None):
    mesh = obj.data
    comp_of, groups = util.islands(mesh)
    all_bb = util.bbox(mesh, list(range(len(mesh.vertices))))
    scale = all_bb["z"][1] - all_bb["z"][0]

    roles = classify_shells(mesh, comp_of, groups, scale, teeth_hint)
    mouth = measure_mouth(mesh, comp_of, roles, scale, mouth_mode)
    if mouth is None and mouth_mode == "auto":
        # Boundary counts distinguish clean apertures from folded mouths on
        # established topology, but a sealed or coarse generated lip can have
        # no boundary while still exposing a measurable upper/lower rim gap.
        # Try both explicit interpretations before declaring landmark failure.
        for fallback_mode in ("aperture", "invaginated"):
            mouth = measure_mouth(mesh, comp_of, roles, scale, fallback_mode)
            if mouth is not None:
                mouth.setdefault("detect", {})["auto_fallback"] = fallback_mode
                break
    condyle = measure_condyle(mesh, comp_of, roles, scale, mouth)
    cavity = measure_cavity(mesh, comp_of, roles, mouth, scale) if mouth else None

    # The exported scale -- the unit every constant in build.py is a fraction of
    # -- must be a FACIAL measurement. The whole-mesh z extent is not: on a bust
    # it includes neck and shoulders and over-reads by 1.24x-1.35x, inflating
    # every falloff until half the face is dragged along by the jaw.
    #
    # Head height would be the natural unit but "crown" is not stable: the face
    # shell excludes the scalp on one head (0.6895) and includes it on another.
    # The mouth corner XC is stable -- XC/head_height measured 0.121 and 0.128
    # on two very different faces -- so the rig unit is defined in XC, scaled so
    # the reference head reproduces its original value exactly and none of the
    # tuned constants below have to change.
    rig_scale = mouth["corner_x"] * RIG_SCALE_PER_XC if mouth else scale

    shells = {}
    for c, d in roles["info"].items():
        shells[str(c)] = {"verts": d["verts"], "sym": round(d["sym"], 3),
                          "bbox": dict((k, [round(x, 4) for x in v]) for k, v in d["bbox"].items())}

    return {"object": obj.name,
            "teeth_hint": teeth_hint,
            "scale": rig_scale,
            "mesh_scale": scale,
            "bbox": dict((k, [round(x, 4) for x in v]) for k, v in all_bb.items()),
            "verts": len(mesh.vertices),
            "has_uvs": len(mesh.uv_layers) > 0,
            "shells": shells,
            "roles": {"face": roles["face"], "teeth_upper": roles["teeth_upper"],
                      "teeth_lower": roles["teeth_lower"], "eyes": roles["eyes"],
                      "teeth_upper_all": roles.get("teeth_upper_all", []),
                      "teeth_lower_all": roles.get("teeth_lower_all", []),
                      "brows": roles["brows"], "body": roles["body"], "hair": roles["hair"]},
            "mouth": mouth,
            "condyle": condyle,
            "cavity": cavity}
