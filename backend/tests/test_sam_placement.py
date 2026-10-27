"""SAM mask placement, live-verified 2026-10-27: the mask raster covers the BOX only (not the image) and sits at the box corner
plus the token's x/y. A 760x1100 label with box 18,261..737,1006 (inclusive) came back as a 746x720 (H x W) mask."""

import base64
import io

from PIL import Image

from app import media

W, H = 760, 1100
BOX = (18, 261, 737, 1006)
MASK_H, MASK_W = 746, 720


def token(x=0, y=0, box=BOX, h=MASK_H, w=MASK_W):
    # ones with a hole in the middle: under the max-coverage cut-off, extent = the whole raster
    flat = [0 if w // 4 <= i < 3 * w // 4 and h // 4 <= j < 3 * h // 4 else 1 for j in range(h) for i in range(w)]
    packed = bytes(sum(bit << (7 - k) for k, bit in enumerate(flat[n : n + 8])) for n in range(0, len(flat), 8))
    head = f"<|box;x1={box[0]};y1={box[1]};x2={box[2]};y2={box[3]};w={W};h={H}|>" if box else ""
    return f"<0f>1 {head}<|mask;x={x};y={y};data={h},{w},!{base64.b85encode(packed).decode()}|>"


def label_png():
    buf = io.BytesIO()
    Image.new("RGB", (W, H), (240, 240, 240)).save(buf, format="PNG")
    return buf.getvalue()


def test_mask_offset_is_parsed_and_defaults_to_zero():
    rec = media.parse_sam_text(token(x=5, y=7))[0]
    assert (rec.mask_x, rec.mask_y, rec.mask_h, rec.mask_w) == (5, 7, MASK_H, MASK_W)
    assert rec.origin() == (18 + 5, 261 + 7)
    bare = media.parse_sam_text("<0f>1 <|mask;data=4,4,!" + base64.b85encode(b"\xff\xff").decode() + "|>")[0]
    assert (bare.mask_x, bare.mask_y) == (0, 0) and bare.origin() == (0, 0)
    assert media.parse_sam_text(token(box=None))[0].origin() == (0, 0)


def test_region_places_the_box_sized_mask_at_the_box_corner():
    rec = media.parse_sam_text(token())[0]
    assert media.region_from_record(rec, W, H) == [0.0237, 0.2373, 0.9711, 0.9155]


def test_cutout_is_the_box_sized_raster_pasted_at_the_box_corner():
    rec = media.parse_sam_text(token())[0]
    img = Image.open(io.BytesIO(media.cutout_png(label_png(), rec)))
    assert img.mode == "RGBA" and img.size == (MASK_W, MASK_H)
    assert img.getpixel((0, 0))[3] == 255 and img.getpixel((MASK_W // 2, MASK_H // 2))[3] == 0  # the hole


def test_offset_shifts_the_placement():
    rec = media.parse_sam_text(token(x=2, y=3, h=100, w=100, box=(100, 200, 199, 299)))[0]
    assert media.region_from_record(rec, W, H) == [round(102 / W, 4), round(203 / H, 4), round(202 / W, 4), round(303 / H, 4)]
