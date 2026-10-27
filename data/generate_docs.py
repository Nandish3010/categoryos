#!/usr/bin/env python3
"""Synthetic vendor documents for CategoryOS (all FICTIONAL, every page marked SAMPLE).

Writes, per vendor, under data/synthetic/vendors/<VID>/docs/:
  * licence certificates (FSSAI / GST style) as slightly rotated, noisy "scans" (JPEG),
  * product label back-of-pack photos with a nutrition / claims panel for hero SKUs (JPEG),
  * a supplier price list (PDF, plus the page image it was made from),
  * manifest.json (what the vendor says each file is) and truth.json (what is really printed, with boxes).
Then writes the mock vision fixtures (backend/fixtures/mock/{intake,catalog}/docs_*.json) that mirror what the vision
models return for these pages, so MODEL_MODE=mock runs the real pipeline.

Planted discrepancies (the demo story):
  V002  application: FSSAI valid until 2027-11-30   scan: valid until 30 NOV 2026 (about a month away)
  V001  label HP-D01 prints 30% protein             SKU sheet and listing say 32%
  V001  price list HP-D06 prints Rs. 3,352.00       SKU sheet cost is Rs. 3,325 (HP-D01's 956.50 agrees)

Usage (needs Pillow and PyYAML, both in the backend environment):
    cd backend && uv run python ../data/generate_docs.py
Deterministic: seeded per page, so running it again reproduces the same files. data/generate.py is untouched."""

import csv
import json
import math
import random
import re
import sys
import time
from pathlib import Path

import yaml
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
VENDORS = HERE / "synthetic" / "vendors"
FIXTURES = REPO / "backend" / "fixtures" / "mock"
POLICY = REPO / "config" / "policy.yaml"

FIXED_TIME = time.struct_time((2026, 10, 1, 9, 0, 0, 3, 274, 0))  # PDF metadata dates, so the file is reproducible
PAPER = (247, 244, 234)
INK = (28, 31, 38)
GREY = (96, 102, 112)
RED = (176, 52, 44)
BED = (188, 190, 194)


def font(size: int):
    return ImageFont.load_default(size=size)


