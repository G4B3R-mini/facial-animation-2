"""Animate an existing rig without rebuilding geometry.

blender -b rig.blend --python-exit-code 1 --python reanimate.py -- animated.blend \
    --cues speech.json --audio speech.wav [--profile rig.json] [--obj head]

Uses the build profile embedded in the selected head, or an explicit JSON report.
Run in background Blender or a snapshot: this replaces animation actions.
"""
import argparse
import json
import sys
from pathlib import Path

import bpy
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import pick_face, face_armature
from tripo_face_rig import animate as A


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("--profile")
    parser.add_argument("--obj")
    parser.add_argument("--cues")
    parser.add_argument("--audio")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--brow", type=float, default=0.014)
    parser.add_argument("--jaw-scale", type=float)
    parser.add_argument("--viseme-scale", type=float)
    args = parser.parse_args(argv)
    if not 1 <= args.fps <= 120:
        parser.error("--fps must be between 1 and 120")
    for path in (args.cues, args.audio):
        if path and not Path(path).is_file():
            parser.error("Input not found: " + path)
    obj = pick_face(args.obj)
    arm = face_armature(obj)
    if arm is None or obj.data.shape_keys is None:
        raise RuntimeError("Selected head needs an armature and expression shape keys")
    if args.profile:
        with open(args.profile, encoding="utf-8") as handle:
            profile = json.load(handle)
        profile = profile.get("profile", profile)
    elif obj.get("face_rig_profile_json"):
        profile = json.loads(obj["face_rig_profile_json"])
    else:
        raise RuntimeError("No embedded build profile; supply --profile rig.json")
    if not profile.get("mouth"):
        raise RuntimeError("Profile has no measured mouth")
    if profile.get("object") and profile["object"] != obj.name:
        raise RuntimeError("Profile belongs to %r, not %r" % (profile["object"], obj.name))
    output = Path(args.output).resolve()
    inputs = [Path(path).resolve() for path in (bpy.data.filepath, args.cues, args.audio, args.profile) if path]
    if output in inputs:
        raise RuntimeError("Save animation to a separate output file")
    output.parent.mkdir(parents=True, exist_ok=True)
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    settings = A.speech_settings(profile)
    if args.jaw_scale is not None:
        settings["jaw_scale"] = args.jaw_scale
    if args.viseme_scale is not None:
        settings["viseme_scale"] = args.viseme_scale
    result = A.animate(obj, arm, profile,
                       lipsync_json=str(Path(args.cues).resolve()) if args.cues else None,
                       audio_path=str(Path(args.audio).resolve()) if args.audio else None, fps=args.fps,
                       settings=settings, brow_amount=args.brow)
    result["mesh"] = obj.name
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    result["saved"] = str(output)
    print("REANIMATE " + json.dumps(result))


if __name__ == "__main__":
    main()
