from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from name_standardization import normalize_site_tag, parse_name_tokens

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
YAML_FILENAMES = {"data.yaml", "data.yml"}
LABEL_DIR_NAMES = {"labels", "label"}

TAG_PRIORITY = ["people", "person", "helmet", "vest", "pack", "backpack", "mask"]
DESCRIPTION_MAP = {
    "people": "多人",
    "person": "一人",
    "helmet": "安全帽",
    "vest": "反光背心",
    "pack": "腰包",
    "backpack": "背包",
    "mask": "口罩",
}

DAY_TEXT = "白天"
NIGHT_TEXT = "晚上"


@dataclass
class DatasetSummary:
    dataset_name: str
    source_path: str
    source_kind: str
    site_token: Optional[str]
    date_token: Optional[str]
    time_token: Optional[str]
    image_count: int
    annotation_count: int
    image_examples: list[str] = field(default_factory=list)
    annotation_examples: list[str] = field(default_factory=list)
    class_name_hits: dict[str, int] = field(default_factory=dict)
    suggested_description: str = ""
    suggested_tags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect dataset ZIP/folder contents and draft metadata.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output-format", choices=["json", "pretty"], default="pretty")
    parser.add_argument("--sample-limit", type=int, default=5)
    return parser.parse_args()


def iter_dataset_targets(source: Path) -> list[Path]:
    if not source.exists():
        raise FileNotFoundError(f"Cannot find --source path: {source}")
    if source.is_file():
        return [source]

    zip_files = sorted(source.glob("*.zip"))
    if zip_files:
        return zip_files

    dirs = [x for x in sorted(source.iterdir()) if x.is_dir()]
    if dirs:
        return dirs

    return [source]


def read_zip_text(zip_path: Path, member: str) -> Optional[str]:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            raw = zf.read(member)
    except Exception:
        return None

    for enc in ("utf-8", "utf-8-sig", "cp950", "big5", "latin-1"):
        try:
            return raw.decode(enc, errors="ignore")
        except Exception:
            continue
    return None


def parse_yaml_names(text: str) -> list[str]:
    lines = text.splitlines()
    names: list[str] = []
    collecting = False

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        if not collecting:
            inline = re.match(r"^names\s*:\s*\[(.*)\]\s*$", stripped, re.IGNORECASE)
            if inline:
                for token in inline.group(1).split(","):
                    t = token.strip().strip('"\'').lower()
                    if t:
                        names.append(t)
                continue

            if re.match(r"^names\s*:\s*$", stripped, re.IGNORECASE):
                collecting = True
            continue

        if re.match(r"^\S.*:\s*", line):
            break

        list_match = re.match(r"^\s*-\s*(.+?)\s*$", line)
        dict_match = re.match(r"^\s*\d+\s*:\s*(.+?)\s*$", line)
        value = list_match.group(1) if list_match else dict_match.group(1) if dict_match else None
        if value:
            t = value.strip().strip('"\'').lower()
            if t:
                names.append(t)

    return list(dict.fromkeys(names))


def extract_label_ids(text: str) -> Counter[int]:
    hits: Counter[int] = Counter()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        first = stripped.split()[0]
        if re.fullmatch(r"\d+", first):
            hits[int(first)] += 1
    return hits


def infer_period(time_token: Optional[str]) -> Optional[str]:
    if not time_token or len(time_token) < 2 or not time_token[:2].isdigit():
        return None
    hour = int(time_token[:2])
    return DAY_TEXT if 6 <= hour < 18 else NIGHT_TEXT


def build_tags(stem: str, site_token: Optional[str], period: Optional[str], observed_tags: list[str]) -> list[str]:
    tags: list[str] = []

    tags.append("ttcps")

    normalized_site = normalize_site_tag(site_token)
    if normalized_site and normalized_site not in tags:
        tags.append(normalized_site)

    if period == DAY_TEXT:
        tags.append("day")
    elif period == NIGHT_TEXT:
        tags.append("night")

    for tag in TAG_PRIORITY:
        if tag in observed_tags:
            tags.append(tag)

    if any(h in stem.lower() for h in ("legacy", "old", "migration", "migrate", "archive")):
        tags.append("legacy")

    return list(dict.fromkeys(tags))


