from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from name_standardization import standardize_dataset_filename


DEFAULT_DATA_YAML = """names:
- person
- pack
- helmet
- mask
nc: 4
train: ../train/images
val: ../valid/images
"""


@dataclass
class PrepareResult:
    source: str
    output: str
    renamed: bool
    data_yaml_added: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rename dataset ZIPs with standard naming and ensure data.yaml exists.",
    )
    parser.add_argument("--source", required=True, help="Source directory containing ZIP files.")
    parser.add_argument("--output", required=True, help="Target directory for processed ZIP files.")
    parser.add_argument("--recursive", action="store_true", help="Recursively scan ZIP files under --source.")
    parser.add_argument("--print-json", action="store_true", help="Print machine-readable JSON summary.")
    return parser.parse_args()


def has_data_yaml(zip_file: ZipFile) -> bool:
    for name in zip_file.namelist():
        base = Path(name).name.lower()
        if base in {"data.yaml", "data.yml"}:
            return True
    return False


def process_one_zip(src_zip: Path, dst_zip: Path) -> PrepareResult:
    dst_zip.parent.mkdir(parents=True, exist_ok=True)
    data_yaml_added = False

    with ZipFile(src_zip, "r") as source, ZipFile(dst_zip, "w", compression=ZIP_DEFLATED) as target:
        for item in source.infolist():
            target.writestr(item, source.read(item.filename))

        if not has_data_yaml(source):
            target.writestr("data.yaml", DEFAULT_DATA_YAML)
            data_yaml_added = True

    return PrepareResult(
        source=str(src_zip),
        output=str(dst_zip),
        renamed=(src_zip.name != dst_zip.name),
        data_yaml_added=data_yaml_added,
    )


def resolve_output_path(output_dir: Path, desired_name: str) -> Path:
    candidate = output_dir / desired_name
    if not candidate.exists():
        return candidate

    stem = Path(desired_name).stem
    suffix = Path(desired_name).suffix
    counter = 1
    while True:
        fallback = output_dir / f"{stem}_{counter}{suffix}"
        if not fallback.exists():
            return fallback
        counter += 1


def main() -> int:
    args = parse_args()
    source_dir = Path(args.source)
    output_dir = Path(args.output)

    if not source_dir.exists() or not source_dir.is_dir():
        raise NotADirectoryError(f"Invalid --source directory: {source_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    finder = source_dir.rglob("*.zip") if args.recursive else source_dir.glob("*.zip")
    zip_files = sorted(item for item in finder if item.is_file())
    if not zip_files:
        raise FileNotFoundError(f"No ZIP files found under {source_dir}")

    results: list[PrepareResult] = []
    for src_zip in zip_files:
        dst_name = standardize_dataset_filename(src_zip.name)
        dst_zip = resolve_output_path(output_dir, dst_name)
        results.append(process_one_zip(src_zip, dst_zip))

    if args.print_json:
        print(json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2))
        return 0

    print(f"Processed ZIP files: {len(results)}")
    renamed_count = sum(1 for item in results if item.renamed)
    yaml_added_count = sum(1 for item in results if item.data_yaml_added)
    print(f"Renamed: {renamed_count}, data.yaml added: {yaml_added_count}")
    for item in results:
        print(f"- {Path(item.source).name} -> {Path(item.output).name}")
        print(f"  renamed: {item.renamed}, data.yaml_added: {item.data_yaml_added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
