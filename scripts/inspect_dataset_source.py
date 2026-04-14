from __future__ import annotations

import argparse
import json
import random
import re
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Iterable, Iterator, Optional

try:
    from PIL import Image, ImageStat
except ImportError:
    Image = None
    ImageStat = None

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
ANNOTATION_EXTS = {".json", ".jsonl", ".txt", ".xml", ".csv", ".yaml", ".yml"}
YAML_FILENAMES = {"data.yaml", "data.yml"}
LABEL_DIR_NAMES = {"labels", "label"}
DESCRIPTION_PRIORITY = ["people", "person", "helmet", "vest", "pack", "backpack", "mask", "bike", "motorcycle", "truck", "car"]
TAG_PRIORITY = ["people", "person", "helmet", "vest", "pack", "backpack", "mask", "bike", "motorcycle", "truck", "car"]
AI_GEN_HINTS = ("gemini", "grok", "synth", "synthetic", "genai", "generative", "diffusion")

TAG_HINTS = {
    "helmet": ["helmet", "hardhat", "hard-hat", "safety helmet", "\u5b89\u5168\u5e3d"],
    "mask": ["mask", "face mask", "\u53e3\u7f69"],
    "pack": ["pack", "waistpack", "waist pack", "fannypack", "fanny pack", "\u8170\u5305"],
    "backpack": ["backpack", "\u80cc\u5305"],
    "vest": ["vest", "reflective vest", "\u53cd\u5149\u80cc\u5fc3", "\u80cc\u5fc3"],
    "person": ["person", "people", "human", "pedestrian", "\u4eba", "\u4eba\u54e1"],
    "bike": ["bike", "bicycle", "\u8173\u8e0f\u8eca", "\u81ea\u884c\u8eca", "\u55ae\u8eca"],
    "motorcycle": ["motorcycle", "motorbike", "\u6a5f\u8eca"],
    "truck": ["truck", "\u5361\u8eca"],
    "car": ["car", "vehicle", "\u6c7d\u8eca", "\u8eca\u8f1b"],
}

DESCRIPTION_MAP = {
    "people": "\u591a\u4eba",
    "person": "\u4e00\u4eba",
    "helmet": "\u5b89\u5168\u5e3d",
    "mask": "\u53e3\u7f69",
    "pack": "\u8170\u5305",
    "backpack": "\u80cc\u5305",
    "vest": "\u53cd\u5149\u80cc\u5fc3",
    "bike": "\u8173\u8e0f\u8eca",
    "motorcycle": "\u6a5f\u8eca",
    "truck": "\u5361\u8eca",
    "car": "\u6c7d\u8eca",
}

DAY_TEXT = "\u767d\u5929"
NIGHT_TEXT = "\u665a\u4e0a"
UNKNOWN_TEXT = "\u5f85\u4eba\u5de5\u78ba\u8a8d"


@dataclass
class DatasetSummary:
    dataset_name: str
    source_path: str
    source_kind: str
    apc_id: Optional[str]
    date_token: Optional[str]
    time_token: Optional[str]
    image_count: int
    annotation_count: int
    image_examples: list[str] = field(default_factory=list)
    annotation_examples: list[str] = field(default_factory=list)
    keyword_hits: dict[str, int] = field(default_factory=dict)
    class_name_hits: dict[str, int] = field(default_factory=dict)
    suggested_description: str = ""
    suggested_tags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class EntryInfo:
    path: str
    suffix: str
    text_probe: Optional[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect legacy dataset ZIP/folder contents and generate draft description/tags.",
    )
    parser.add_argument("--source", required=True, help="ZIP file, extracted dataset folder, or folder of ZIPs.")
    parser.add_argument(
        "--output-format",
        choices=["json", "pretty"],
        default="pretty",
        help="pretty: human-readable summary, json: machine-readable JSON",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=5,
        help="How many example image/annotation file paths to keep. Default: 5",
    )
    return parser.parse_args()


def iter_dataset_targets(source: Path) -> list[Path]:
    if not source.exists():
        raise FileNotFoundError(f"\u627e\u4e0d\u5230 source \u8def\u5f91: {source}")
    if source.is_file():
        return [source]

    zip_files = sorted(source.glob("*.zip"))
    if zip_files:
        return zip_files

    candidate_dirs = [item for item in sorted(source.iterdir()) if item.is_dir()]
    if candidate_dirs:
        return candidate_dirs

    return [source]