def summarize_zip(target: Path, sample_limit: int) -> DatasetSummary:
    tokens = parse_name_tokens(target.stem)
    entries: list[str] = []
    image_paths: list[str] = []
    annotation_paths: list[str] = []
    yaml_names: list[str] = []
    label_hits: Counter[int] = Counter()

    with zipfile.ZipFile(target, "r") as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            entries.append(name)
            p = Path(name)
            suffix = p.suffix.lower()
            if suffix in IMAGE_EXTS:
                image_paths.append(name)
            if p.name.lower() in YAML_FILENAMES or suffix == ".txt":
                annotation_paths.append(name)
            if p.name.lower() in YAML_FILENAMES:
                text = read_zip_text(target, name)
                if text:
                    yaml_names = parse_yaml_names(text) or yaml_names
            if suffix == ".txt" and any(part.lower() in LABEL_DIR_NAMES for part in p.parts[:-1]):
                text = read_zip_text(target, name)
                if text:
                    label_hits.update(extract_label_ids(text))

    observed_name_hits: Counter[str] = Counter()
    for class_id, cnt in label_hits.items():
        if 0 <= class_id < len(yaml_names):
            observed_name_hits[yaml_names[class_id]] += cnt

    observed_tags = [tag for tag in TAG_PRIORITY if observed_name_hits.get(tag, 0) > 0]

    if "person" in observed_tags and observed_name_hits.get("person", 0) >= 2:
        observed_tags = [t for t in observed_tags if t != "person"]
        observed_tags.insert(0, "people")

    period = infer_period(tokens.time_token)
    desc_tokens: list[str] = []
    if period:
        desc_tokens.append(period)
    for tag in TAG_PRIORITY:
        if tag in observed_tags and tag in DESCRIPTION_MAP:
            desc_tokens.append(DESCRIPTION_MAP[tag])
    if not desc_tokens:
        desc_tokens.append("待人工確認")

    notes: list[str] = []
    if not yaml_names:
        notes.append("Missing data.yaml names mapping")
    if not label_hits:
        notes.append("No labels/*.txt class IDs found")
    if not image_paths:
        notes.append("No images found")

    return DatasetSummary(
        dataset_name=tokens.normalized_stem,
        source_path=str(target),
        source_kind="zip",
        site_token=tokens.site_token,
        date_token=tokens.date_token,
        time_token=tokens.time_token,
        image_count=len(image_paths),
        annotation_count=len(annotation_paths),
        image_examples=image_paths[:sample_limit],
        annotation_examples=annotation_paths[:sample_limit],
        class_name_hits=dict(observed_name_hits.most_common()),
        suggested_description="，".join(dict.fromkeys(desc_tokens)),
        suggested_tags=build_tags(tokens.normalized_stem, tokens.site_token, period, observed_tags),
        notes=notes,
    )


def summarize_dir(target: Path, sample_limit: int) -> DatasetSummary:
    tokens = parse_name_tokens(target.name)
    image_paths = [str(p.relative_to(target)).replace("\\", "/") for p in target.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    annotation_paths = [str(p.relative_to(target)).replace("\\", "/") for p in target.rglob("*") if p.is_file() and (p.suffix.lower() == ".txt" or p.name.lower() in YAML_FILENAMES)]
    period = infer_period(tokens.time_token)
    description = period if period else "待人工確認"
    tags = build_tags(tokens.normalized_stem, tokens.site_token, period, [])

    return DatasetSummary(
        dataset_name=tokens.normalized_stem,
        source_path=str(target),
        source_kind="directory",
        site_token=tokens.site_token,
        date_token=tokens.date_token,
        time_token=tokens.time_token,
        image_count=len(image_paths),
        annotation_count=len(annotation_paths),
        image_examples=image_paths[:sample_limit],
        annotation_examples=annotation_paths[:sample_limit],
        class_name_hits={},
        suggested_description=description,
        suggested_tags=tags,
        notes=[],
    )


def summarize_entries(target: Path, sample_limit: int) -> DatasetSummary:
    if target.is_file():
        return summarize_zip(target, sample_limit)
    return summarize_dir(target, sample_limit)


def render_pretty(summaries: Iterable[DatasetSummary]) -> str:
    blocks = []
    for s in summaries:
        lines = [
            "=" * 72,
            f"dataset_name: {s.dataset_name}",
            f"source: {s.source_path} ({s.source_kind})",
            f"site_token: {s.site_token}",
            f"date_token: {s.date_token}",
            f"time_token: {s.time_token}",
            f"image_count: {s.image_count}",
            f"annotation_count: {s.annotation_count}",
            f"suggested_description: {s.suggested_description}",
            f"suggested_tags: {', '.join(s.suggested_tags)}",
            f"image_examples: {s.image_examples}",
            f"annotation_examples: {s.annotation_examples}",
            f"class_name_hits: {s.class_name_hits}",
        ]
        if s.notes:
            lines.append(f"notes: {s.notes}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def main() -> int:
    args = parse_args()
    source = Path(args.source)
    targets = iter_dataset_targets(source)
    summaries = [summarize_entries(t, args.sample_limit) for t in targets]

    if args.output_format == "json":
        print(json.dumps([asdict(x) for x in summaries], ensure_ascii=False, indent=2))
    else:
        print(render_pretty(summaries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
