"""Assemble expression-atlas PNGs into a labelled contact sheet."""
import argparse
import glob
import os

from PIL import Image, ImageDraw, ImageFont


parser = argparse.ArgumentParser()
parser.add_argument("input_dir")
parser.add_argument("output")
parser.add_argument("--columns", type=int, default=8)
parser.add_argument("--thumb", type=int, default=190)
args = parser.parse_args()

paths = sorted(glob.glob(os.path.join(args.input_dir, "[0-9][0-9]_*.png")))
if not paths:
    raise SystemExit("no expression PNGs found")
font = ImageFont.load_default(size=14)
label_h = 24
rows = (len(paths) + args.columns - 1) // args.columns
sheet = Image.new("RGB", (args.columns * args.thumb, rows * (args.thumb + label_h)),
                  (20, 20, 20))
draw = ImageDraw.Draw(sheet)
for i, path in enumerate(paths):
    image = Image.open(path).convert("RGB")
    image.thumbnail((args.thumb, args.thumb), Image.Resampling.LANCZOS)
    x = (i % args.columns) * args.thumb
    y = (i // args.columns) * (args.thumb + label_h)
    ox = x + (args.thumb - image.width) // 2
    oy = y + (args.thumb - image.height) // 2
    sheet.paste(image, (ox, oy))
    label = os.path.splitext(os.path.basename(path))[0].split("_", 1)[1]
    draw.text((x + 4, y + args.thumb + 4), label, fill=(235, 235, 235), font=font)
os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
sheet.save(args.output, quality=94)
print(args.output)