class Canvas:
    """A page being drawn. Every field value that should be machine-read registers its pixel box."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.img = Image.new("RGB", (w, h), PAPER)
        self.d = ImageDraw.Draw(self.img)
        self.fields: list[dict] = []
        self.panel: tuple[int, int, int, int] | None = None

    def text(self, x: int, y: int, txt: str, size: int = 22, bold: bool = False, fill=INK) -> tuple[int, int, int, int]:
        f = font(size)
        if bold:
            self.d.text((x + 1, y), txt, font=f, fill=fill)
        self.d.text((x, y), txt, font=f, fill=fill)
        return self.d.textbbox((x, y), txt, font=f)

    def field(self, name: str, x: int, y: int, txt: str, size: int = 24, bold: bool = True, sku: str | None = None) -> None:
        bb = self.text(x, y, txt, size, bold)
        self.fields.append({"name": name, "value": txt, "px": [bb[0] - 3, bb[1] - 2, bb[2] + 3, bb[3] + 3], "sku_code": sku})

    def wrap(self, x: int, y: int, txt: str, width: int, size: int = 20, leading: int = 28, fill=INK) -> int:
        f = font(size)
        line = ""
        for word in txt.split():
            trial = f"{line} {word}".strip()
            if self.d.textlength(trial, font=f) <= width:
                line = trial
            else:
                self.d.text((x, y), line, font=f, fill=fill)
                y += leading
                line = word
        if line:
            self.d.text((x, y), line, font=f, fill=fill)
            y += leading
        return y

    def seal(self, cx: int, cy: int, r: int) -> None:
        for k, rr in enumerate((r, r - 8, r - 30)):
            self.d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=(60, 80, 140), width=3 if k != 1 else 1)
        self.text(cx - 48, cy - 22, "SAMPLE", 26, True, (60, 80, 140))
        self.text(cx - 38, cy + 6, "SEAL", 22, True, (60, 80, 140))

    def barcode(self, x: int, y: int, w: int, h: int, rng: random.Random) -> None:
        cx = x
        while cx < x + w:
            bar = rng.choice((2, 3, 4, 6))
            self.d.rectangle((cx, y, cx + bar - 1, y + h), fill=INK)
            cx += bar + rng.choice((2, 3, 5))


def watermark(c: Canvas, word: str = "SAMPLE") -> None:
    layer = Image.new("L", (c.w, c.h), 0)
    ImageDraw.Draw(layer).text((c.w // 2 - 190, c.h // 2 - 60), word, font=font(150), fill=34)
    layer = layer.rotate(32, resample=Image.BICUBIC)
    c.img = Image.composite(Image.new("RGB", (c.w, c.h), (150, 40, 40)), c.img, layer)
    c.d = ImageDraw.Draw(c.img)


def scan(c: Canvas, angle: float, seed: str) -> tuple[Image.Image, list[dict], list[float] | None]:
    """Photograph the page: rotate it slightly on a darker bed, soften, add grain and an uneven light. Returns the image,
    the fields with normalised boxes and the panel box (in the rotated frame)."""
    w, h = c.w, c.h
    cx, cy = w / 2, h / 2
    th = math.radians(angle)

    def move(x: float, y: float) -> tuple[float, float]:
        dx, dy = x - cx, y - cy
        return cx + dx * math.cos(th) + dy * math.sin(th), cy - dx * math.sin(th) + dy * math.cos(th)

    def hull(px: list[float] | tuple[int, int, int, int]) -> list[float]:
        x0, y0, x1, y1 = px
        pts = [move(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return [round(max(min(xs) / w, 0.0), 4), round(max(min(ys) / h, 0.0), 4), round(min(max(xs) / w, 1.0), 4), round(min(max(ys) / h, 1.0), 4)]

    img = c.img.rotate(angle, resample=Image.BICUBIC, fillcolor=BED).filter(ImageFilter.GaussianBlur(0.55))
    rng = random.Random(seed)
    grain = Image.frombytes("L", (w, h), rng.randbytes(w * h))
    img = Image.blend(img, grain.convert("RGB"), 0.07)
    light = Image.linear_gradient("L").rotate(rng.choice((0, 90, 180, 270))).resize((w, h)).point(lambda v: 228 + v // 10)
    img = ImageChops.multiply(img, Image.merge("RGB", (light, light, light)))
    fields = [{**f, "bbox": hull(f["px"])} for f in c.fields]
    return img, fields, (hull(c.panel) if c.panel else None)


# ---------------------------------------------------------------- documents


def licence(v: dict, kind: str) -> Canvas:
    """kind: 'fssai' (food business licence) or 'gst' (tax registration). v: licence_number, holder, city, valid_from, valid_until."""
    c = Canvas(840, 1180)
    d = c.d
    d.rectangle((24, 24, c.w - 24, c.h - 24), outline=INK, width=4)
    d.rectangle((38, 38, c.w - 38, c.h - 38), outline=GREY, width=1)
    c.text(120, 60, "SAMPLE DOCUMENT - FICTIONAL - NOT A REAL LICENCE", 20, True, RED)
    title = "FOOD BUSINESS LICENCE" if kind == "fssai" else "GST REGISTRATION CERTIFICATE"
    sub = "Issued under the Sample Food Safety Rules (fictional)" if kind == "fssai" else "Issued under the Sample Goods and Services Tax Rules (fictional)"
    c.text(120 if kind == "fssai" else 70, 130, title, 40, True)
    c.text(110, 190, sub, 21, False, GREY)
    d.line((70, 240, c.w - 70, 240), fill=GREY, width=2)
    rows = [
        ("Licence number" if kind == "fssai" else "Registration number", "licence_number", v["licence_number"]),
        ("Name of holder", "holder_name", v["holder"]),
        ("Business address", None, f"Plot 12, Industrial Estate, {v['city']}"),
        ("Kind of business", None, "Manufacturer and trader" if kind == "fssai" else "Regular taxpayer"),
        ("Valid from", "valid_from", v["valid_from"]),
        ("Valid until", "valid_until", v["valid_until"]),
        ("Issued by", None, "Sample Licensing Authority"),
    ]
    y = 300
    for label, name, value in rows:
        c.text(70, y, label, 22, False, GREY)
        if name:
            c.field(name, 330, y - 2, value, 27, True)
        else:
            c.text(330, y - 2, value, 25, True)
        y += 92
    c.seal(180, 1000, 70)
    d.line((520, 1040, 780, 1040), fill=INK, width=2)
    c.text(540, 1052, "Designated Officer (sample)", 19, False, GREY)
    c.text(70, 1110, "This is a computer-generated sample for software testing.", 17, False, GREY)
    watermark(c)
    return c


def label(v: dict) -> Canvas:
    """Back-of-pack photo. v: brand, product, protein (e.g. '30.0 %'), fat, net, mrp, fssai, claims, ingredients, sku, extras."""
    c = Canvas(760, 1100)
    d = c.d
    d.rectangle((0, 0, c.w, 150), fill=(46, 84, 70))
    c.text(40, 40, v["brand"].upper(), 50, True, (240, 240, 232))
    c.text(40, 106, "SAMPLE LABEL - FICTIONAL", 19, True, (230, 196, 120))
    c.field("product_name", 40, 175, v["product"], 28, True, v["sku"])
    c.text(40, 224, "BACK OF PACK", 18, False, GREY)
    top = 270
    c.panel = (28, top, c.w - 28, 1000)
    d.rectangle(c.panel, outline=INK, width=4)
    y = top + 18
    c.text(48, y, "GUARANTEED ANALYSIS", 26, True)
    y += 52
    for name, value in v["analysis"]:
        c.text(60, y, name, 22, False, INK)
        if name.startswith("Crude Protein"):
            c.field("protein_pct", 470, y - 2, value, 25, True, v["sku"])
        else:
            c.text(470, y - 2, value, 24, True)
        d.line((52, y + 36, c.w - 52, y + 36), fill=GREY, width=1)
        y += 50
    y += 14
    c.text(48, y, "INGREDIENTS", 20, True, GREY)
    y = c.wrap(48, y + 32, v["ingredients"], c.w - 110, 19, 26)
    y += 12
    c.text(48, y, "CLAIMS", 20, True, GREY)
    c.field("claims_text", 48, y + 32, v["claims"], 21, False, v["sku"])
    y += 96
    d.line((40, y, c.w - 40, y), fill=INK, width=2)
    y += 16
    c.text(48, y, "Net quantity:", 21, False, GREY)
    c.field("net_quantity", 230, y - 2, v["net"], 25, True, v["sku"])
    y += 48
    c.text(48, y, "MRP:", 21, False, GREY)
    c.field("mrp", 230, y - 2, v["mrp"], 25, True, v["sku"])
    c.text(400, y + 2, "(incl. of all taxes)", 18, False, GREY)
    y += 48
    c.text(48, y, "Lic. No.:", 21, False, GREY)
    c.field("fssai_number", 230, y - 2, v["fssai"], 23, True, v["sku"])
    y += 48
    c.text(48, y, v["extras"], 19, False, GREY)
    rng = random.Random(v["sku"])
    c.barcode(60, 1022, 360, 50, rng)
    c.text(450, 1034, "SAMPLE - NOT FOR SALE", 18, True, RED)
    watermark(c)
    return c


def price_list(v: dict) -> Canvas:
    c = Canvas(900, 1280)
    d = c.d
    c.text(50, 40, "SUPPLIER PRICE LIST", 40, True)
    c.text(50, 96, "SAMPLE DOCUMENT - FICTIONAL", 20, True, RED)
    c.text(50, 140, v["company"], 24, True)
    c.text(50, 176, f"Effective {v['effective']}  |  Prices per unit, exclusive of GST", 19, False, GREY)
    x_code, x_name, x_pack, x_price = 50, 160, 560, 700
    y = 230
    d.rectangle((40, y - 8, c.w - 40, y + 38), fill=(226, 228, 222))
    for x, t in ((x_code, "Code"), (x_name, "Product"), (x_pack, "Pack"), (x_price, "Cost (Rs)")):
        c.text(x, y, t, 22, True)
    y += 62
    for row in v["rows"]:
        c.text(x_code, y, row["code"], 21, False)
        name = row["name"] if len(row["name"]) <= 34 else row["name"][:33] + "."
        c.text(x_name, y, name, 21, False)
        c.text(x_pack, y, row["pack"], 21, False)
        c.field("price", x_price, y - 2, row["price"], 23, True, row["code"])
        d.line((40, y + 38, c.w - 40, y + 38), fill=(200, 200, 194), width=1)
        y += 66
    c.text(50, c.h - 70, "Terms: payment as agreed. Valid for orders placed during the effective month.", 17, False, GREY)
    return c


# ---------------------------------------------------------------- vendor data


def sheet_rows(vid: str) -> list[dict]:
    with open(VENDORS / vid / "sku_sheet.csv", newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    return [dict(zip(rows[0], r)) for r in rows[1:] if any(r)]


def sheet_costs(vid: str) -> list[dict]:
    """code, name, pack, cost (float or None) from the vendor's sheet, parsed leniently."""
    out = []
    for r in sheet_rows(vid):
        keys = list(r)
        code = r[keys[0]]
        name = r[keys[1]]
        pack = r[keys[2]]
        cost_key = next((k for k in keys if re.search(r"cost", k, re.I)), None)
        raw = r.get(cost_key, "") if cost_key else ""
        m = re.search(r"\d[\d,]*(?:\.\d+)?", raw)
        out.append({"code": code, "name": name, "pack": pack, "cost": float(m.group(0).replace(",", "")) if m else None})
    return out


