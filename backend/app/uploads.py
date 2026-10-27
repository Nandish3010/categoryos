"""Validation and parsing of everything a visitor uploads at /try. Pure functions over bytes: no disk, no network, no
model. Nothing here trusts a file name, a content type or an extension; the content is sniffed.

* Sheets: CSV (UTF-8) or XLSX. Size, row, column and cell limits come from config (ops limits). XLSX is a zip, so it is
  inspected before it is opened (entry count, uncompressed size, no macros, no path tricks) and read with openpyxl's
  read-only, values-only mode with defusedxml installed.
* Applications: JSON (size capped) or a form, validated into a fixed shape; unknown keys are dropped.
* Documents: PNG or JPEG (decoded with Pillow, pixel-capped) or PDF (stored, not rendered).
* Output: ``csv_safe`` neutralises spreadsheet formulas for anything we hand back as CSV."""

import csv
import io
import json
import re
import zipfile
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.config import settings
from app.errors import CategoryOSError
from app.parsing import map_columns

MAX_PIXELS = 40_000_000
MAX_XLSX_UNCOMPRESSED = 25 * 1024 * 1024
MAX_XLSX_ENTRIES = 300
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_WS = re.compile(r"[\t\r\n]+")
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._#/\-]{0,39}$")
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
SHEET_FIELDS_NEEDED = ("code", "name", "mrp")


class UploadError(CategoryOSError):
    status = 422
    code = "upload_invalid"
    problem = "The upload was not accepted"
    cause = "A file failed validation"
    fix = "Check the file against the limits shown on the page"


class UploadTooLarge(UploadError):
    status = 413
    code = "upload_too_large"


class UploadWrongType(UploadError):
    status = 415
    code = "upload_wrong_type"


# ---------- sniffing ----------


def sniff(data: bytes) -> Literal["png", "jpeg", "pdf", "zip", "text", "unknown"]:
    """What the bytes are, whatever the file was called."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        return "zip"
    head = data[:4096]
    if b"\x00" in head:
        return "unknown"
    try:
        head.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        if exc.start < len(head) - 4:  # a multibyte character cut by the 4 KB slice is fine
            return "unknown"
    return "text"


def clean(text: Any) -> str:
    """Control characters out, line breaks and tabs flattened to one space, edges trimmed."""
    return _WS.sub(" ", _CTRL.sub("", str(text if text is not None else ""))).strip()


def csv_safe(value: Any) -> str:
    """A cell for CSV we hand back to a person: anything a spreadsheet would run as a formula gets a leading apostrophe."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


# ---------- sheets ----------


class Sheet(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    columns: dict[str, str]
    warnings: list[str] = Field(default_factory=list)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime | date):
        return value.isoformat()
    return clean(value)


