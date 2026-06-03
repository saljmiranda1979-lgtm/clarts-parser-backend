from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "tools" / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from rapidocr_onnxruntime import RapidOCR  # type: ignore

OCR = None


def get_ocr():
    global OCR
    if OCR is None:
        OCR = RapidOCR()
    return OCR


def render_pdf(pdf_path: Path, work_dir: Path) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    page_png = work_dir / f"{pdf_path.stem}-page.png"
    try:
        import pypdfium2 as pdfium  # type: ignore
        from PIL import Image  # type: ignore

        pdf = pdfium.PdfDocument(str(pdf_path))
        page = pdf[0]
        bitmap = page.render(scale=2)
        image = bitmap.to_pil()
        image = image.resize((1224, 1584), Image.Resampling.LANCZOS)
        image.save(page_png)
        return page_png
    except Exception:
        pass

    raw_png = work_dir / f"{pdf_path.stem}-raw.png"
    subprocess.run(["sips", "-s", "format", "png", str(pdf_path), "--out", str(raw_png)], check=True, capture_output=True)
    subprocess.run(["sips", "-z", "1584", "1224", str(raw_png), "--out", str(page_png)], check=True, capture_output=True)
    return page_png


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def parse_number(text: str) -> float | None:
    cleaned = text.replace("O", "0").replace("o", "0")
    cleaned = cleaned.replace("（", "(").replace("）", ")")
    match = re.search(r"-?\d[\d,]*(?:[.]\d+)?", cleaned)
    if not match:
        return None
    raw = match.group(0).replace(",", "")
    parts = raw.split(".")
    if len(parts) > 2:
        raw = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(raw)
    except ValueError:
        return None


def parse_last_number(text: str) -> float | None:
    cleaned = text.replace("（", "(").replace("）", ")")
    matches = re.findall(r"-?\d[\d,]*(?:[.]\d+)?", cleaned)
    if not matches:
        return None
    raw = matches[-1].replace(",", "")
    parts = raw.split(".")
    if len(parts) > 2:
        raw = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(raw)
    except ValueError:
        return None


def is_numeric_line(text: str) -> bool:
    compact = re.sub(r"[\s,$=*'\":()（）]", "", text)
    compact = compact.replace(",", "").replace(".", "", 1).replace("-", "", 1)
    return bool(compact) and compact.isdigit()


def numbers_right_of(lines: list[dict], index: int, y_tolerance: float = 18, max_x: float | None = None) -> list[float]:
    label = lines[index]
    values = []
    for item in lines:
        if item["x"] <= label["x"]:
            continue
        if max_x is not None and item["x"] > max_x:
            continue
        if abs(item["y"] - label["y"]) > y_tolerance:
            continue
        value = parse_number(item["text"])
        if value is not None and is_numeric_line(item["text"]):
            values.append((item["x"], value))
    return [value for _, value in sorted(values)]


def next_number(lines: list[dict], start: int, max_ahead: int = 8, integer: bool = False) -> float:
    for item in lines[start + 1 : start + 1 + max_ahead]:
        value = parse_number(item["text"])
        if value is None:
            continue
        if integer and abs(value - round(value)) > 0.001:
            continue
        if is_numeric_line(item["text"]):
            return float(round(value)) if integer else value
    return 0.0


def find_index(lines: list[dict], *needles: str, start: int = 0) -> int | None:
    normalized_needles = [normalize(n) for n in needles]
    for index, item in enumerate(lines[start:], start=start):
        text = normalize(item["text"])
        if all(needle in text for needle in normalized_needles):
            return index
    return None


def row_numbers(lines: list[dict], *needles: str, min_y: float = 0, max_label_x: float | None = None, max_value_x: float | None = None) -> list[float]:
    normalized_needles = [normalize(n) for n in needles]
    for index, item in enumerate(lines):
        if item["y"] < min_y:
            continue
        if max_label_x is not None and item["x"] > max_label_x:
            continue
        text = normalize(item["text"])
        if all(needle in text for needle in normalized_needles):
            return numbers_right_of(lines, index, max_x=max_value_x)
    return []


def pair(values: list[float], index: int) -> int:
    return int(round(values[index])) if len(values) > index else 0


def value_after(lines: list[dict], *needles: str, integer: bool = False, default: float = 0.0) -> float:
    index = find_index(lines, *needles)
    if index is None:
        return default
    same_row = numbers_right_of(lines, index)
    if same_row:
        value = same_row[0] if not integer else round(same_row[0])
        return float(value)
    return next_number(lines, index, integer=integer)


def value_on_row(lines: list[dict], *needles: str, integer: bool = False, default: float = 0.0) -> float:
    index = find_index(lines, *needles)
    if index is None:
        return default
    same_row = numbers_right_of(lines, index)
    if not same_row:
        return default
    value = same_row[0] if not integer else round(same_row[0])
    return float(value)


def value_from_line_text(lines: list[dict], *needles: str, default: float = 0.0) -> float:
    normalized_needles = [normalize(n) for n in needles]
    for item in lines:
        text = normalize(item["text"])
        if all(needle in text for needle in normalized_needles):
            value = parse_last_number(item["text"])
            if value is not None:
                return value
    return default


def date_from_text(lines: list[dict], filename: str) -> str:
    for item in lines:
        match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", item["text"])
        if match:
            month, day, year = match.groups()
            year = f"20{year}" if len(year) == 2 else year
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    match = re.search(r"(\d{1,2})-(\d{1,2})-(\d{2,4})", filename)
    if match:
        month, day, year = match.groups()
        year = f"20{year}" if len(year) == 2 else year
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return ""