def infer_tokens_from_name(stem: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    parts = [part for part in re.split(r"[_\-\s]+", stem) if part]
    apc_id = parts[0] if parts else None

    date_token = None
    time_token = None
    for index, part in enumerate(parts):
        if not date_token and re.fullmatch(r"\d{6}|\d{8}", part):
            date_token = part
            for candidate in parts[index + 1 :]:
                if re.fullmatch(r"\d{4}|\d{6}", candidate):
                    time_token = candidate
                    break
            continue
        if not time_token and re.fullmatch(r"\d{4}|\d{6}", part):
            time_token = part

    return apc_id, date_token, time_token


def normalize_site_tag(apc_id: Optional[str]) -> Optional[str]:
    if not apc_id:
        return None
    normalized = apc_id.strip().lower()
    if not normalized:
        return None

    match = re.match(r"^([a-z]+)", normalized)
    if not match:
        return None

    site_tag = match.group(1)
    if len(site_tag) < 3:
        return normalized
    return site_tag


def has_ai_gen_hint(stem: str) -> bool:
    lowered = stem.lower()
    return any(hint in lowered for hint in AI_GEN_HINTS)


def infer_day_or_night(time_token: Optional[str]) -> Optional[str]:
    if not time_token or len(time_token) < 2 or not time_token[:2].isdigit():
        return None
    hour = int(time_token[:2])
    return DAY_TEXT if 6 <= hour < 18 else NIGHT_TEXT


def read_text_probe_from_bytes(raw: bytes) -> Optional[str]:
    for encoding in ("utf-8", "utf-8-sig", "cp950", "big5", "latin-1"):
        try:
            return raw.decode(encoding, errors="ignore")[:20000]
        except Exception:
            continue
    return None


def read_text_probe(path: Path) -> Optional[str]:
    if path.suffix.lower() not in ANNOTATION_EXTS:
        return None
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:20000]
    except Exception:
        try:
            return path.read_text(encoding="cp950", errors="ignore")[:20000]
        except Exception:
            return None


def iter_entries_from_dir(root: Path) -> Iterator[EntryInfo]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        yield EntryInfo(
            path=path.relative_to(root).as_posix(),
            suffix=path.suffix.lower(),
            text_probe=read_text_probe(path),
        )


def iter_entries_from_zip(zip_path: Path) -> Iterator[EntryInfo]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            suffix = Path(name).suffix.lower()
            text_probe = None
            if suffix in ANNOTATION_EXTS:
                try:
                    text_probe = read_text_probe_from_bytes(zf.read(name))
                except Exception:
                    text_probe = None
            yield EntryInfo(path=Path(name).as_posix(), suffix=suffix, text_probe=text_probe)


def extract_keywords(text: str) -> Counter[str]:
    lowered = text.lower()
    hits: Counter[str] = Counter()
    for tag, hints in TAG_HINTS.items():
        for hint in hints:
            normalized_hint = hint.lower()
            if normalized_hint in lowered:
                hits[tag] += lowered.count(normalized_hint) or 1
    return hits


def normalize_class_name(raw: str) -> Optional[str]:
    cleaned = raw.strip().strip("\"'").lower()
    if not cleaned:
        return None
    for canonical, hints in TAG_HINTS.items():
        hint_set = {hint.lower() for hint in hints}
        if cleaned == canonical or cleaned in hint_set:
            return canonical
    return cleaned if len(cleaned) >= 2 else None


def extract_class_names(text: str) -> Counter[str]:
    class_hits: Counter[str] = Counter()
    patterns = [
        r'"name"\s*:\s*"([^"]+)"',
        r'"label"\s*:\s*"([^"]+)"',
        r'"category"\s*:\s*"([^"]+)"',
        r'classes?\s*[:=]\s*\[([^\]]+)\]',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text, re.IGNORECASE):
            for token in re.split(r"[,\s]+", match.strip("[] \"'")):
                normalized = normalize_class_name(token)
                if normalized:
                    class_hits[normalized] += 1
    return class_hits


def is_yaml_metadata_file(path: str) -> bool:
    return Path(path).name.lower() in YAML_FILENAMES


def is_label_annotation_file(path: str) -> bool:
    file_path = Path(path)
    if file_path.suffix.lower() != ".txt":
        return False
    return any(part.lower() in LABEL_DIR_NAMES for part in file_path.parts[:-1])


