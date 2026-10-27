"""Cut a Muse Image render (character on a flat pale-grey backdrop) out to a transparent PNG.

Usage: cutout.py <in.png> <out.png> [--no-floor] [--thresh=N]  (lower thresh keeps white floating papers)

Method (kept reproducible on purpose):
  1. Pillow floodfill from the edges and corners, thresh=40.
  2. In the lowest 40% of the image, also drop low-saturation bright pixels (max-min<22, max>150)
     which is the floor shadow/gradient. --no-floor skips this (use for white paper piles).
  3. MedianFilter(5), binarise >128, MinFilter(7), GaussianBlur(1.5) to get a clean soft alpha.
  4. Darken semi-transparent edge pixels x0.55 to kill the light fringe.
  5. Crop to the bounding box.
Run with a Python that has Pillow (backend/.venv/bin/python).
"""
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SENTINEL = (255, 0, 255)


def cutout(src: str, dst: str, floor: bool = True, thresh: int = 40) -> None:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    work = im.copy()
    seeds = []
    step = 12
    for x in range(0, w, step):
        seeds += [(x, 0), (x, h - 1)]
    for y in range(0, h, step):
        seeds += [(0, y), (w - 1, y)]
    seeds += [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    for s in seeds:
        if work.getpixel(s) != SENTINEL:
            ImageDraw.floodfill(work, s, SENTINEL, thresh=thresh)
    px = work.load()
    ipx = im.load()
    mask = Image.new("L", (w, h), 255)
    mpx = mask.load()
    floor_y = int(h * 0.6)
    for y in range(h):
        for x in range(w):
            if px[x, y] == SENTINEL:
                mpx[x, y] = 0
            elif floor and y >= floor_y:
                r, g, b = ipx[x, y]
                if max(r, g, b) - min(r, g, b) < 22 and max(r, g, b) > 150:
                    mpx[x, y] = 0
    mask = mask.filter(ImageFilter.MedianFilter(5))
    mask = mask.point(lambda v: 255 if v > 128 else 0)
    mask = mask.filter(ImageFilter.MinFilter(7))
    mask = mask.filter(ImageFilter.GaussianBlur(1.5))
    # darken the semi-transparent rim so no light halo shows on a dark background
    rgb = im.copy()
    rpx = rgb.load()
    mpx = mask.load()
    for y in range(h):
        for x in range(w):
            a = mpx[x, y]
            if 0 < a < 255:
                r, g, b = rpx[x, y]
                rpx[x, y] = (int(r * 0.55), int(g * 0.55), int(b * 0.55))
    out = rgb.convert("RGBA")
    out.putalpha(mask)
    bbox = mask.point(lambda v: 255 if v > 8 else 0).getbbox()
    if bbox:
        out = out.crop(bbox)
    if out.height > 1100:  # keep committed assets small
        out = out.resize((round(out.width * 1100 / out.height), 1100), Image.LANCZOS)
    out.save(dst, optimize=True)
    print(f"{dst}: {out.size}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    th = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--thresh=")), 40)
    cutout(args[0], args[1], floor="--no-floor" not in sys.argv, thresh=th)
