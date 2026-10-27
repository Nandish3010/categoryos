#!/usr/bin/env python3
"""Synthetic LIVE CATALOG for CategoryOS "Run: Catalog fixes" (existing vendors E001-E006). All data FICTIONAL, INR.

Usage: python3 data/generate_catalog_live.py   (seed 42, byte-identical on re-run; stdlib only for the CSV/JSON)
Writes, under data/synthetic/ops/:
  catalog_live.csv        the marketplace listings as they are today (title, bullets, attributes, images as flags, FSSAI no.)
  vendor_price_list.csv   the vendors' price lists: an old list, the LATEST list (what counts) and one future-dated row
  catalog_licences.json   FSSAI licence records per food vendor (valid_until, so an expired one can be spotted)
  catalog_labels/         three pack-label photos + manifest.json (needs Pillow and PyYAML: reuses data/generate_docs.py's
                          label drawing; skipped with a message when they are not installed) and the mock vision fixtures
                          backend/fixtures/mock/ops/docs_E00x_label_*.json that mirror what the vision models return.
Separate from generate.py / generate_ops.py / generate_docs.py on purpose (they are edited on other branches; this one only
READS ops/skus.csv and imports the label canvas from generate_docs).

PLANTED issues (the module's test bench; ids are listing ids):
  title over the limit             L-BK-01 (keyword-stuffed 140-char title)
  title missing brand / size       L-TW-01
  missing required attribute       L-BK-04 (life_stage, breed_size, grain_free), L-TW-03 (material)
  banned / unproven claims         L-BK-01 (boosts immunity, supports joint health, BEST), L-PL-04 (cures, No.1, vet formulated),
                                   L-GW-02 (ultimate, unmatched), L-GW-05 (treats ear infections, heals)
  MRP differs from latest list     L-BK-02 (old list price), L-LT-04 (also differs from the label)
  pack size mismatch               L-BK-03 (2 kg vs 1 kg), L-LT-02 (5 kg vs 10 kg)
  near-duplicate listings          L-BK-06-B (of L-BK-06), L-TW-06-B (of L-TW-06)
  wrong category / subcategory     L-PL-03 (cat food filed under dog dry food), L-LT-03 (tofu litter filed as clumping)
  missing / low-resolution image   L-PL-05 (no image), L-PL-06 (400 px), L-TW-04 (640 px)
  high returns "not as described"  come from the existing ops/returns.csv (L-PL-01, L-LT-03, L-NP-05, ...), not planted here
  expired FSSAI                    L-PL-01, L-PL-02 (renewed licence is on file: fix = swap the number),
                                   all six E003 listings (nothing valid on file: fix = hold the listing)
  label vs listing                 L-BK-01 (label prints 26% protein, listing says 28%), L-PL-01 (34% vs 36%), L-LT-04 (MRP)"""

import csv
import json
import os
import random
import sys
from datetime import date

SEED = 42
HERE = os.path.dirname(os.path.abspath(__file__))
OPS = os.path.join(HERE, "synthetic", "ops")
LABELS = os.path.join(OPS, "catalog_labels")
FIXTURES = os.path.join(os.path.dirname(HERE), "backend", "fixtures", "mock", "ops")
AS_OF = date(2026, 10, 26)

BRANDS = {"E001": "Barkley & Co", "E002": "Purrline Foods", "E003": "NutriPaws", "E004": "Tailwind Play", "E005": "Litterly", "E006": "Groomwell"}