def parse_yaml_names(text: str) -> list[str]:
    lines = text.splitlines()
    names: list[str] = []
    collecting = False

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        if not collecting:
            inline_match = re.match(r"^names\s*:\s*\[(.*)\]\s*$", stripped, re.IGNORECASE)
            if inline_match:
                for token in inline_match.group(1).split(","):
                    normalized = normalize_class_name(token)
                    if normalized:
                        names.append(normalized)
                continue

            dict_inline_match = re.match(r"^names\s*:\s*\{(.*)\}\s*$", stripped, re.IGNORECASE)
            if dict_inline_match:
                for pair in dict_inline_match.group(1).split(","):
                    _, _, value = pair.partition(":")
                    normalized = normalize_class_name(value)
                    if normalized:
                        names.append(normalized)
                continue

            if re.match(r"^names\s*:\s*$", stripped, re.IGNORECASE):
                collecting = True
            continue

        if re.match(r"^\S.*:\s*", line):
            break

        list_match = re.match(r"^\s*-\s*(.+?)\s*$", line)
        dict_match = re.match(r"^\s*\d+\s*:\s*(.+?)\s*$", line)
        value = None
        if list_match:
            value = list_match.group(1)
        elif dict_match:
            value = dict_match.group(1)
        else:
            continue

        normalized = normalize_class_name(value)
        if normalized:
            names.append(normalized)

    return list(dict.fromkeys(names))


def extract_label_ids(text: str) -> Counter[int]:
    hits: Counter[int] = Counter()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        token = stripped.split()[0]
        if re.fullmatch(r"\d+", token):
            hits[int(token)] += 1
    return hits


def read_binary_bytes(target: Path, entry_path: str) -> Optional[bytes]:
    try:
        if target.is_file():
            with zipfile.ZipFile(target, "r") as zf:
                return zf.read(entry_path)
        return (target / Path(entry_path)).read_bytes()
    except Exception:
        return None


"""
def infer_periods_from_sample_images(target: Path, image_paths: list[str], stem: str) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    if not image_paths:
        return [], notes
    if Image is None or ImageStat is None:
        notes.append("無法以影像抽樣判斷白天或晚上，因為 Pillow 尚未安裝。")
        return [], notes

    sample_size = min(2, len(image_paths))
    rng = random.Random(stem)
    sampled_paths = rng.sample(image_paths, sample_size)
    inferred_periods: list[str] = []

    for image_path in sampled_paths:
        raw = read_binary_bytes(target, image_path)
        if not raw:
            continue
        try:
            with Image.open(BytesIO(raw)) as image:
                rgb_image = image.convert("RGB")
                stat = ImageStat.Stat(rgb_image)
                mean_brightness = sum(stat.mean) / len(stat.mean)
                if mean_brightness >= 110:
                    inferred_periods.append(DAY_TEXT)
                else:
                    inferred_periods.append(NIGHT_TEXT)
        except Exception:
            continue

    deduped_periods = list(dict.fromkeys(inferred_periods))
    if not deduped_periods:
        notes.append("已抽樣影像，但無法完成白天或晚上辨識。")
    elif len(deduped_periods) == 2:
        notes.append("抽樣影像同時出現白天與晚上特徵，因此保留 day 與 night 兩個標籤。")
    return deduped_periods, notes
"""


def infer_periods_from_sample_images(target: Path, image_paths: list[str], stem: str) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    if not image_paths:
        return [], notes
    if Image is None or ImageStat is None:
        notes.append("\u7121\u6cd5\u4ee5\u5f71\u50cf\u62bd\u6a23\u5224\u65b7\u767d\u5929\u6216\u665a\u4e0a\uff0c\u56e0\u70ba Pillow \u5c1a\u672a\u5b89\u88dd\u3002")
        return [], notes

    sample_size = min(2, len(image_paths))
    rng = random.Random(stem)
    sampled_paths = rng.sample(image_paths, sample_size)
    inferred_periods: list[str] = []

    for image_path in sampled_paths:
        raw = read_binary_bytes(target, image_path)
        if not raw:
            continue
        try:
            with Image.open(BytesIO(raw)) as image:
                rgb_image = image.convert("RGB")
                stat = ImageStat.Stat(rgb_image)
                mean_brightness = sum(stat.mean) / len(stat.mean)
                if mean_brightness >= 110:
                    inferred_periods.append(DAY_TEXT)
                else:
                    inferred_periods.append(NIGHT_TEXT)
        except Exception:
            continue

    deduped_periods = list(dict.fromkeys(inferred_periods))
    if not deduped_periods:
        notes.append("\u5df2\u62bd\u6a23\u5f71\u50cf\uff0c\u4f46\u7121\u6cd5\u5b8c\u6210\u767d\u5929\u6216\u665a\u4e0a\u8fa8\u8b58\u3002")
    elif len(deduped_periods) == 2:
        notes.append("\u62bd\u6a23\u5f71\u50cf\u540c\u6642\u51fa\u73fe\u767d\u5929\u8207\u665a\u4e0a\u7279\u5fb5\uff0c\u56e0\u6b64\u4fdd\u7559 day \u8207 night \u5169\u500b\u6a19\u7c64\u3002")
    return deduped_periods, notes


