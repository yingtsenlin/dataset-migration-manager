from __future__ import annotations

import argparse
import json
import re
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from random import Random


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
DEFAULT_DATA_YAML = """names:
- person
- pack
- helmet
- mask
nc: 4
train: ../train/images
val: ../valid/images
"""

APC_MAP = {
    "52cctv02": "APC01",
    "52cctv03": "APC02",
    "66cctv01": "APC03",
    "ccrcctv01": "APC04",
    "30cctv01": "APC05",
    "11cctv01": "APC06",
    "11cctv02": "APC07",
    "12cctv01": "APC08",
    "12cctv02": "APC09",
    "13cctv01": "APC10",
    "13cctv02": "APC11",
    "52cctv01": "APC12",
    "61cctv01": "APC13",
    "61cctv02": "APC14",
}


@dataclass
class PreparedItem:
    source_folder: str
    renamed_stem: str
    yaml_added: bool
    source_images: int
    source_labels: int
    packed_images: int
    packed_labels: int
    tar_path: str
    zip_path: str
    description: str
    keywords: list[str]
    samples: list[dict[str, str | None]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare today's mod_output datasets for upload.")
    parser.add_argument("--source-root", required=True, help="Folder containing extracted dataset folders.")
    parser.add_argument("--output-root", required=True, help="Output folder for tar/zip/report.")
    return parser.parse_args()


def today_folders(source_root: Path) -> list[Path]:
    today = datetime.now().date()
    folders = [
        p for p in source_root.iterdir()
        if p.is_dir() and datetime.fromtimestamp(p.stat().st_ctime).date() == today
    ]
    return sorted(folders)


def parse_dataset_name(folder_name: str) -> tuple[str, int, int, int, int, int]:
    cam_match = re.search(r"(\d{2})-CCTV-(\d{2})", folder_name, re.IGNORECASE)
    nums = re.findall(r"\d+", folder_name)
    if not cam_match or len(nums) < 9:
        raise ValueError(f"Cannot parse folder name: {folder_name}")
    cam_key = f"{cam_match.group(1)}cctv{cam_match.group(2)}".lower()
    apc_code = APC_MAP.get(cam_key, f"APC_{cam_key}")
    year = int(nums[2])
    month = int(nums[3])
    day = int(nums[4])
    hour = int(nums[-3])
    minute = int(nums[-2])
    return apc_code, year, month, day, hour, minute


def build_dataset_stem(folder_name: str) -> str:
    apc_code, year, month, day, hour, minute = parse_dataset_name(folder_name)
    return f"{apc_code}_{year % 100:02d}{month:02d}{day:02d}_{hour:02d}{minute:02d}"


def next_unique_path(dst: Path) -> Path:
    if not dst.exists():
        return dst
    stem = dst.stem
    suffix = dst.suffix
    counter = 1
    while True:
        candidate = dst.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def collect_files(src_folder: Path, target_root: Path, sub_name: str, suffixes: set[str]) -> int:
    out_dir = target_root / sub_name
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in src_folder.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in suffixes:
            continue
        destination = next_unique_path(out_dir / path.name)
        shutil.copy2(path, destination)
        count += 1
    return count


def ensure_yaml(target_root: Path) -> bool:
    yaml_path = target_root / "data.yaml"
    if yaml_path.exists():
        return False
    yaml_path.write_text(DEFAULT_DATA_YAML, encoding="utf-8")
    return True


def build_sample_pairs(images_dir: Path, labels_dir: Path, seed_key: str) -> list[dict[str, str | None]]:
    image_files = sorted([p for p in images_dir.glob("*") if p.suffix.lower() in IMAGE_EXTS])
    if not image_files:
        return []
    label_by_stem = {p.stem: p for p in labels_dir.glob("*.txt")}
    sample_count = min(10, max(5, len(image_files)))
    rng = Random(seed_key)
    picked = rng.sample(image_files, min(sample_count, len(image_files)))
    rows: list[dict[str, str | None]] = []
    for image in picked:
        label = label_by_stem.get(image.stem)
        rows.append(
            {
                "image": str(image),
                "label": str(label) if label else None,
            }
        )
    return rows


def write_tar(source_dir: Path, out_path: Path) -> None:
    with tarfile.open(out_path, "w") as tf:
        tf.add(source_dir, arcname=source_dir.name)


def write_zip(source_dir: Path, out_path: Path) -> None:
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in source_dir.rglob("*"):
            if item.is_file():
                zf.write(item, item.relative_to(source_dir).as_posix())


def main() -> int:
    args = parse_args()
    source_root = Path(args.source_root)
    output_root = Path(args.output_root)
    tar_dir = output_root / "tar"
    zip_dir = output_root / "zip"
    flat_dir = output_root / "_flat_sources"
    tar_dir.mkdir(parents=True, exist_ok=True)
    zip_dir.mkdir(parents=True, exist_ok=True)
    flat_dir.mkdir(parents=True, exist_ok=True)

    results: list[PreparedItem] = []
    for folder in today_folders(source_root):
        stem = build_dataset_stem(folder.name)
        target_flat = flat_dir / stem
        if target_flat.exists():
            shutil.rmtree(target_flat)
        target_flat.mkdir(parents=True, exist_ok=True)

        source_images = sum(1 for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
        source_labels = sum(1 for p in folder.rglob("*.txt") if p.is_file())

        packed_images = collect_files(folder, target_flat, "images", IMAGE_EXTS)
        packed_labels = collect_files(folder, target_flat, "labels", {".txt"})
        yaml_added = ensure_yaml(target_flat)

        tar_path = tar_dir / f"{stem}.tar"
        zip_path = zip_dir / f"{stem}.zip"
        write_tar(target_flat, tar_path)
        write_zip(target_flat, zip_path)

        hour = int(stem.split("_")[2][:2])
        period_zh = "白天" if 6 <= hour < 18 else "晚上"
        period_en = "day" if period_zh == "白天" else "night"
        apc_tag = stem.split("_")[0].lower()

        samples = build_sample_pairs(target_flat / "images", target_flat / "labels", stem)
        results.append(
            PreparedItem(
                source_folder=str(folder),
                renamed_stem=stem,
                yaml_added=yaml_added,
                source_images=source_images,
                source_labels=source_labels,
                packed_images=packed_images,
                packed_labels=packed_labels,
                tar_path=str(tar_path),
                zip_path=str(zip_path),
                description=f"{period_zh}，多人，安全帽，腰包，口罩",
                keywords=[apc_tag, period_en, "people", "helmet", "pack", "mask"],
                samples=samples,
            )
        )

    report_path = output_root / "upload_report.json"
    compare_path = output_root / "source_pack_compare.json"
    names_path = output_root / "upload_names.txt"
    report_json = [item.__dict__ for item in results]
    report_path.write_text(json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8")
    compare_rows = [
        {
            "renamed_stem": item.renamed_stem,
            "source_images": item.source_images,
            "packed_images": item.packed_images,
            "source_labels": item.source_labels,
            "packed_labels": item.packed_labels,
            "images_match": item.source_images == item.packed_images,
            "labels_match": item.source_labels == item.packed_labels,
        }
        for item in results
    ]
    compare_path.write_text(json.dumps(compare_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    names_path.write_text("\n".join(item.renamed_stem for item in results), encoding="utf-8")

    print(f"prepared={len(results)}")
    for item in results:
        print(
            f"{item.renamed_stem}: images {item.source_images}->{item.packed_images}, "
            f"labels {item.source_labels}->{item.packed_labels}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
