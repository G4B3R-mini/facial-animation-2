"""Build a labelled contact sheet from qa_render.py output.

Runs OUTSIDE Blender, under any python with Pillow:

    python make_sheet.py QA_DIR [--tag female] [--kind bust|mouth]

Kept separate because Blender's embedded interpreter usually cannot pip-install
into Program Files, so importing PIL inside Blender is unreliable.

Also builds a two-row before/after comparison:

    python make_sheet.py QA_DIR --compare TAG_BEFORE TAG_AFTER [--kind mouth]
"""
import sys, os, glob, json

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("Pillow is required:  python -m pip install pillow")

args = sys.argv[1:]
if not args:
    sys.exit(__doc__)
qa_dir = args[0]
kind = args[args.index("--kind") + 1] if "--kind" in args else "bust"
tag = args[args.index("--tag") + 1] if "--tag" in args else None
compare = None
if "--compare" in args:
    i = args.index("--compare")
    compare = (args[i + 1], args[i + 2])

BG = (24, 24, 26)
FG = (255, 215, 110)
PAD, LAB = 8, 22


def load(t, k):
    out = []
    for p in sorted(glob.glob(os.path.join(qa_dir, "%s_%s_*.png" % (t, k)))):
        name = os.path.basename(p)[len("%s_%s_" % (t, k)):-4]
        out.append((name, Image.open(p).convert("RGB")))
    # neutral first, then the rest in filename order
    out.sort(key=lambda kv: (kv[0] != "neutral", kv[0]))
    return out


if compare:
    rows = [(t, load(t, kind)) for t in compare]
    rows = [(t, ims) for t, ims in rows if ims]
    if not rows:
        sys.exit("no images found for tags %s in %s" % (list(compare), qa_dir))
    names = [n for n, _ in rows[0][1]]
    w, h = rows[0][1][0][1].size
    cols = len(names)
    sheet = Image.new("RGB", (PAD + cols * (w + PAD),
                              PAD + len(rows) * (h + PAD + LAB) + LAB), BG)
    d = ImageDraw.Draw(sheet)
    for ri, (t, ims) in enumerate(rows):
        y = PAD + LAB + ri * (h + PAD + LAB)
        d.text((PAD, y - 16), t, fill=FG)
        by = dict(ims)
        for ci, n in enumerate(names):
            if n not in by:
                continue
            x = PAD + ci * (w + PAD)
            sheet.paste(by[n], (x, y))
            d.text((x + 4, y + 4), n, fill=(255, 255, 255))
    out = os.path.join(qa_dir, "SHEET_compare_%s_%s_%s.jpg" % (compare[0], compare[1], kind))
    sheet.save(out, quality=93)
    print(out)
    sys.exit(0)

tags = [tag] if tag else sorted(
    {os.path.basename(p).split("_" + kind + "_")[0]
     for p in glob.glob(os.path.join(qa_dir, "*_%s_*.png" % kind))})
for t in tags:
    ims = load(t, kind)
    if not ims:
        continue
    w, h = ims[0][1].size
    cols = min(4, len(ims))
    rows_n = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (PAD + cols * (w + PAD),
                              PAD + rows_n * (h + PAD + LAB)), BG)
    d = ImageDraw.Draw(sheet)
    for i, (n, im) in enumerate(ims):
        r, c = divmod(i, cols)
        x = PAD + c * (w + PAD)
        y = PAD + r * (h + PAD + LAB) + LAB
        sheet.paste(im, (x, y))
        d.text((x + 4, y - 16), n, fill=FG)
    out = os.path.join(qa_dir, "SHEET_%s_%s.jpg" % (t, kind))
    sheet.save(out, quality=93)
    print(out)