def derive_subject_count_tag(label_entry_id_hits: list[Counter[int]], yaml_names: list[str]) -> Optional[str]:
    if not yaml_names:
        return None

    try:
        person_index = yaml_names.index("person")
    except ValueError:
        return None

    max_people_in_one_image = 0
    for entry_hits in label_entry_id_hits:
        max_people_in_one_image = max(max_people_in_one_image, entry_hits.get(person_index, 0))

    if max_people_in_one_image >= 2:
        return "people"
    if max_people_in_one_image == 1:
        return "person"
    return None


def build_observed_label_name_hits(label_id_hits: Counter[int], yaml_names: list[str]) -> tuple[Counter[str], list[int]]:
    observed_hits: Counter[str] = Counter()
    unmapped_ids: list[int] = []
    for class_id, count in label_id_hits.items():
        if 0 <= class_id < len(yaml_names):
            observed_hits[yaml_names[class_id]] += count
        else:
            unmapped_ids.append(class_id)
    return observed_hits, sorted(unmapped_ids)


def build_description(periods: list[str], observed_tags: list[str], fallback_tags: Counter[str]) -> str:
    description_tokens: list[str] = []
    description_tokens.extend(periods)

    for tag in DESCRIPTION_PRIORITY:
        if tag in observed_tags:
            description_tokens.append(DESCRIPTION_MAP[tag])

    if not observed_tags:
        for tag in DESCRIPTION_PRIORITY:
            if fallback_tags.get(tag):
                description_tokens.append(DESCRIPTION_MAP.get(tag, tag))

    if not description_tokens:
        description_tokens.append(UNKNOWN_TEXT)

    return "\uff0c".join(dict.fromkeys(description_tokens))


def build_tags(stem: str, apc_id: Optional[str], periods: list[str], observed_tags: list[str], fallback_tags: Counter[str]) -> list[str]:
    tags: list[str] = []
    site_tag = normalize_site_tag(apc_id)

    if site_tag:
        tags.append(site_tag)

    if has_ai_gen_hint(stem):
        tags.append("AI Gen")

    if DAY_TEXT in periods:
        tags.append("day")
    if NIGHT_TEXT in periods:
        tags.append("night")

    source_tags = observed_tags if observed_tags else [tag for tag in TAG_PRIORITY if fallback_tags.get(tag)]
    for tag in TAG_PRIORITY:
        if tag in source_tags:
            tags.append(tag)

    if has_legacy_hint(stem):
        tags.append("legacy")

    return list(dict.fromkeys(tags))