# sku -> (title, category, subcategory, pack_size, attributes, bullets, description)
A = dict  # attribute dicts
L = {
    "BK-01": ("Barkley & Co Chicken & Rice Adult Dry Dog Food 3 kg", "dog dry food", "adult", "3 kg",
              A(life_stage="adult", breed_size="all breeds", protein="28%", grain_free="no", pack_g=3000),
              ["Real chicken and rice recipe for adult dogs", "28% protein for daily energy", "Suitable for all breeds"],
              "Complete dry food for adult dogs of all breeds, made with chicken and rice. Not grain free; 28% protein."),
    "BK-02": ("Barkley & Co Lamb & Rice Adult Dry Dog Food 3 kg", "dog dry food", "adult", "3 kg",
              A(life_stage="adult", breed_size="all breeds", protein="24%", grain_free="no", pack_g=3000),
              ["Lamb and rice recipe for adult dogs", "24% protein", "Suitable for all breeds"],
              "Complete dry food for adult dogs of all breeds, made with lamb and rice. Not grain free; 24% protein."),
    "BK-03": ("Barkley & Co Puppy Starter Dry Dog Food 1 kg", "dog dry food", "adult", "1 kg",
              A(life_stage="puppy", breed_size="all breeds", protein="30%", grain_free="no", pack_g=1000),
              ["Starter nutrition for puppies", "30% protein for growth", "Small kibble for small mouths"],
              "Complete dry food for puppies of all breeds from weaning. Not grain free; 30% protein."),
    "BK-04": ("Barkley & Co Senior Care Dry Dog Food 3 kg", "dog dry food", "senior", "3 kg",
              A(life_stage="senior", breed_size="all breeds", protein="22%", grain_free="no", pack_g=3000),
              ["Gentle recipe for senior dogs", "22% protein", "Rice-based and easy to chew"],
              "Complete dry food for senior dogs of all breeds, made with rice and chicken meal. Not grain free; 22% protein."),
    "BK-05": ("Barkley & Co Chicken Gravy Wet Dog Food Pouch 100 g", "dog wet food", "gravy", "100 g",
              A(life_stage="adult", protein="9%", pack_g=100),
              ["Chicken chunks in gravy", "9% protein", "Easy-tear 100 g pouch"],
              "Wet food for adult dogs with chicken chunks in gravy. Contains 9% protein."),
    "BK-06": ("Barkley & Co Beef Pate Wet Dog Food Can 350 g", "dog wet food", "pate", "350 g",
              A(life_stage="adult", protein="8%", pack_g=350),
              ["Smooth beef pate", "8% protein", "350 g can with a pull ring"],
              "Wet food for adult dogs, a smooth beef pate. Contains 8% protein."),
    "PL-01": ("Purrline Foods Ocean Fish Adult Dry Cat Food 1.2 kg", "cat dry food", "adult", "1.2 kg",
              A(life_stage="adult", breed_size="all breeds", protein="36%", grain_free="no", pack_g=1200),
              ["Ocean fish recipe for adult cats", "36% protein", "Fish oil for a glossy coat"],
              "Complete dry food for adult cats, made with ocean fish. Not grain free; 36% protein."),
    "PL-02": ("Purrline Foods Chicken & Tuna Adult Dry Cat Food 1.2 kg", "cat dry food", "adult", "1.2 kg",
              A(life_stage="adult", breed_size="all breeds", protein="34%", grain_free="no", pack_g=1200),
              ["Chicken and tuna recipe for adult cats", "34% protein", "Added taurine"],
              "Complete dry food for adult cats, made with chicken and tuna. Not grain free; 34% protein."),
    "PL-03": ("Purrline Foods Kitten Starter Dry Cat Food 400 g", "cat dry food", "kitten", "400 g",
              A(life_stage="kitten", breed_size="all breeds", protein="38%", grain_free="no", pack_g=400),
              ["Starter nutrition for kittens", "38% protein", "Small kibble"],
              "Complete dry food for kittens from weaning. Not grain free; 38% protein."),
    "PL-04": ("Purrline Foods Indoor Hairball Care Dry Cat Food 1.2 kg", "cat dry food", "adult", "1.2 kg",
              A(life_stage="adult", breed_size="all breeds", protein="32%", grain_free="no", pack_g=1200),
              ["Indoor recipe for adult cats", "32% protein", "Added fibre"],
              "Complete dry food for indoor adult cats with added fibre. Not grain free; 32% protein."),
    "PL-05": ("Purrline Foods Tuna in Gravy Wet Cat Food Pouch 70 g", "cat wet food", "gravy", "70 g",
              A(life_stage="adult", protein="10%", pack_g=70),
              ["Tuna flakes in gravy", "10% protein", "70 g pouch"],
              "Wet food for adult cats with tuna flakes in gravy. Contains 10% protein."),
    "PL-06": ("Purrline Foods Mackerel Mousse Wet Cat Food Can 85 g", "cat wet food", "mousse", "85 g",
              A(life_stage="adult", protein="9%", pack_g=85),
              ["Smooth mackerel mousse", "9% protein", "85 g can"],
              "Wet food for adult cats, a smooth mackerel mousse. Contains 9% protein."),
    "NP-01": ("NutriPaws Chicken Strips Dog Treats 150 g", "treats", "dog treats", "150 g",
              A(life_stage="adult", protein="30%", pack_g=150),
              ["Soft chicken strips", "30% protein", "No artificial colours"],
              "Soft chicken strip treats for adult dogs. Contains 30% protein."),
    "NP-02": ("NutriPaws Dental Chew Sticks for Dogs 150 g", "treats", "dental", "150 g",
              A(life_stage="adult", protein="12%", pack_g=150),
              ["Long-lasting chew sticks", "12% protein", "Ridged texture"],
              "Chew sticks for adult dogs with a ridged texture. Contains 12% protein."),
    "NP-03": ("NutriPaws Peanut Butter Biscuits Dog Treats 400 g", "treats", "dog treats", "400 g",
              A(life_stage="adult", protein="14%", pack_g=400),
              ["Crunchy peanut butter biscuits", "14% protein", "Resealable 400 g pack"],
              "Crunchy peanut butter biscuits for adult dogs. Contains 14% protein."),
    "NP-04": ("NutriPaws Training Bites Dog Treats 60 g", "treats", "dog treats", "60 g",
              A(life_stage="adult", protein="25%", pack_g=60),
              ["Small bites for training", "25% protein", "60 g pouch"],
              "Small soft treats for training adult dogs. Contains 25% protein."),
    "NP-05": ("NutriPaws Tuna Cat Treats 60 g", "treats", "cat treats", "60 g",
              A(life_stage="adult", protein="40%", pack_g=60),
              ["Crunchy tuna treats", "40% protein", "60 g pouch"],
              "Crunchy tuna treats for adult cats. Contains 40% protein."),
    "NP-06": ("NutriPaws Creamy Lick Cat Treat 4 pack", "treats", "cat treats", "4 pack",
              A(life_stage="adult", protein="8%", pack_pc=4),
              ["Lickable cat treat", "8% protein", "Pack of 4 sachets"],
              "Lickable creamy treat for adult cats in a pack of 4. Contains 8% protein."),
    "TW-01": ("Tailwind Play Rope Tug Toy for Dogs Large", "toys", "dog toys", "Large",
              A(material="cotton rope", pack_pc=1),
              ["Braided cotton rope", "Large size for big dogs", "Good for tug games"],
              "A braided cotton rope tug toy for large dogs."),
    "TW-02": ("Tailwind Play Squeaky Plush Duck Dog Toy", "toys", "dog toys", "1 pc",
              A(material="plush", pack_pc=1),
              ["Soft plush duck", "Squeaker inside", "Stitched seams"],
              "A soft plush duck with a squeaker for dogs."),
    "TW-03": ("Tailwind Play Feather Wand Teaser Cat Toy", "toys", "cat toys", "1 pc",
              A(material="feather and plastic", pack_pc=1),
              ["Feather teaser on a flexible wand", "Encourages active play", "1 wand"],
              "A feather teaser wand made of feather and plastic for cats."),
    "TW-04": ("Tailwind Play Adjustable Dog Harness Medium", "accessories", "harness", "Medium",
              A(material="nylon", pack_pc=1),
              ["Adjustable chest and neck straps", "Padded mesh", "Medium size"],
              "An adjustable nylon harness with padded mesh for medium dogs."),
    "TW-05": ("Tailwind Play Printed Dog Collar Bandana Set of 2", "accessories", "collars", "Set of 2",
              A(material="cotton", pack_pc=2),
              ["Printed cotton bandanas", "Set of 2", "Machine washable"],
              "A set of 2 printed cotton bandanas for dogs."),
    "TW-06": ("Tailwind Play Collapsible Travel Bowl for Dogs", "accessories", "bowls", "1 pc",
              A(material="silicone", pack_pc=1),
              ["Folds flat for travel", "Food-grade silicone", "Carabiner clip"],
              "A collapsible silicone travel bowl for dogs."),
    "LT-01": ("Litterly Clumping Bentonite Cat Litter Unscented 10 kg", "cat litter", "clumping", "10 kg",
              A(material="bentonite", pack_g=10000),
              ["Fast clumping bentonite", "Unscented", "10 kg bag"],
              "Unscented clumping cat litter made of bentonite."),
    "LT-02": ("Litterly Clumping Bentonite Cat Litter Lavender 10 kg", "cat litter", "clumping", "10 kg",
              A(material="bentonite", pack_g=10000),
              ["Fast clumping bentonite", "Lavender scent", "10 kg bag"],
              "Lavender scented clumping cat litter made of bentonite."),
    "LT-03": ("Litterly Tofu Cat Litter Original 6 L", "cat litter", "tofu", "6 L",
              A(material="tofu", pack_ml=6000),
              ["Plant-based tofu litter", "Flushable in small amounts", "6 L bag"],
              "Original tofu cat litter, plant-based and low dust."),
    "LT-04": ("Litterly Activated Carbon Clumping Cat Litter 5 kg", "cat litter", "clumping", "5 kg",
              A(material="bentonite and activated carbon", pack_g=5000),
              ["Activated carbon for odour control", "Clumps fast", "5 kg bag"],
              "Clumping cat litter with activated carbon for odour control."),
    "LT-05": ("Litterly Clumping Bentonite Cat Litter 5 kg", "cat litter", "clumping", "5 kg",
              A(material="bentonite", pack_g=5000),
              ["Fast clumping bentonite", "Low dust", "5 kg bag"],
              "Clumping cat litter made of bentonite."),
    "LT-06": ("Litterly Metal Litter Scoop", "cat litter", "clumping", "1 pc",
              A(material="stainless steel", pack_pc=1),
              ["Stainless steel scoop", "Wide slots", "Easy to clean"],
              "A stainless steel litter scoop with wide slots."),
    "GW-01": ("Groomwell Oatmeal Pet Shampoo 250 ml", "grooming", "shampoo", "250 ml",
              A(pack_ml=250),
              ["Oatmeal for soft coats", "Soap-free formula", "250 ml bottle"],
              "A gentle oatmeal shampoo for dogs and cats."),
    "GW-02": ("Groomwell Deshedding Brush for Pets", "grooming", "tools", "1 pc",
              A(pack_pc=1),
              ["Removes loose undercoat", "Comfort grip handle", "Self-cleaning button"],
              "A deshedding brush with a comfort grip for dogs and cats."),
    "GW-03": ("Groomwell Paw Balm for Dogs 50 g", "grooming", "hygiene", "50 g",
              A(pack_g=50),
              ["Soothing balm for paw pads", "Natural wax base", "50 g tin"],
              "A paw balm with a natural wax base for dogs."),
    "GW-04": ("Groomwell Pet Nail Clipper", "grooming", "tools", "1 pc",
              A(pack_pc=1),
              ["Stainless steel blades", "Non-slip handle", "Safety guard"],
              "A stainless steel nail clipper with a safety guard for pets."),
    "GW-05": ("Groomwell Pet Ear Cleaner 100 ml", "grooming", "hygiene", "100 ml",
              A(pack_ml=100),
              ["Gentle ear cleaning solution", "Alcohol free", "100 ml bottle"],
              "A gentle, alcohol free ear cleaner for dogs and cats."),
    "GW-06": ("Groomwell Tick & Flea Grooming Comb for Pets", "grooming", "tools", "1 pc",
              A(pack_pc=1),
              ["Fine teeth catch fleas", "Comfort handle", "Rust-free pins"],
              "A fine toothed comb for removing fleas and ticks from pets."),
}

