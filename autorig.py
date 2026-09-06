"""Headless entry point.

    blender -b head.blend -P autorig.py -- --out rigged.blend --json profile.json

Exit code is 0 only if every verification gate passed.
"""
import argparse
import hashlib
import json
import os
import struct
import sys

import bpy


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser(prog="autorig")
    ap.add_argument("--obj", default=None, help="mesh name (default: densest mesh)")
    ap.add_argument("--out", default=None, help="save the rigged .blend here")
    ap.add_argument("--json", default=None, help="dump profile + verification here")
    ap.add_argument("--face-guide", default=None,
                    help="artist-authored .faceguide.json from the Blender wizard")
    ap.add_argument("--no-tongue", action="store_true")
    ap.add_argument("--no-visemes", action="store_true")
    ap.add_argument("--measure-only", action="store_true")
    ap.add_argument("--weld-coincident", action="store_true",
                    help="reconnect exact duplicate vertices in split-quad exports")
    ap.add_argument("--weld-distance", type=float, default=1e-7,
                    help="object-space threshold for --weld-coincident")
    seam = ap.add_mutually_exclusive_group()
    seam.add_argument("--split-seam", dest="split_seam", action="store_true",
                      help="cut the lip band (default for invaginated mouths)")
    seam.add_argument("--no-split-seam", dest="split_seam", action="store_false",
                      help="keep a continuous lip band")
    ap.set_defaults(split_seam=None)
    ap.add_argument("--teeth", default=None,
                    help="comma-separated objects to absorb as teeth shells")
    ap.add_argument("--tongue-object", default=None,
                    help="use this existing object as the tongue instead of generating one")
    ap.add_argument("--mouth-mode", default="auto",
                    choices=["auto", "aperture", "invaginated"])
    ap.add_argument("--retopo-mouth", default="off",
                    choices=["off", "densify", "preview"],
                    help="add safe local lip density or create a fitted template preview")
    ap.add_argument("--retopo-cuts", type=int, default=1,
                    help="subdivision cuts for --retopo-mouth densify")
    ap.add_argument("--align", action="store_true",
                    help="shift the mesh so the midline (from mirror-pair shells) is x=0")
    ap.add_argument("--seal-rest", type=float, default=None,
                    help="resting lip-seal strength 0..1 (default 1.0); lower it "
                         "when a mouth modelled wide open over-seals at rest")
    ap.add_argument("--open-deg", type=float, default=18.0)
    ap.add_argument("--animate", action="store_true",
                    help="add automatic blinks, gaze, and brow animation")
    ap.add_argument("--lipsync-json", default=None,
                    help="Rhubarb JSON; also enables automatic facial animation")
    ap.add_argument("--audio", default=None,
                    help="audio file to add to the sequencer with lipsync")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--arkit", action="store_true",
                    help="generate measured ARKit 52 drafts and VRChat 15 visemes")
    ap.add_argument("--calibration-only", action="store_true",
                    help="retain only six editable mouth calibration poses")
    return ap.parse_args(argv)


def pick_mesh(name):
    """Resolve --obj, or work the roles out from the object names.

    The old default here was "densest mesh", which is how a wig got rigged:
    hair outweighs the head in most Tripo exports. Names are the reliable
    signal, so identify.py reads them, and anything it cannot settle is
    reported and refused rather than guessed at.
    """
    if name:
        o = bpy.data.objects.get(name)
        if o is None:
            raise SystemExit("no object named %r" % name)
        return o, None
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    if not meshes:
        raise SystemExit("no mesh objects in file")

    from tripo_face_rig import identify as ID
    assignment, notes = ID.identify(meshes)
    print("--- identify ---")
    for line in notes:
        print("  %s" % line)
    if assignment["head"] is None:
        raise SystemExit(
            "could not tell which mesh is the head. Meshes in this file: %s. "
            "Pass --obj explicitly."
            % ", ".join("%s (%d verts)" % (m.name, len(m.data.vertices))
                        for m in meshes))
    return assignment["head"], assignment


def basis_signature(obj):
    block = (obj.data.shape_keys.key_blocks.get("Basis")
             if obj.data.shape_keys else None)
    points = block.data if block else obj.data.vertices
    digest = hashlib.sha256()
    for point in points:
        digest.update(struct.pack("<3d", point.co.x, point.co.y, point.co.z))
    return digest.hexdigest()