def summarize_entries(target: Path, sample_limit: int) -> DatasetSummary:
    source_kind = "zip" if target.is_file() else "directory"
    stem = target.stem if target.is_file() else target.name
    apc_id, date_token, time_token = infer_tokens_from_name(stem)

    entries = list(iter_entries_from_zip(target) if target.is_file() else iter_entries_from_dir(target))

    image_paths = [entry.path for entry in entries if entry.suffix in IMAGE_EXTS]
    annotation_entries = [entry for entry in entries if entry.suffix in ANNOTATION_EXTS]

    keyword_hits: Counter[str] = Counter()
    class_name_hits: Counter[str] = Counter()
    yaml_names: list[str] = []
    label_id_hits: Counter[int] = Counter()
    label_entry_id_hits: list[Counter[int]] = []
    notes: list[str] = []

    for entry in annotation_entries:
        if not entry.text_probe:
            continue
        keyword_hits.update(extract_keywords(entry.text_probe))
        class_name_hits.update(extract_class_names(entry.text_probe))
        if is_yaml_metadata_file(entry.path):
            yaml_names = parse_yaml_names(entry.text_probe) or yaml_names
        if is_label_annotation_file(entry.path):
            current_label_ids = extract_label_ids(entry.text_probe)
            label_id_hits.update(current_label_ids)
            label_entry_id_hits.append(current_label_ids)

    combined_name_text = "\n".join(entry.path.lower() for entry in entries[:300])
    keyword_hits.update(extract_keywords(combined_name_text))

    observed_label_name_hits, unmapped_ids = build_observed_label_name_hits(label_id_hits, yaml_names)
    class_name_hits.update(observed_label_name_hits)
    keyword_hits.update(observed_label_name_hits)

    subject_count_tag = derive_subject_count_tag(label_entry_id_hits, yaml_names)
    observed_tags = [tag for tag in TAG_PRIORITY if observed_label_name_hits.get(tag)]
    if subject_count_tag:
        observed_tags = [tag for tag in observed_tags if tag != "person"]
        observed_tags.insert(0, subject_count_tag)

    periods: list[str] = []
    period_from_name = infer_day_or_night(time_token)
    if period_from_name:
        periods.append(period_from_name)
    elif has_ai_gen_hint(stem):
        inferred_periods, period_notes = infer_periods_from_sample_images(target, image_paths, stem)
        periods.extend(inferred_periods)
        notes.extend(period_notes)

    if not yaml_names:
        notes.append("\u627e\u4e0d\u5230 data.yaml\uff0clabels \u7121\u6cd5\u5b8c\u6574\u5c0d\u7167 class \u540d\u7a31\u3002")
    if yaml_names and not label_id_hits:
        notes.append("\u627e\u5230 data.yaml\uff0c\u4f46 labels \u5167\u6c92\u6709\u53ef\u89e3\u6790\u7684 class id\u3002")
    if unmapped_ids:
        notes.append(f"labels \u51fa\u73fe\u672a\u5c0d\u61c9\u5230 data.yaml \u7684 class id: {unmapped_ids}")
    if not annotation_entries:
        notes.append("\u627e\u4e0d\u5230\u5e38\u898b\u6a19\u8a3b\u6a94\uff0c\u63cf\u8ff0\u8207 tags \u53ea\u80fd\u4fdd\u5b88\u63a8\u4f30\u3002")
    if not image_paths:
        notes.append("\u627e\u4e0d\u5230\u5e38\u898b\u5f71\u50cf\u6a94\uff0c\u8cc7\u6599\u96c6\u53ef\u80fd\u4e0d\u5b8c\u6574\u3002")
    if image_paths and "person" not in observed_tags and not keyword_hits.get("person"):
        notes.append("\u672a\u5f9e labels \u6216\u6a94\u540d\u95dc\u9375\u5b57\u660e\u78ba\u89c0\u5bdf\u5230 person\u3002")

    suggested_description = build_description(list(dict.fromkeys(periods)), observed_tags, keyword_hits)
    suggested_tags = build_tags(stem, apc_id, list(dict.fromkeys(periods)), observed_tags, keyword_hits)

    return DatasetSummary(
        dataset_name=stem,
        source_path=str(target),
        source_kind=source_kind,
        apc_id=apc_id,
        date_token=date_token,
        time_token=time_token,
        image_count=len(image_paths),
        annotation_count=len(annotation_entries),
        image_examples=image_paths[:sample_limit],
        annotation_examples=[entry.path for entry in annotation_entries[:sample_limit]],
        keyword_hits=dict(keyword_hits.most_common()),
        class_name_hits=dict(class_name_hits.most_common(20)),
        suggested_description=suggested_description,
        suggested_tags=suggested_tags,
        notes=notes,
    )


def render_pretty(summaries: Iterable[DatasetSummary]) -> str:
    blocks = []
    for summary in summaries:
        block = [
            "=" * 72,
            f"dataset_name: {summary.dataset_name}",
            f"source: {summary.source_path} ({summary.source_kind})",
            f"apc_id: {summary.apc_id}",
            f"date_token: {summary.date_token}",
            f"time_token: {summary.time_token}",
            f"image_count: {summary.image_count}",
            f"annotation_count: {summary.annotation_count}",
            f"suggested_description: {summary.suggested_description}",
            f"suggested_tags: {', '.join(summary.suggested_tags)}",
            f"image_examples: {summary.image_examples}",
            f"annotation_examples: {summary.annotation_examples}",
            f"keyword_hits: {summary.keyword_hits}",
            f"class_name_hits: {summary.class_name_hits}",
        ]
        if summary.notes:
            block.append(f"notes: {summary.notes}")
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


def main() -> int:
    args = parse_args()
    source = Path(args.source)
    targets = iter_dataset_targets(source)
    summaries = [summarize_entries(target, args.sample_limit) for target in targets]

    if args.output_format == "json":
        print(json.dumps([asdict(item) for item in summaries], ensure_ascii=False, indent=2))
    else:
        print(render_pretty(summaries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