def _read_csv(data: bytes) -> list[list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UploadWrongType(
            "The sheet is not UTF-8 text",
            cause=f"Byte {exc.start} is not valid UTF-8",
            fix="Save the sheet as CSV UTF-8 (or upload the .xlsx)",
        ) from exc
    first = text.split("\n", 1)[0]
    delimiter = max(",;\t|", key=lambda d: first.count(d))
    out: list[list[str]] = []
    try:
        for record in csv.reader(io.StringIO(text), delimiter=delimiter):
            out.append([_cell(c) for c in record])
            if len(out) > settings.upload_max_rows + 1 + 50:  # stop early; blank lines may sit between rows
                break
    except csv.Error as exc:
        raise UploadError("The CSV could not be parsed", cause=str(exc), fix="Check quotes and delimiters, or upload the .xlsx") from exc
    return out


def _read_xlsx(data: bytes) -> list[list[str]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UploadWrongType("The file is not a valid spreadsheet", cause="It is not a readable zip/xlsx", fix="Upload a .csv or .xlsx") from exc
    infos = zf.infolist()
    names = [i.filename for i in infos]
    if len(infos) > MAX_XLSX_ENTRIES or sum(i.file_size for i in infos) > MAX_XLSX_UNCOMPRESSED:
        raise UploadTooLarge("The spreadsheet expands to too much data", cause="Zip entry count or uncompressed size is over the limit", fix="Export just the SKU rows to a new file")
    if any(n.startswith("/") or ".." in n.split("/") or "\\" in n for n in names):
        raise UploadError("The spreadsheet contains unsafe paths", cause="A zip entry points outside the archive", fix="Re-export the sheet from Excel or Sheets")
    if "xl/workbook.xml" not in names or "[Content_Types].xml" not in names:
        raise UploadWrongType("The zip is not an Excel workbook", cause="xl/workbook.xml is missing", fix="Upload a .csv or .xlsx")
    if any("vbaProject" in n or n.startswith(("xl/externalLinks", "xl/embeddings")) for n in names):
        raise UploadError("The workbook has macros, embedded objects or external links", cause="These are not read", fix="Save a plain .xlsx or a .csv with values only")
    try:
        import defusedxml  # noqa: F401  (openpyxl uses it when present: no entity expansion tricks)
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise UploadError("The spreadsheet could not be read", cause=type(exc).__name__, fix="Re-export it, or upload a .csv") from exc
    try:
        ws = wb.worksheets[0]
        out: list[list[str]] = []
        for record in ws.iter_rows(values_only=True, max_col=settings.upload_max_columns + 1):
            out.append([_cell(c) for c in record])
            if len(out) > settings.upload_max_rows + 1 + 50:
                break
        return out
    finally:
        wb.close()


def parse_sheet(data: bytes) -> Sheet:
    """Validate and parse a SKU sheet. Raises UploadError (or a subclass) with a message a person can act on."""
    if not data:
        raise UploadError("The sheet is empty", fix="Upload a CSV or XLSX with a header row and one row per SKU")
    if len(data) > settings.upload_max_sheet_bytes:
        raise UploadTooLarge(
            f"The sheet is over {settings.upload_max_sheet_bytes // 1024 // 1024} MB",
            cause=f"{len(data):,} bytes uploaded",
            fix="Upload fewer rows or remove unused columns",
        )
    kind = sniff(data)
    if kind == "zip":
        raw = _read_xlsx(data)
    elif kind == "text":
        raw = _read_csv(data)
    else:
        raise UploadWrongType(
            "The sheet must be a CSV or XLSX file",
            cause=f"The content looks like {kind}, whatever the file is called",
            fix="Upload a .csv (UTF-8) or .xlsx",
        )
    rows = [r for r in raw if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise UploadError("The sheet needs a header row and at least one SKU row")
    headers = [clean(h) for h in rows[0]]
    while headers and not headers[-1]:
        headers.pop()
    if not headers or any(not h for h in headers):
        raise UploadError("Every column needs a header", cause="A header cell is empty", fix="Name each column in row 1")
    if len(headers) > settings.upload_max_columns:
        raise UploadTooLarge(f"The sheet has more than {settings.upload_max_columns} columns", fix="Remove columns the vendor sheet does not need")
    if len({h.lower() for h in headers}) != len(headers) or any(len(h) > 100 for h in headers):
        raise UploadError("Column headers must be unique and under 100 characters")
    body = rows[1:]
    if len(body) > settings.upload_max_rows:
        raise UploadTooLarge(
            f"The sheet has {len(body)} SKU rows; the limit is {settings.upload_max_rows}",
            fix="Upload the first batch; the engine scores each row the same way",
        )
    table: list[list[str]] = []
    for n, record in enumerate(body, start=2):
        cells = (record + [""] * len(headers))[: len(headers)]
        if any(len(c) > settings.upload_max_cell_chars for c in cells):
            raise UploadTooLarge(f"Row {n} has a cell over {settings.upload_max_cell_chars} characters")
        table.append(cells)
    columns = map_columns(headers)
    missing = [f for f in SHEET_FIELDS_NEEDED if f not in columns]
    if missing:
        raise UploadError(
            "The sheet is missing columns the engine needs: " + ", ".join(missing),
            cause=f"Recognised columns: {columns or 'none'}",
            fix="Name columns for the SKU code (Code / SKU), the product (Product Name / Item) and the price (MRP / Price); add Cost to Us if you have it",
        )
    code_i = headers.index(columns["code"])
    seen: dict[str, int] = {}
    for n, cells in enumerate(table, start=2):
        code = cells[code_i]
        if not _CODE.match(code):
            raise UploadError(f"Row {n}: the SKU code {code[:40]!r} is not usable", fix="Use up to 40 letters, digits, spaces and . _ # / -")
        if code in seen:
            raise UploadError(f"Row {n}: the SKU code {code!r} repeats row {seen[code]}", fix="Each SKU needs its own code")
        seen[code] = n
    warnings: list[str] = []
    formulas = sum(1 for cells in table for c in cells if c.startswith(FORMULA_START) and not re.fullmatch(r"[-+]?\d[\d,]*(\.\d+)?", c))
    if formulas:
        warnings.append(f"{formulas} cell(s) start with = + - or @; they are kept as plain text and neutralised in any CSV we export")
    if "cost" not in columns:
        warnings.append("No cost column was recognised: cost is inferred from the vendor's offered margin, or the SKU needs data")
    return Sheet(headers=headers, rows=table, columns=columns, warnings=warnings)


def sheet_to_csv(sheet: Sheet) -> bytes:
    """The sheet as we store it: values exactly as parsed, re-serialised by us (the uploaded bytes are never kept)."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(sheet.headers)
    writer.writerows(sheet.rows)
    return buf.getvalue().encode("utf-8")


# ---------- application ----------

DocStatus = Literal["valid", "expired", "missing", "pending_verification"]


def _short(max_len: int):
    def check(v: str) -> str:
        v = clean(v)
        if len(v) > max_len:
            raise ValueError(f"is over {max_len} characters")
        return v

    return check


class AppDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str
    number: str = ""
    valid_until: str = ""
    status: DocStatus = "valid"

    _t = field_validator("type", "number", mode="before")(_short(80))

    @field_validator("type")
    @classmethod
    def _need_type(cls, v: str) -> str:
        if not v:
            raise ValueError("needs a document type")
        return v

    @field_validator("valid_until", mode="before")
    @classmethod
    def _iso(cls, v: Any) -> str:
        v = clean(v)
        if v:
            try:
                date.fromisoformat(v)
            except ValueError as exc:
                raise ValueError("must be an ISO date like 2027-03-31") from exc
        return v


class ProposedTerms(BaseModel):
    model_config = ConfigDict(extra="ignore")
    margin_offered_pct: float | None = Field(None, ge=0, le=95)
    payment_terms_days: int | None = Field(None, ge=0, le=365)
    moq_units: int | None = Field(None, ge=0, le=1_000_000)
    marketing_support_inr: float | None = Field(None, ge=0, le=1_000_000_000)
    launch_discount_pct: float | None = Field(None, ge=0, le=100)
    returns_policy: str = ""

    _r = field_validator("returns_policy", mode="before")(_short(500))


class ApplicationIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    company_name: str
    brand_name: str
    contact_name: str = ""
    contact_email: str = ""
    city: str = ""
    years_in_business: int | None = Field(None, ge=0, le=300)
    categories: list[str] = Field(default_factory=list, max_length=20)
    vendor_type: str | None = None
    documents: list[AppDocument] = Field(default_factory=list, max_length=20)
    proposed_terms: ProposedTerms = Field(default_factory=ProposedTerms)
    pitch: str = ""

    _s = field_validator("company_name", "brand_name", mode="before")(_short(120))
    _o = field_validator("contact_name", "contact_email", "city", mode="before")(_short(120))
    _p = field_validator("pitch", mode="before")(_short(2000))

    @field_validator("company_name", "brand_name")
    @classmethod
    def _required(cls, v: str) -> str:
        if not v:
            raise ValueError("is required")
        return v

    @field_validator("categories", mode="before")
    @classmethod
    def _cats(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v = v.split(",")
        if not isinstance(v, list):
            raise ValueError("must be a list")  # noqa: TRY004 - pydantic reports ValueError
        out = [clean(c).lower() for c in v if clean(c)]
        if any(len(c) > 60 for c in out):
            raise ValueError("a category is over 60 characters")
        return out

    @field_validator("vendor_type", mode="before")
    @classmethod
    def _vt(cls, v: Any) -> str | None:
        v = clean(v) if v else ""
        return v or None


def parse_application_json(data: bytes) -> ApplicationIn:
    if len(data) > settings.upload_max_application_bytes:
        raise UploadTooLarge(f"The application JSON is over {settings.upload_max_application_bytes // 1024} KB")
    if sniff(data) != "text":
        raise UploadWrongType("The application must be a JSON file", cause="The content is not text")
    try:
        raw = json.loads(data.decode("utf-8-sig"))
    except (ValueError, RecursionError) as exc:
        raise UploadError("The application is not valid JSON", cause=str(exc)[:200]) from exc
    return application_from(raw)


def application_from(raw: Any) -> ApplicationIn:
    if not isinstance(raw, dict):
        raise UploadError("The application must be a JSON object")
    try:
        return ApplicationIn.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise UploadError(
            f"Application: {where}: {first['msg'].removeprefix('Value error, ')}",
            cause=f"{len(exc.errors())} problem(s) in the application",
            fix="Fix the field named, or use the short form instead of a file",
        ) from exc


# ---------- documents ----------


class DocInfo(BaseModel):
    ext: Literal["png", "jpg", "pdf"]
    width: int | None = None
    height: int | None = None


def validate_doc(data: bytes) -> DocInfo:
    if not data:
        raise UploadError("A document is empty")
    if len(data) > settings.upload_max_doc_bytes:
        raise UploadTooLarge(f"A document is over {settings.upload_max_doc_bytes // 1024 // 1024} MB", cause=f"{len(data):,} bytes")
    kind = sniff(data)
    if kind == "pdf":
        return DocInfo(ext="pdf")
    if kind not in {"png", "jpeg"}:
        raise UploadWrongType("Documents must be PNG, JPEG or PDF", cause=f"The content looks like {kind}, whatever the file is called")
    from PIL import Image, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError) as exc:
        raise UploadError("A document image could not be decoded", cause=type(exc).__name__, fix="Re-save the image as PNG or JPEG") from exc
    if width * height > MAX_PIXELS:
        raise UploadTooLarge("A document image has too many pixels", fix="Scan at 150 to 200 dpi")
    return DocInfo(ext="png" if kind == "png" else "jpg", width=width, height=height)