def money(v: float) -> str:
    return f"{v:,.2f}"


APPLICATIONS = {vid: json.loads((VENDORS / vid / "application.json").read_text()) for vid in ("V001", "V002", "V003", "V004")}


def holder(vid: str) -> str:
    return APPLICATIONS[vid]["company_name"]


def city(vid: str) -> str:
    return APPLICATIONS[vid]["city"]


def number(vid: str, doc_type: str) -> str:
    return next(d["number"] for d in APPLICATIONS[vid]["documents"] if d["type"] == doc_type)


# Each spec: (file, kind, declares, sku, canvas builder, angle, extra manifest title)
def specs(vid: str) -> list[dict]:
    out: list[dict] = []

    def cert(file: str, kind: str, declares: str, doc_type: str, valid_from: str, valid_until: str, angle: float, title: str) -> None:
        out.append(
            {
                "file": file, "kind": "licence_certificate", "declares": declares, "title": title, "angle": angle, "format": "jpg",
                "canvas": lambda: licence(
                    {"licence_number": number(vid, doc_type), "holder": holder(vid), "city": city(vid), "valid_from": valid_from, "valid_until": valid_until}, kind
                ),
            }
        )

    if vid == "V001":
        cert("fssai_certificate.jpg", "fssai", "FSSAI", "FSSAI", "16 AUG 2022", "15 AUG 2027", 1.1, "FSSAI licence certificate (scan)")
        cert("gst_certificate.jpg", "gst", "GST", "GST", "01 APR 2020", "31 MAR 2030", -0.8, "GST registration certificate (scan)")
    if vid == "V002":
        # PLANTED: the application declares FSSAI valid until 2027-11-30; the scan shows 30 NOV 2026.
        cert("fssai_certificate.jpg", "fssai", "FSSAI", "FSSAI", "01 DEC 2023", "30 NOV 2026", -1.3, "FSSAI licence certificate (scan)")
        cert("gst_certificate.jpg", "gst", "GST", "GST", "01 APR 2023", "31 MAR 2030", 0.9, "GST registration certificate (scan)")
    if vid == "V003":
        cert("gst_certificate.jpg", "gst", "GST", "GST", "01 APR 2021", "31 MAR 2030", 0.7, "GST registration certificate (scan)")
    if vid == "V004":
        cert("fssai_certificate.jpg", "fssai", "FSSAI", "FSSAI", "01 APR 2023", "31 MAR 2026", -1.0, "FSSAI licence certificate (scan)")

    if vid in ("V001", "V002"):
        rows = []
        for r in sheet_costs(vid):
            if r["cost"] is None:
                continue
            price = r["cost"]
            if vid == "V001" and r["code"] == "HP-D06":
                price = 3352.0  # PLANTED: the sheet says 3325 (digit transposition)
            rows.append({"code": r["code"], "name": r["name"], "pack": r["pack"], "price": money(price)})
        out.append(
            {
                "file": "price_list.pdf", "kind": "price_list", "declares": None, "title": "Supplier price list (PDF)", "format": "pdf",
                "pages": ["price_list.p1.png"], "angle": 0.0,
                "canvas": lambda rows=rows: price_list({"company": holder(vid), "effective": "01 OCT 2026", "rows": rows}),
            }
        )

    if vid == "V001":
        brand = APPLICATIONS[vid]["brand_name"]
        out.append(
            {
                "file": "label_HP-D01.jpg", "kind": "product_label", "declares": None, "sku_code": "HP-D01", "angle": -1.6, "format": "jpg",
                "title": "Pack label HP-D01 (photo)",
                "canvas": lambda: label(
                    {
                        "brand": brand, "sku": "HP-D01", "product": "Alpine Chicken & Sweet Potato Adult",
                        # PLANTED: the label prints 30 percent protein; the sheet and the listing say 32 percent.
                        "analysis": [("Crude Protein (min)", "30.0 %"), ("Crude Fat (min)", "16.0 %"), ("Crude Fibre (max)", "4.0 %"), ("Moisture (max)", "10.0 %"), ("Ash (max)", "8.0 %")],
                        "ingredients": "Chicken (26%), sweet potato, chicken fat, dried egg, flaxseed, minerals, vitamins, omega 3 and 6 oils.",
                        "claims": "Grain-free. Single-source chicken. Supports joint health.",
                        "net": "1.5 kg", "mrp": "Rs. 1,499", "fssai": number(vid, "FSSAI"), "extras": "Best before: 12 months from packing.",
                    }
                ),
            }
        )
        out.append(
            {
                "file": "label_HP-D02.jpg", "kind": "product_label", "declares": None, "sku_code": "HP-D02", "angle": 1.4, "format": "jpg",
                "title": "Pack label HP-D02 (photo)",
                "canvas": lambda: label(
                    {
                        "brand": brand, "sku": "HP-D02", "product": "Alpine Chicken & Sweet Potato Adult Value Pack",
                        "analysis": [("Crude Protein (min)", "32.0 %"), ("Crude Fat (min)", "16.0 %"), ("Crude Fibre (max)", "4.0 %"), ("Moisture (max)", "10.0 %"), ("Ash (max)", "8.0 %")],
                        "ingredients": "Chicken (28%), sweet potato, chicken fat, dried egg, flaxseed, minerals, vitamins, omega 3 and 6 oils.",
                        "claims": "Grain-free. Single-source chicken.",
                        "net": "6 kg", "mrp": "Rs. 4,999", "fssai": number(vid, "FSSAI"), "extras": "Best before: 12 months from packing.",
                    }
                ),
            }
        )
    if vid == "V002":
        out.append(
            {
                "file": "label_MW-T01.jpg", "kind": "product_label", "declares": None, "sku_code": "MW-T01", "angle": 1.0, "format": "jpg",
                "title": "Pack label MW-T01 (photo)",
                "canvas": lambda: label(
                    {
                        "brand": APPLICATIONS[vid]["brand_name"], "sku": "MW-T01", "product": "Tuna Creamy Lick Treat",
                        "analysis": [("Crude Fat (min)", "1.5 %"), ("Crude Fibre (max)", "0.5 %"), ("Moisture (max)", "88.0 %"), ("Ash (max)", "2.0 %")],
                        "ingredients": "Tuna (92%), water, tapioca starch, taurine.",
                        "claims": "No grain. Lickable tuna puree.",
                        "net": "60 g", "mrp": "Rs. 199", "fssai": number(vid, "FSSAI"), "extras": "4 sachets of 15 g. Best before: 12 months.",
                    }
                ),
            }
        )
    return out