FSSAI = {"E001": "FSSAI-E001-2028", "E002": "FSSAI-E002-NEW", "E003": "FSSAI-E003-OLD"}
FSSAI_OLD = {"E002": "FSSAI-E002-OLD"}
FOOD = {"dog dry food", "dog wet food", "cat dry food", "cat wet food", "treats"}

LICENCES = [
    {"vendor_id": "E001", "type": "FSSAI", "number": "FSSAI-E001-2028", "valid_from": "2023-04-01", "valid_until": "2028-03-31"},
    {"vendor_id": "E002", "type": "FSSAI", "number": "FSSAI-E002-OLD", "valid_from": "2021-10-01", "valid_until": "2026-09-30"},
    {"vendor_id": "E002", "type": "FSSAI", "number": "FSSAI-E002-NEW", "valid_from": "2026-10-01", "valid_until": "2028-03-31"},
    # PLANTED: E003's licence ran out on 31 Aug and nothing newer is on file
    {"vendor_id": "E003", "type": "FSSAI", "number": "FSSAI-E003-OLD", "valid_from": "2021-09-01", "valid_until": "2026-08-31"},
]

COLUMNS = ["listing_id", "vendor_id", "sku_code", "title", "bullets", "description", "category", "subcategory", "mrp", "pack_size",
           "attributes", "image_count", "image_width", "image_height", "fssai_number", "gmv_share", "status", "listed_on"]