def main():
    args = parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    from tripo_face_rig import measure as M, build as B, verify as V
    guide = None
    if args.face_guide:
        from tripo_face_rig import face_guides as GUIDES
        guide = GUIDES.load(args.face_guide)
        guide["path"] = os.path.abspath(args.face_guide)
        if not args.measure_only:
            check = GUIDES.validate_for_build(guide)
            if not check["valid"]:
                raise SystemExit("invalid guided build: " + "; ".join(check["issues"]))
        assignments = guide.get("objects") or {}
        if not args.obj:
            args.obj = assignments.get("head")
        if not args.teeth:
            teeth = [assignments.get("upper_teeth"),
                     assignments.get("lower_teeth")]
            args.teeth = ",".join(name for name in teeth if name) or None
        if not args.tongue_object:
            args.tongue_object = assignments.get("tongue")

    obj, auto = pick_mesh(args.obj)
    # Explicit flags always win; auto-detection only fills in what was blank.
    if auto:
        if not args.teeth and auto["teeth"]:
            args.teeth = ",".join(t.name for t in auto["teeth"])
        if not args.tongue_object and auto["tongue"] is not None:
            args.tongue_object = auto["tongue"].name

    from tripo_face_rig import prepare as PREP
    original_matrix = obj.matrix_world.copy()
    prep = {"normalize": PREP.normalize_transform(obj)}
    if guide and prep["normalize"]["changed"]:
        GUIDES.transform_local_markers(guide, matrix=original_matrix)
    if args.weld_coincident:
        prep["weld"] = PREP.weld_coincident(obj, args.weld_distance)
    tongue_obj = bpy.data.objects.get(args.tongue_object) if args.tongue_object else None
    teeth_hint = None
    if args.teeth:
        prep["absorb"] = PREP.absorb(obj, [n.strip() for n in args.teeth.split(",")])
        teeth_hint = prep["absorb"].get("ranges")
    if args.align:
        prep["align"] = PREP.align(obj, companions=[tongue_obj] if tongue_obj else ())
        if guide:
            GUIDES.transform_local_markers(
                guide, dx=prep["align"].get("applied_dx", 0.0))
    if prep:
        print("--- prepare ---")
        for k, v in prep.items():
            print("  %-8s %s" % (k, v))

    profile = M.measure(obj, args.mouth_mode, teeth_hint)
    if guide:
        GUIDES.apply_to_profile(profile, guide)
    if args.retopo_mouth != "off":
        from tripo_face_rig import retopo as RETOPO
        try:
            if args.retopo_mouth == "densify":
                prep["mouth_retopo"] = RETOPO.densify(
                    obj, profile, cuts=args.retopo_cuts)
                profile = M.measure(obj, args.mouth_mode, teeth_hint)
                if guide:
                    GUIDES.apply_to_profile(profile, guide)
            else:
                preview, geometry = RETOPO.create_preview(obj, profile)
                prep["mouth_retopo"] = {
                    "status": "preview", "object": preview.name,
                    "confidence": geometry["confidence"],
                    "segments": geometry["segments"],
                    "rings": geometry["ring_count"],
                    "vertices": len(geometry["vertices"]),
                    "faces": len(geometry["faces"]),
                }
        except RuntimeError as exc:
            print("FAIL: %s" % exc)
            return 3
        print("--- mouth retopo ---")
        for key, value in prep["mouth_retopo"].items():
            print("  %-26s %s" % (key, value))
    split_seam = ((profile.get("mouth") or {}).get("mode") == "invaginated"
                  if args.split_seam is None else args.split_seam)
    # when the seam is split on purpose, the lip band is excluded from the
    # baseline too, so the gate still catches holes torn anywhere else
    _skip = V.mouth_region(profile) if split_seam else None
    baseline = V.boundary_edges(obj.data, _skip)
    baseline_lips = (V.gate_lips_sealed(obj, None, profile, None)
                     if profile.get("mouth") else None)
    baseline_teeth = (V.teeth_exposure_baseline(obj, profile)
                      if profile.get("mouth") else 0)
    through_skin = (V.teeth_through_skin(obj, profile)
                    if profile.get("mouth") else 0)

    payload = {"prepare": prep, "profile": profile}
    if args.measure_only:
        print(json.dumps(payload, indent=1, default=float))
        if args.json:
            with open(args.json, "w") as f:
                json.dump(payload, f, indent=1, default=float)
        if args.out:
            bpy.ops.wm.save_as_mainfile(filepath=args.out)
            print("saved %s" % args.out)
        return 0

    if profile.get("mouth") is None:
        print("FAIL: could not locate mouth landmarks on %r." % obj.name)
        print("  Mouth detection anchors on teeth. Teeth used: %s"
              % (args.teeth or "NONE"))
        print("  Meshes in this file: %s"
              % ", ".join("%s (%d verts)" % (m.name, len(m.data.vertices))
                          for m in bpy.data.objects if m.type == 'MESH'))
        print("  If the head or the teeth were picked wrongly above, name "
              "them with --obj / --teeth.")
        return 2

    opts = {}
    if args.no_tongue:
        opts["tongue"] = False
    if args.no_visemes:
        opts["visemes"] = False
    if split_seam:
        opts["split_seam"] = True
    if args.seal_rest is not None:
        opts["seal_rest"] = max(0.0, min(1.0, args.seal_rest))
    if tongue_obj is not None:
        opts["tongue"] = False        # bone is still built; we bind the user's mesh

    report = B.build(obj, profile, opts)
    ao = bpy.data.objects[report["armature"]]
    if tongue_obj is not None:
        report["tongue_bound"] = PREP.bind_object_to_bone(tongue_obj, ao, "tongue")
    if args.arkit:
        from tripo_face_rig import expressions as EXPR
        report["expressions"] = EXPR.generate(
            obj, ao, profile,
            tongue_obj=tongue_obj or bpy.data.objects.get("tongue"),
            include_vrc=True)
        expr = report["expressions"]
        print("--- expressions ---")
        print("  ARKit functional          %d/%d" %
              (expr["arkit_nonempty"], expr["arkit_required"]))
        print("  VRChat visemes            %d/%d" %
              (expr["vrc_present"], len(EXPR.VRC_15)))
        if expr["arkit_empty"]:
            print("  partial                   %s" %
                  ", ".join(expr["arkit_empty"]))
        if args.calibration_only:
            report["calibration"] = EXPR.retain_calibration(
                obj, tongue_obj=tongue_obj or bpy.data.objects.get("tongue"))
    result = V.verify(obj, ao, profile, baseline_boundary=baseline,
                      open_deg=args.open_deg, opts=opts,
                      baseline_teeth=baseline_teeth,
                      baseline_lips=baseline_lips)

    if args.animate or args.lipsync_json:
        from tripo_face_rig import animate as ANIM
        report["animation"] = ANIM.animate(
            obj, ao, profile, lipsync_json=args.lipsync_json,
            audio_path=args.audio, fps=args.fps)

    payload["build"] = report
    payload["verify"] = result
    payload["baseline_teeth"] = baseline_teeth
    payload["baseline_lips"] = baseline_lips
    payload["teeth_through_skin"] = through_skin

    # The calibration wizard finalizes in-place later. Persist exactly the
    # measured profile and object relationships used for this build so it does
    # not need to re-measure a topology that has already been ripped.
    obj["face_rig_profile_json"] = json.dumps(profile, default=float)
    obj["face_rig_armature"] = ao.name
    obj["face_rig_tongue"] = ((tongue_obj or bpy.data.objects.get("tongue")).name
                              if (tongue_obj or bpy.data.objects.get("tongue")) else "")
    obj["face_rig_calibration_only"] = bool(args.calibration_only)
    obj["face_rig_calibration_approved"] = False
    obj["face_rig_basis_signature"] = basis_signature(obj)

    if through_skin > 4:
        print("WARNING: %d teeth polys sit IN FRONT of the lip line on the INPUT "
              "mesh, before rigging -- the source geometry is already broken. "
              "The gates only certify that rigging did not make it worse."
              % through_skin)
    print("--- gates ---")
    for k, v in result["checks"].items():
        print("  %-26s %s" % (k, "PASS" if v else "FAIL"))
    if result["failed"]:
        print("FAILED: %s" % ", ".join(result["failed"]))

    if args.json:
        with open(args.json, "w") as f:
            json.dump(payload, f, indent=1, default=float)
    if args.out:
        bpy.ops.wm.save_as_mainfile(filepath=args.out)
        print("saved %s" % args.out)

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