# ---------------------------------------------------------------- writing


def write_doc(vid: str, spec: dict, folder: Path) -> dict:
    canvas: Canvas = spec["canvas"]()
    seed = f"{vid}:{spec['file']}"
    if spec["format"] == "pdf":
        img, fields, panel = scan_flat(canvas)
        page_file = spec["pages"][0]
        img.save(folder / page_file, format="PNG", optimize=True)
        img.save(folder / spec["file"], format="PDF", resolution=100.0, title=spec["title"], producer="CategoryOS sample generator",
                 creationDate=FIXED_TIME, modDate=FIXED_TIME)
        pages = [page_file]
    else:
        img, fields, panel = scan(canvas, spec["angle"], seed)
        img.save(folder / spec["file"], format="JPEG", quality=74, optimize=True)
        pages = [spec["file"]]
    manifest = {k: spec[k] for k in ("file", "kind", "title") if k in spec}
    manifest["pages"] = pages
    for k in ("declares", "sku_code"):
        if spec.get(k):
            manifest[k] = spec[k]
    truth = {"file": spec["file"], "kind": spec["kind"], "pages": [{"file": pages[0], "width": img.width, "height": img.height, "fields": fields, "panel": panel}]}
    return {"manifest": manifest, "truth": truth}


def scan_flat(c: Canvas):
    """A digital export: no rotation, no grain. Boxes are just normalised."""
    fields = [{**f, "bbox": [round(f["px"][0] / c.w, 4), round(f["px"][1] / c.h, 4), round(f["px"][2] / c.w, 4), round(f["px"][3] / c.h, 4)]} for f in c.fields]
    return c.img, fields, None