def read_skus() -> list[dict]:
    with open(os.path.join(OPS, "skus.csv"), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build() -> tuple[list[dict], list[dict]]:
    rng = random.Random(SEED)
    skus = read_skus()
    rows: list[dict] = []
    for s in skus:
        code, vid = s["sku_code"], s["vendor_id"]
        title, cat, sub, pack, attrs, bullets, desc = L[code]
        number = ""
        if cat in FOOD:
            number = FSSAI[vid]
        rows.append({
            "listing_id": f"L-{code}", "vendor_id": vid, "sku_code": code, "title": title, "bullets": list(bullets), "description": desc,
            "category": cat, "subcategory": sub, "mrp": int(float(s["mrp"])), "pack_size": pack, "attributes": dict(attrs),
            "image_count": rng.choice((4, 5, 6, 7)), "image_width": rng.choice((1200, 1500, 1600, 2000)), "image_height": 0,
            "fssai_number": number, "gmv_share": 1.0, "status": "active",
            "listed_on": date.fromordinal(date(2025, 11, 1).toordinal() + rng.randrange(0, 300)).isoformat(),
        })
    for r in rows:
        r["image_height"] = r["image_width"]
    by = {r["listing_id"]: r for r in rows}

    def edit(code: str, **kw) -> None:
        by[f"L-{code}"].update(kw)

    # --- planted issues ---
    edit("BK-01", title="Barkley & Co BEST Chicken & Rice Adult Dry Dog Food 3 kg - Premium High Protein Complete Nutrition for All Dog Breeds, Healthy Coat, Strong Bones, Great Taste",
         bullets=["Real chicken and rice recipe for adult dogs", "Boosts immunity and supports joint health", "28% protein for daily energy"])
    edit("BK-02", mrp=1050)  # old price list value; the latest list says 1100
    edit("BK-03", title="Barkley & Co Puppy Starter Dry Dog Food 2 kg", pack_size="2 kg")
    by["L-BK-03"]["attributes"]["pack_g"] = 2000
    for k in ("life_stage", "breed_size", "grain_free"):
        del by["L-BK-04"]["attributes"][k]
    by["L-BK-06"]["gmv_share"] = 0.85
    dup = dict(by["L-BK-06"], listing_id="L-BK-06-B", title="Barkley & Co Beef Pate Wet Dog Food Tin 350 gm", gmv_share=0.15,
               bullets=["Smooth beef pate", "8% protein", "350 gm tin"], image_count=2, image_width=1000, image_height=1000, listed_on="2026-09-12")
    dup["attributes"] = dict(by["L-BK-06"]["attributes"])
    edit("PL-01", fssai_number=FSSAI_OLD["E002"])
    edit("PL-02", fssai_number=FSSAI_OLD["E002"])
    edit("PL-03", category="dog dry food", subcategory="adult")
    edit("PL-04", bullets=["Cures hairballs naturally", "No.1 vet formulated hairball relief", "32% protein"])
    edit("PL-05", image_count=0, image_width=0, image_height=0)
    edit("PL-06", image_width=400, image_height=400)
    edit("LT-02", pack_size="5 kg")
    by["L-LT-02"]["attributes"]["pack_g"] = 5000
    edit("LT-03", subcategory="clumping")
    edit("LT-04", mrp=429)
    edit("TW-01", title="Rope Tug Toy")
    del by["L-TW-03"]["attributes"]["material"]
    edit("TW-04", image_width=640, image_height=640)
    by["L-TW-06"]["gmv_share"] = 0.85
    dup2 = dict(by["L-TW-06"], listing_id="L-TW-06-B", title="Tailwind Play Foldable Travel Bowl for Dogs", gmv_share=0.15,
                bullets=["Folds flat for travel", "Food-grade silicone", "Carabiner clip"], image_count=2, image_width=1000, image_height=1000, listed_on="2026-09-20")
    dup2["attributes"] = dict(by["L-TW-06"]["attributes"])
    edit("GW-02", title="Groomwell Deshedding Brush for Pets", bullets=["The ultimate deshedding brush", "Unmatched results on every coat", "Comfort grip handle"])
    edit("GW-05", bullets=["Treats ear infections and heals irritation", "Alcohol free", "100 ml bottle"])
    out = [by[f"L-{s['sku_code']}"] for s in skus] + [dup, dup2]
    return out, skus


def write_csv(path: str, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def price_lists(skus: list[dict]) -> list[list]:
    rows = []
    old = {"BK-02": 1050, "BK-01": 1000, "NP-03": 479, "LT-01": 679}
    for s in skus:
        code, vid, mrp = s["sku_code"], s["vendor_id"], int(float(s["mrp"]))
        pack = L[code][3]
        rows.append([vid, code, "2026-05-01", old.get(code, mrp), pack])
        rows.append([vid, code, "2026-09-15", mrp, pack])
    rows.append(["E006", "GW-04", "2026-11-15", 219, L["GW-04"][3]])  # future-dated: not yet in force, must be ignored
    return rows


# ---------------------------------------------------------------- labels (optional: Pillow + PyYAML)

LABEL_SPECS = [
    # sku, protein printed, claims, net, mrp, analysis rows
    ("BK-01", "26.0 %", "Grain inclusive. Boosts immunity.", "3 kg", "Rs. 1,050", "FSSAI-E001-2028"),
    ("PL-01", "34.0 %", "Rich in ocean fish.", "1.2 kg", "Rs. 640", "FSSAI-E002-OLD"),
    ("LT-04", None, "Odour control.", "5 kg", "Rs. 449", "NA - not a food"),
]


def write_labels(skus: list[dict]) -> bool:
    try:
        sys.path.insert(0, HERE)
        import generate_docs as gd  # noqa: PLC0415  (needs Pillow and PyYAML)
    except ImportError as exc:
        print(f"labels skipped: {exc}", file=sys.stderr)
        return False
    os.makedirs(LABELS, exist_ok=True)
    os.makedirs(FIXTURES, exist_ok=True)
    by = {s["sku_code"]: s for s in skus}
    entries = []
    for code, protein, claims, net, mrp, fssai in LABEL_SPECS:
        vid = by[code]["vendor_id"]
        title = L[code][0]
        analysis = [("Crude Fat (min)", "12.0 %"), ("Crude Fibre (max)", "4.0 %"), ("Moisture (max)", "10.0 %"), ("Ash (max)", "8.0 %")]
        if protein:
            analysis.insert(0, ("Crude Protein (min)", protein))
        canvas = gd.label({
            "brand": BRANDS[vid], "sku": code, "product": title.replace(BRANDS[vid] + " ", ""), "analysis": analysis,
            "ingredients": "Main ingredient, cereals or minerals, vitamins and oils.", "claims": claims, "net": net, "mrp": mrp,
            "fssai": fssai, "extras": "Best before: 12 months from packing.",
        })
        file = f"label_{code}.jpg"
        img, fields, panel = gd.scan(canvas, 0.9 if code != "PL-01" else -1.2, f"{vid}:{file}")
        img.save(os.path.join(LABELS, file), format="JPEG", quality=74, optimize=True)
        entries.append({"file": file, "kind": "product_label", "title": f"Pack label {code} (photo)", "pages": [file], "sku_code": code, "vendor_id": vid})
        task = f"docs_{vid}_label_{code.replace('-', '_')}"
        flds = [{"name": f["name"], "value": f["value"], "bbox": f["bbox"], "confidence": 0.97, "sku_code": f["sku_code"]} for f in fields]
        fx = lambda content: {"schema_version": 1, "parser_version": "1.0", "model": "muse-spark-1.3", "input_tokens": 0, "output_tokens": 0, "content": content}  # noqa: E731
        dump = lambda name, obj: open(os.path.join(FIXTURES, name), "w").write(json.dumps(obj, indent=2) + "\n")  # noqa: E731
        dump(f"{task}.json", fx({"kind": "product_label", "legible": True, "fields": flds, "notes": ""}))
        dump(f"{task}_panel.json", {"bbox": panel})

        def inside(b, p=panel):
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            return p[0] <= cx <= p[2] and p[1] <= cy <= p[3]

        dump(f"{task}_reread.json", fx({"reads": [{"name": f["name"], "value": f["value"], "sku_code": f["sku_code"]} for f in fields if inside(f["bbox"])]}))
    with open(os.path.join(LABELS, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"documents": entries}, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return True


def main() -> None:
    listings, skus = build()
    write_csv(
        os.path.join(OPS, "catalog_live.csv"), COLUMNS,
        [[r["listing_id"], r["vendor_id"], r["sku_code"], r["title"], " || ".join(r["bullets"]), r["description"], r["category"], r["subcategory"],
          r["mrp"], r["pack_size"], json.dumps(r["attributes"], sort_keys=True), r["image_count"], r["image_width"], r["image_height"],
          r["fssai_number"], r["gmv_share"], r["status"], r["listed_on"]] for r in listings],
    )
    write_csv(os.path.join(OPS, "vendor_price_list.csv"), ["vendor_id", "sku_code", "effective_date", "mrp", "pack_size"], price_lists(skus))
    with open(os.path.join(OPS, "catalog_licences.json"), "w", encoding="utf-8") as f:
        json.dump({"note": "Synthetic. Generated by data/generate_catalog_live.py (seed 42).", "licences": LICENCES}, f, indent=2)
        f.write("\n")
    labels = write_labels(skus)
    print(f"{len(listings)} listings, {len(price_lists(skus))} price-list rows, {len(LICENCES)} licences, labels: {'written' if labels else 'skipped'}")


if __name__ == "__main__":
    main()