def city_msw(lines: list[dict]) -> tuple[int, float]:
    index = find_index(lines, "city", "msw", "inbound")
    if index is None:
        return 0, 0.0
    embedded = parse_last_number(lines[index]["text"])
    if embedded is not None:
        return 0, embedded
    same_row = numbers_right_of(lines, index, y_tolerance=14)
    if len(same_row) >= 2:
        return int(same_row[0]), same_row[1]
    nums: list[float] = []
    for item in lines[index + 1 : index + 6]:
        value = parse_number(item["text"])
        if value is not None and is_numeric_line(item["text"]):
            nums.append(value)
        if len(nums) >= 2:
            return int(nums[0]), nums[1]
    return (int(nums[0]), 0.0) if nums else (0, 0.0)


def parse_report(pdf_path: Path, work_dir: Path | None = None) -> dict:
    work_dir = work_dir or ROOT / "tmp" / "ocr"
    image_path = render_pdf(pdf_path, work_dir)
    result, _ = get_ocr()(str(image_path))
    lines = []
    for box, text, confidence in result or []:
        y = min(point[1] for point in box)
        x = min(point[0] for point in box)
        lines.append({"text": text, "confidence": float(confidence), "x": float(x), "y": float(y)})
    lines.sort(key=lambda item: (item["y"], item["x"]))

    city_count, city_tons = city_msw(lines)
    city_gf_funded = value_from_line_text(lines, "city", "gf", "funded")
    city_msw_inbound_funded = value_from_line_text(lines, "msw", "inbound")
    city_la_msw_inbound = city_tons
    if city_msw_inbound_funded:
        city_la_msw_inbound = round(city_msw_inbound_funded + city_gf_funded, 2)
    outbound_loads = value_after(lines, "total", "outbound", "loads", integer=True)
    data = {
        "date": date_from_text(lines, pdf_path.name),
        "pdfName": pdf_path.name,
        "inboundTotal": value_after(lines, "total", "inbound"),
        "outboundTotal": value_after(lines, "total", "outbound", "tons"),
        "outboundMinusPrior": value_after(lines, "outbound", "minus", "prior"),
        "priorDayLeftover": value_after(lines, "prior", "leftover"),
        "tonsFromPriorDayLoads": value_after(lines, "tons", "prior", "loads"),
        "tonsPreloaded": value_after(lines, "tons", "preloaded"),
        "trashLeftOnFloor": value_after(lines, "trash", "left", "floor"),
        "greenFoodLeftOnFloor": value_after(lines, "green", "food", "left", "floor"),
        "totalOutboundLoads": int(outbound_loads),
        "loadsFromPriorDays": int(value_after(lines, "loads", "prior", "days", integer=True)),
        "trucksPreloaded": int(value_after(lines, "trucks", "preloaded", integer=True)),
        "cityLaMswInbound": city_la_msw_inbound,
        "cityLaMswCount": city_count,
        "cityGfFunded": city_gf_funded,
        "cityLaMswInboundFunded": city_msw_inbound_funded,
        "inboundCityFoodWaste": value_after(lines, "inbound", "city", "food", "waste"),
        "inboundCityGreenWaste": value_after(lines, "inbound", "city", "green", "waste"),
        "inboundCityRecycling": value_on_row(lines, "inbound", "city", "recycling"),
        "inboundCommercial401": value_after(lines, "inbound", "commercial", "401"),
        "destinations": {
            "curbside173Sunshine": int(value_on_row(lines, "curbside", "173", "sunshine", integer=True)),
            "commercial401Sunshine": int(value_on_row(lines, "commercial", "401", "sunshine", integer=True)),
            "elSobranteLandfill": int(value_on_row(lines, "sobrante", "landfill", integer=True)),
            "cityOfLaToRecology": int(value_on_row(lines, "city", "la", "recology", integer=True)),
            "cityOfLaChiquita": 0,
            "cityOfLaElSimiValley": int(value_on_row(lines, "simi", "valley", integer=True)),
            "greenWasteCalmetFacility": int(value_on_row(lines, "green", "waste", "facility", integer=True)),
        },
        "haulers": {},
        "parseMeta": {
            "method": "rapidocr-onnxruntime",
            "image": str(image_path),
            "lineCount": len(lines),
            "averageConfidence": round(sum(line["confidence"] for line in lines) / max(len(lines), 1), 4),
        },
    }
    ecology = row_numbers(lines, "ecology", min_y=900, max_label_x=250, max_value_x=650)
    crr = row_numbers(lines, "crr", min_y=900, max_label_x=250, max_value_x=650)
    city = row_numbers(lines, "cityofla", min_y=900, max_label_x=250, max_value_x=650)
    eco = row_numbers(lines, "eco", "recology", min_y=900, max_label_x=250, max_value_x=650)
    data["haulers"] = {
        "Ecology": {"trucksOnSite": pair(ecology, 0), "loadsCompleted": pair(ecology, 1)},
        "CR&R": {"trucksOnSite": pair(crr, 0), "loadsCompleted": pair(crr, 1)},
        "City of LA": {"trucksOnSite": pair(city, 0), "loadsCompleted": pair(city, 1)},
        "ECO to Recology": {"trucksOnSite": pair(eco, 0), "loadsCompleted": pair(eco, 1)},
    }
    return data


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: parse_clarts.py <report.pdf>", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(parse_report(Path(sys.argv[1])), indent=2))


if __name__ == "__main__":
    main()