def fixture(model_content: dict) -> dict:
    return {"schema_version": 1, "parser_version": "1.0", "model": "muse-spark-1.3", "input_tokens": 0, "output_tokens": 0, "content": model_content}


def write_fixtures(vid: str, truth: dict, policy: dict) -> None:
    docs = policy["documents"]
    kinds = {k["kind"]: k for k in docs["kinds"]}
    cfg = kinds[truth["kind"]]
    stage = cfg["stage"]
    critical = {f["name"] for f in docs["fields"] if f["kind"] == truth["kind"] and f["critical"]}
    for page in truth["pages"]:
        task = f"docs_{vid}_{re.sub(r'[^A-Za-z0-9]+', '_', Path(page['file']).stem).strip('_')}"
        out = FIXTURES / stage
        out.mkdir(parents=True, exist_ok=True)
        fields = [{"name": f["name"], "value": f["value"], "bbox": f["bbox"], "confidence": 0.97, "sku_code": f["sku_code"]} for f in page["fields"]]
        (out / f"{task}.json").write_text(json.dumps(fixture({"kind": truth["kind"], "legible": True, "fields": fields, "notes": ""}), indent=2) + "\n")
        panel = page["panel"] if cfg["panel"] else None
        if panel:
            (out / f"{task}_panel.json").write_text(json.dumps({"bbox": panel}, indent=2) + "\n")

            def inside(b):
                cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                return panel[0] <= cx <= panel[2] and panel[1] <= cy <= panel[3]

            inside_fields = [f for f in page["fields"] if inside(f["bbox"])]
            reads = [{"name": f["name"], "value": f["value"], "sku_code": f["sku_code"]} for f in inside_fields]
            (out / f"{task}_reread.json").write_text(json.dumps(fixture({"reads": reads}), indent=2) + "\n")
            todo = [f for f in page["fields"] if f["name"] in critical and not inside(f["bbox"])]
            if todo:
                reads = [{"name": f["name"], "value": f["value"], "sku_code": f["sku_code"]} for f in todo]
                (out / f"{task}_reread_fields.json").write_text(json.dumps(fixture({"reads": reads}), indent=2) + "\n")
        else:
            todo = [f for f in page["fields"] if f["name"] in critical]
            reads = [{"name": f["name"], "value": f["value"], "sku_code": f["sku_code"]} for f in todo]
            (out / f"{task}_reread.json").write_text(json.dumps(fixture({"reads": reads}), indent=2) + "\n")


def main() -> int:
    policy = yaml.safe_load(POLICY.read_text())
    for vid in ("V001", "V002", "V003", "V004"):
        folder = VENDORS / vid / "docs"
        folder.mkdir(parents=True, exist_ok=True)
        entries, truths = [], []
        for spec in specs(vid):
            res = write_doc(vid, spec, folder)
            entries.append(res["manifest"])
            truths.append(res["truth"])
            write_fixtures(vid, res["truth"], policy)
        (folder / "manifest.json").write_text(json.dumps({"documents": entries}, indent=2, ensure_ascii=False) + "\n")
        (folder / "truth.json").write_text(json.dumps({"note": "What is really printed on each page. For tests and fixtures only; the pipeline never reads this file.", "documents": truths}, indent=2) + "\n")
        print(f"{vid}: {len(entries)} document(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
