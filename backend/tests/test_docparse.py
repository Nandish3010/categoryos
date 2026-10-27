from datetime import date

import pytest
from PIL import Image

from app import docparse


@pytest.mark.parametrize(
    "text,expected",
    [
        ("30 NOV 2026", date(2026, 11, 30)),
        ("30th November 2026", date(2026, 11, 30)),
        ("Nov 30, 2026", date(2026, 11, 30)),
        ("30/11/2026", date(2026, 11, 30)),  # day first, as printed in India
        ("30-11-2026", date(2026, 11, 30)),
        ("2026-11-30", date(2026, 11, 30)),
        ("valid until: 15 aug 2027.", date(2027, 8, 15)),
    ],
)
def test_parse_date_formats(text, expected):
    assert docparse.parse_date(text) == expected


@pytest.mark.parametrize("text", ["", None, "no date here", "31 FOO 2026", "32/13/2026"])
def test_parse_date_rejects_garbage(text):
    assert docparse.parse_date(text) is None


def test_parse_value_by_type():
    assert docparse.parse_value("pct", "30.0 %") == pytest.approx(0.30)
    assert docparse.parse_value("pct", "32") == pytest.approx(0.32)  # a bare number on a label is read as percent
    assert docparse.parse_value("inr", "Rs. 1,499") == 1499.0
    assert docparse.parse_value("inr", "₹956.50") == 956.5
    assert docparse.parse_value("qty", "1.5 kg") == 1500.0
    assert docparse.parse_value("qty", "60 g") == 60.0
    assert docparse.parse_value("number", "SPF 50") == 50.0
    assert docparse.parse_value("text", "FSSAI-DEMO-0002") == docparse.parse_value("text", "fssai demo 0002")
    assert docparse.parse_value("pct", "abc") is None and docparse.parse_value("inr", "") is None


def test_claim_number_is_days_for_dates():
    d = date(2026, 11, 30)
    assert docparse.claim_number("date", d, date(2026, 10, 27)) == 34.0
    assert docparse.claim_number("date", d, date(2026, 12, 1)) == -1.0
    assert docparse.claim_number("pct", 0.3, None) == 0.3
    assert docparse.claim_number("date", d, None) is None


def test_bbox_validation_and_clamping():
    assert docparse.valid_bbox([0.1, 0.1, 0.5, 0.2])
    for bad in ([0.5, 0.1, 0.1, 0.2], [0.1, 0.1, 1.2, 0.2], [0.1, 0.1, 0.2], None, [0.1, 0.2, 0.3, 0.2]):
        assert not docparse.valid_bbox(bad)
    assert docparse.clamp_bbox([0.9, 1.4, -0.2, 0.1]) == [0.0, 0.1, 0.9, 1.0]


def _page() -> bytes:
    img = Image.new("RGB", (100, 200), (255, 255, 255))
    for x in range(20, 40):
        for y in range(50, 80):
            img.putpixel((x, y), (0, 0, 0))
    return docparse.crop_png(img)


def test_crop_digest_binds_the_pixels_not_the_encoder():
    page = _page()
    box = [0.2, 0.25, 0.4, 0.4]
    digest = docparse.region_digest(page, box)
    img = docparse.open_image(page)
    assert digest == docparse.crop_digest(docparse.crop(img, box)) and len(digest) == 64
    assert docparse.region_digest(page, [0.5, 0.25, 0.7, 0.4]) != digest  # a different region
    img.putpixel((25, 60), (255, 0, 0))
    assert docparse.region_digest(docparse.crop_png(img), box) != digest  # one changed pixel


def test_crop_padding_grows_the_crop_inside_the_page():
    img = docparse.open_image(_page())
    plain = docparse.crop(img, [0.2, 0.25, 0.4, 0.4])
    padded = docparse.crop(img, [0.2, 0.25, 0.4, 0.4], 0.05)
    assert padded.size[0] > plain.size[0] and padded.size[1] > plain.size[1]
    assert docparse.crop(img, [0.0, 0.0, 1.0, 1.0], 0.5).size == img.size
