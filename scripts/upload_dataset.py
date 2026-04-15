from __future__ import annotations

import argparse
import random
import re
import sys
import time
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

try:
    from PIL import Image, ImageStat
except ImportError:
    Image = None
    ImageStat = None


@dataclass(frozen=True)
class Selectors:
    create_button_candidates: tuple[str, ...] = (
        "xpath=//button[contains(normalize-space(.), '建立資料集')]",
        "xpath=//button[contains(normalize-space(.), '新增資料集')]",
        "xpath=//button[contains(normalize-space(.), '創建資料集')]",
        "xpath=//button[contains(normalize-space(.), '建立') and contains(normalize-space(.), '資料集')]",
        "xpath=//button[contains(normalize-space(.), '新增') and contains(normalize-space(.), '資料集')]",
        "xpath=//button[contains(normalize-space(.), '創建') and contains(normalize-space(.), '資料集')]",
        "xpath=//button[contains(normalize-space(.), 'Create') and contains(normalize-space(.), 'Dataset')]",
        "xpath=//button[contains(normalize-space(.), '資料集')]",
        "xpath=//button[contains(normalize-space(.), 'Create Dataset')]",
    )
    name_input: str = "#name"
    description_input: str = "#description"
    tags_input: str = "#tags"
    create_confirm_candidates: tuple[str, ...] = (
        "xpath=//div[contains(@class, 'ant-modal-footer')]//button[contains(@class, 'ant-btn-primary')]",
        "xpath=//div[contains(@class, 'ant-modal-footer')]//button[last()]",
    )
    zip_input_primary: str = "xpath=//input[@type='file' and contains(@accept, '.zip')]"
    zip_input_fallback: str = "xpath=//input[@type='file']"
    upload_list: str = "xpath=//div[contains(@class, 'ant-upload-list')]"
    import_button_candidates: tuple[str, ...] = (
        "xpath=//button[contains(normalize-space(.), '匯入 ZIP 至資料集')]",
        "xpath=//button[contains(normalize-space(.), '匯入 ZIP')]",
        "xpath=//button[contains(normalize-space(.), '導入 ZIP')]",
        "xpath=//button[contains(normalize-space(.), 'ZIP') and contains(normalize-space(.), '資料集')]",
        "xpath=//button[contains(normalize-space(.), 'Import ZIP')]",
    )


@dataclass
class DatasetMetadata:
    dataset_name: str
    description: str
    tags: list[str]
    source_zip: Path
    apc_id: Optional[str] = None
    time_str: Optional[str] = None


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
YAML_FILENAMES = {"data.yaml", "data.yml"}
LABEL_DIR_NAMES = {"labels", "label"}
DESCRIPTION_PRIORITY = ["people", "person", "helmet", "vest", "pack", "backpack", "mask", "bike", "motorcycle", "truck", "car"]
TAG_PRIORITY = ["people", "person", "helmet", "vest", "pack", "backpack", "mask", "bike", "motorcycle", "truck", "car"]
AI_GEN_HINTS = ("gemini", "grok", "synth", "synthetic", "genai", "generative", "diffusion")
LEGACY_HINTS = ("legacy", "old", "migration", "migrate", "historical", "archive")

TAG_HINTS = {
    "helmet": ["helmet", "hardhat", "hard-hat", "safety helmet", "安全帽"],
    "mask": ["mask", "face mask", "口罩"],
    "pack": ["pack", "waistpack", "waist pack", "fannypack", "fanny pack", "腰包"],
    "backpack": ["backpack", "背包"],
    "vest": ["vest", "reflective vest", "反光背心", "背心"],
    "person": ["person", "human", "pedestrian", "人", "人員"],
    "people": ["people", "多人"],
    "bike": ["bike", "bicycle", "腳踏車", "自行車", "單車"],
    "motorcycle": ["motorcycle", "motorbike", "機車"],
    "truck": ["truck", "卡車"],
    "car": ["car", "vehicle", "汽車", "車輛"],
}

DESCRIPTION_MAP = {
    "people": "多人",
    "person": "一人",
    "helmet": "安全帽",
    "mask": "口罩",
    "pack": "腰包",
    "backpack": "背包",
    "vest": "反光背心",
    "bike": "腳踏車",
    "motorcycle": "機車",
    "truck": "卡車",
    "car": "汽車",
}

DAY_TEXT = "白天"
NIGHT_TEXT = "晚上"


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create datasets and upload ZIP archives through Playwright.",
    )
    parser.add_argument("--base-url", required=True, help="Dataset list page URL.")
    parser.add_argument("--source", required=True, help="A single .zip file or a directory containing .zip files.")
    parser.add_argument("--dataset-name", help="Override dataset name for single ZIP mode.")
    parser.add_argument("--description", help="Override description for single ZIP mode.")
    parser.add_argument("--tags", help="Comma-separated tags override for single ZIP mode.")
    parser.add_argument("--browser-channel", default="msedge", help="Chromium channel name. Default: msedge")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode.")
    parser.add_argument("--require-manual-login", action="store_true", help="Pause for manual login.")
    parser.add_argument("--login-url", help="Optional login page URL. Defaults to --base-url.")
    parser.add_argument("--username", help="Login username for automated sign-in.")
    parser.add_argument("--password", help="Login password for automated sign-in.")
    parser.add_argument(
        "--append-test-suffix",
        action="store_true",
        help="Append '_test' to dataset names before upload.",
    )
    parser.add_argument("--post-create-wait-ms", type=int, default=2000)
    parser.add_argument("--post-import-wait-ms", type=int, default=5000)
    parser.add_argument("--screenshot-dir", help="Directory for debug screenshots.")
    parser.add_argument("--keep-debug-screenshots", action="store_true")
    return parser.parse_args()


def normalize_tags(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def looks_garbled_text(text: Optional[str]) -> bool:
    if not text:
        return False
    cleaned = text.strip()
    if not cleaned:
        return False
    if "�" in cleaned:
        return True
    return cleaned.count("?") / max(len(cleaned), 1) >= 0.2


def choose_description(override: Optional[str], inferred: str) -> str:
    if override:
        return inferred if looks_garbled_text(override) else override
    if looks_garbled_text(inferred):
        return "待人工確認"
    return inferred


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


def infer_period_from_time(time_str: Optional[str]) -> Optional[str]:
    if not time_str or len(time_str) < 2 or not time_str[:2].isdigit():
        return None
    hour = int(time_str[:2])
    return DAY_TEXT if 6 <= hour < 18 else NIGHT_TEXT


def normalize_site_tag(apc_id: Optional[str]) -> Optional[str]:
    if not apc_id:
        return None
    normalized = apc_id.strip().lower()
    match = re.match(r"^([a-z]+)", normalized)
    if not match:
        return None
    site_tag = match.group(1)
    return site_tag if len(site_tag) >= 3 else normalized


def has_ai_gen_hint(stem: str) -> bool:
    lowered = stem.lower()
    return any(hint in lowered for hint in AI_GEN_HINTS)


def has_legacy_hint(stem: str) -> bool:
    lowered = stem.lower()
    return any(hint in lowered for hint in LEGACY_HINTS)


def normalize_class_name(raw: str) -> Optional[str]:
    cleaned = raw.strip().strip('"\'').lower()
    if not cleaned:
        return None
    for canonical, hints in TAG_HINTS.items():
        if cleaned == canonical or cleaned in {hint.lower() for hint in hints}:
            return canonical
    return cleaned if len(cleaned) >= 2 else None


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
            if re.match(r"^names\s*:\s*$", stripped, re.IGNORECASE):
                collecting = True
            continue
        if re.match(r"^\S.*:\s*", line):
            break
        list_match = re.match(r"^\s*-\s*(.+?)\s*$", line)
        dict_match = re.match(r"^\s*\d+\s*:\s*(.+?)\s*$", line)
        value = list_match.group(1) if list_match else dict_match.group(1) if dict_match else None
        if not value:
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


def read_zip_text(zip_file: Path, member: str) -> Optional[str]:
    try:
        with zipfile.ZipFile(zip_file, "r") as zf:
            raw = zf.read(member)
    except Exception:
        return None
    for encoding in ("utf-8", "utf-8-sig", "cp950", "big5", "latin-1"):
        try:
            return raw.decode(encoding, errors="ignore")
        except Exception:
            continue
    return None


def read_zip_bytes(zip_file: Path, member: str) -> Optional[bytes]:
    try:
        with zipfile.ZipFile(zip_file, "r") as zf:
            return zf.read(member)
    except Exception:
        return None


def inspect_zip_source(zip_file: Path) -> tuple[list[str], list[Counter[int]], list[str]]:
    image_paths: list[str] = []
    label_hits_per_file: list[Counter[int]] = []
    yaml_names: list[str] = []
    with zipfile.ZipFile(zip_file, "r") as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            path = Path(name)
            suffix = path.suffix.lower()
            if suffix in IMAGE_EXTS:
                image_paths.append(path.as_posix())
                continue
            if path.name.lower() in YAML_FILENAMES:
                text = read_zip_text(zip_file, name)
                if text:
                    yaml_names = parse_yaml_names(text) or yaml_names
                continue
            if suffix == ".txt" and any(part.lower() in LABEL_DIR_NAMES for part in path.parts[:-1]):
                text = read_zip_text(zip_file, name)
                if text:
                    label_hits_per_file.append(extract_label_ids(text))
    return image_paths, label_hits_per_file, yaml_names


def derive_subject_count_tag(label_entry_id_hits: list[Counter[int]], yaml_names: list[str]) -> Optional[str]:
    if not yaml_names:
        return None
    try:
        person_index = yaml_names.index("person")
    except ValueError:
        return None
    max_people = 0
    for entry_hits in label_entry_id_hits:
        max_people = max(max_people, entry_hits.get(person_index, 0))
    if max_people >= 2:
        return "people"
    if max_people == 1:
        return "person"
    return None


def build_observed_tags(label_entry_id_hits: list[Counter[int]], yaml_names: list[str]) -> list[str]:
    class_hits: Counter[str] = Counter()
    for entry_hits in label_entry_id_hits:
        for class_id, count in entry_hits.items():
            if 0 <= class_id < len(yaml_names):
                class_hits[yaml_names[class_id]] += count
    observed_tags = [tag for tag in TAG_PRIORITY if class_hits.get(tag)]
    subject_count_tag = derive_subject_count_tag(label_entry_id_hits, yaml_names)
    if subject_count_tag:
        observed_tags = [tag for tag in observed_tags if tag not in {"person", "people"}]
        observed_tags.insert(0, subject_count_tag)
    return list(dict.fromkeys(observed_tags))


def infer_periods_from_sample_images(zip_file: Path, image_paths: list[str], stem: str) -> list[str]:
    if not image_paths or Image is None or ImageStat is None:
        return []
    sampled_paths = random.Random(stem).sample(image_paths, min(2, len(image_paths)))
    periods: list[str] = []
    for image_path in sampled_paths:
        raw = read_zip_bytes(zip_file, image_path)
        if not raw:
            continue
        try:
            with Image.open(BytesIO(raw)) as image:
                rgb_image = image.convert("RGB")
                stat = ImageStat.Stat(rgb_image)
                mean_brightness = sum(stat.mean) / len(stat.mean)
                periods.append(DAY_TEXT if mean_brightness >= 110 else NIGHT_TEXT)
        except Exception:
            continue
    return list(dict.fromkeys(periods))


def build_description(periods: list[str], observed_tags: list[str]) -> str:
    description_tokens: list[str] = []
    description_tokens.extend(periods)
    for tag in DESCRIPTION_PRIORITY:
        if tag in observed_tags and tag in DESCRIPTION_MAP:
            description_tokens.append(DESCRIPTION_MAP[tag])
    if not description_tokens:
        return "待人工確認"
    return "，".join(dict.fromkeys(description_tokens))


def build_tags(stem: str, apc_id: Optional[str], periods: list[str], observed_tags: list[str]) -> list[str]:
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
    for tag in TAG_PRIORITY:
        if tag in observed_tags:
            tags.append(tag)
    if has_legacy_hint(stem):
        tags.append("legacy")
    return list(dict.fromkeys(tags))


def infer_metadata_from_stem(stem: str, source_zip: Path) -> DatasetMetadata:
    apc_id, _, time_str = infer_tokens_from_name(stem)
    image_paths, label_entry_id_hits, yaml_names = inspect_zip_source(source_zip)
    observed_tags = build_observed_tags(label_entry_id_hits, yaml_names)

    periods: list[str] = []
    period_from_name = infer_period_from_time(time_str)
    if period_from_name:
        periods.append(period_from_name)
    elif has_ai_gen_hint(stem):
        periods.extend(infer_periods_from_sample_images(source_zip, image_paths, stem))

    periods = list(dict.fromkeys(periods))
    description = choose_description(None, build_description(periods, observed_tags))
    tags = build_tags(stem, apc_id, periods, observed_tags)

    return DatasetMetadata(
        dataset_name=stem,
        description=description,
        tags=tags,
        source_zip=source_zip,
        apc_id=apc_id,
        time_str=time_str,
    )


def build_metadata_list(args: argparse.Namespace) -> list[DatasetMetadata]:
    source_path = Path(args.source)
    if not source_path.exists():
        raise FileNotFoundError(f"Cannot find --source path: {source_path}")

    if source_path.is_file():
        zip_files = [source_path]
    else:
        zip_files = sorted(source_path.glob("*.zip"))

    if not zip_files:
        raise FileNotFoundError(f"No .zip files found under {source_path}")

    if len(zip_files) > 1 and any([args.dataset_name, args.description, args.tags]):
        raise ValueError("When --source is a directory, do not use --dataset-name/--description/--tags overrides.")

    metadata_items: list[DatasetMetadata] = []
    for zip_file in zip_files:
        inferred = infer_metadata_from_stem(zip_file.stem, zip_file)
        if len(zip_files) == 1:
            inferred.dataset_name = args.dataset_name or inferred.dataset_name
            inferred.description = choose_description(args.description, inferred.description)
            override_tags = normalize_tags(args.tags)
            inferred.tags = override_tags or inferred.tags
        if args.append_test_suffix and not inferred.dataset_name.endswith("_test"):
            inferred.dataset_name = f"{inferred.dataset_name}_test"
        metadata_items.append(inferred)

    return metadata_items


def save_debug_screenshot(page: Page, screenshot_paths: list[Path], screenshot_path: Path) -> None:
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshot_path), full_page=True)
    screenshot_paths.append(screenshot_path)
    log(f"[debug] saved screenshot: {screenshot_path}")


def cleanup_debug_screenshots(screenshot_paths: Iterable[Path]) -> None:
    for shot_path in screenshot_paths:
        try:
            if shot_path.exists():
                shot_path.unlink()
        except Exception:
            pass


def wait_until_button_enabled(button: Locator, timeout_seconds: int = 15) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        disabled = button.get_attribute("disabled")
        if disabled is None or disabled == "false":
            return
        button.page.wait_for_timeout(500)
    raise TimeoutError(f"button not enabled within {timeout_seconds}s")


def wait_for_manual_login_if_needed(page: Page, require_manual_login: bool) -> None:
    if not require_manual_login:
        return
    log("頁面已開啟。請先在瀏覽器完成手動登入；登入完成後回到終端機按 Enter 繼續。")
    try:
        input()
        page.wait_for_timeout(500)
        return
    except EOFError:
        log("[info] 目前環境無法接收 Enter，改為被動等待你完成登入（不會自動點擊頁面）。")

    for _ in range(600):
        try:
            project_menu = page.locator("xpath=//span[normalize-space()='專案']").first
            if project_menu.count() > 0 and project_menu.is_visible():
                page.wait_for_timeout(500)
                return
        except Exception:
            pass
        page.wait_for_timeout(1000)
    raise TimeoutError("等待手動登入逾時，請確認是否已登入並停留在系統內頁。")


def login_with_credentials_if_provided(
    page: Page,
    username: Optional[str],
    password: Optional[str],
) -> bool:
    if not username or not password:
        return False

    user_candidates = (
        "xpath=//input[@name='username']",
        "xpath=//input[@id='username']",
        "xpath=//input[contains(@placeholder, '帳號')]",
        "xpath=//input[contains(@placeholder, '使用者')]",
        "xpath=//input[@type='email']",
        "xpath=//input[@type='text']",
    )
    pass_candidates = (
        "xpath=//input[@name='password']",
        "xpath=//input[@id='password']",
        "xpath=//input[contains(@placeholder, '密碼')]",
        "xpath=//input[@type='password']",
    )
    submit_candidates = (
        "xpath=//button[@type='submit']",
        "xpath=//button[contains(normalize-space(.), '登入')]",
        "xpath=//button[contains(normalize-space(.), 'Login')]",
        "xpath=//button[contains(normalize-space(.), 'Sign in')]",
    )

    def _first_visible(selectors: Iterable[str]) -> Optional[Locator]:
        for selector in selectors:
            loc = page.locator(selector)
            try:
                for idx in range(loc.count()):
                    item = loc.nth(idx)
                    if item.is_visible():
                        return item
            except Exception:
                continue
        return None

    user_input = _first_visible(user_candidates)
    pass_input = _first_visible(pass_candidates)
    if user_input is None or pass_input is None:
        raise RuntimeError("找不到登入欄位，請檢查登入頁面是否變更。")

    user_input.fill(username)
    pass_input.fill(password)
    submit = _first_visible(submit_candidates)
    if submit is not None:
        submit.click()
    else:
        pass_input.press("Enter")

    for _ in range(120):
        try:
            project_menu = page.locator("xpath=//span[normalize-space()='專案']").first
            if project_menu.count() > 0 and project_menu.is_visible():
                page.wait_for_timeout(400)
                return True
        except Exception:
            pass
        page.wait_for_timeout(500)
    raise TimeoutError("自動登入逾時，請確認帳密與登入頁面。")


def ensure_project_page(page: Page, base_url: str) -> None:
    target_path = urlparse(base_url).path.rstrip("/")
    current_path = urlparse(page.url).path.rstrip("/")
    if current_path == target_path:
        return

    project_path_match = re.search(r"(/projects/\d+)", base_url)
    project_path = project_path_match.group(1) if project_path_match else target_path

    project_menu_candidates = (
        "xpath=//li[@role='menuitem'][.//span[normalize-space()='專案']]",
        "xpath=//*[contains(@class, 'ant-menu-item')][.//span[normalize-space()='專案']]",
        "xpath=//span[normalize-space()='專案']/ancestor::*[@role='menuitem' or contains(@class, 'ant-menu-item')][1]",
    )
    project_link_candidates = (
        f"xpath=//a[@href='{project_path}']",
        f"xpath=//a[contains(@href, '{project_path}')]",
    )

    for selector in project_menu_candidates:
        candidate = page.locator(selector).first
        try:
            if candidate.count() > 0 and candidate.is_visible():
                candidate.click()
                page.wait_for_timeout(800)
                break
        except Exception:
            continue

    for selector in project_link_candidates:
        candidate = page.locator(selector).first
        try:
            if candidate.count() > 0 and candidate.is_visible():
                candidate.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(800)
                break
        except Exception:
            continue

    current_path = urlparse(page.url).path.rstrip("/")
    if current_path != target_path:
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(800)


def find_first_visible(page: Page, selectors: Iterable[str]) -> Locator:
    for selector in selectors:
        loc = page.locator(selector)
        try:
            count = loc.count()
        except Exception:
            continue
        for idx in range(count):
            candidate = loc.nth(idx)
            try:
                if candidate.is_visible():
                    return candidate
            except Exception:
                continue
    raise RuntimeError(f"No visible element for selectors: {list(selectors)}")


def create_dataset(page: Page, selectors: Selectors, meta: DatasetMetadata, wait_ms: int) -> None:
    log(f"[create] {meta.dataset_name}")
    create_button = find_first_visible(page, selectors.create_button_candidates)
    create_button.click()
    page.wait_for_timeout(700)

    page.fill(selectors.name_input, meta.dataset_name)
    page.fill(selectors.description_input, meta.description)
    page.fill(selectors.tags_input, ", ".join(meta.tags))

    confirm_button = find_first_visible(page, selectors.create_confirm_candidates)
    wait_until_button_enabled(confirm_button, timeout_seconds=10)
    confirm_button.click()
    page.wait_for_timeout(wait_ms)


def dataset_entry_locator(page: Page, dataset_name: str) -> str:
    exact = f"xpath=//a[normalize-space()='{dataset_name}']"
    if page.locator(exact).count() > 0:
        return exact
    return f"xpath=//a[contains(normalize-space(), '{dataset_name}')]"


def select_dataset(page: Page, dataset_name: str) -> None:
    locator = dataset_entry_locator(page, dataset_name)
    page.wait_for_selector(locator, state="visible", timeout=15000)
    page.click(locator)
    page.wait_for_timeout(1200)
    log(f"[select] {dataset_name}")


def set_zip_file(page: Page, selectors: Selectors, file_path: Path) -> None:
    zip_input = page.locator(selectors.zip_input_primary).first
    if zip_input.count() == 0:
        zip_input = page.locator(selectors.zip_input_fallback).first
    if zip_input.count() == 0:
        raise RuntimeError("Cannot find ZIP file input element.")
    zip_input.set_input_files(str(file_path))
    page.wait_for_selector(selectors.upload_list, state="attached", timeout=15000)
    log(f"[upload] selected ZIP: {file_path.name}")


def trigger_import(page: Page, selectors: Selectors, wait_ms: int) -> None:
    import_button = find_first_visible(page, selectors.import_button_candidates)
    wait_until_button_enabled(import_button, timeout_seconds=15)
    import_button.click()
    log("[upload] import clicked")
    page.wait_for_timeout(wait_ms)


def upload_single_dataset(page: Page, selectors: Selectors, meta: DatasetMetadata, args: argparse.Namespace) -> None:
    screenshot_paths: list[Path] = []
    screenshot_dir = Path(args.screenshot_dir) if args.screenshot_dir else None

    create_dataset(page, selectors, meta, args.post_create_wait_ms)
    if screenshot_dir:
        save_debug_screenshot(page, screenshot_paths, screenshot_dir / f"before_select_{meta.dataset_name}.png")

    select_dataset(page, meta.dataset_name)
    if screenshot_dir:
        save_debug_screenshot(page, screenshot_paths, screenshot_dir / f"after_select_{meta.dataset_name}.png")

    set_zip_file(page, selectors, meta.source_zip)
    if screenshot_dir:
        save_debug_screenshot(page, screenshot_paths, screenshot_dir / f"after_zip_select_{meta.dataset_name}.png")

    trigger_import(page, selectors, args.post_import_wait_ms)
    if screenshot_dir:
        save_debug_screenshot(page, screenshot_paths, screenshot_dir / f"after_import_click_{meta.dataset_name}.png")

    page.goto(args.base_url)
    page.wait_for_timeout(2000)
    ensure_project_page(page, args.base_url)

    if screenshot_dir and not args.keep_debug_screenshots:
        cleanup_debug_screenshots(screenshot_paths)


def main() -> int:
    args = parse_args()
    selectors = Selectors()
    metadata_items = build_metadata_list(args)

    log("[info] upload plan")
    for meta in metadata_items:
        log(f"  - {meta.dataset_name} <- {meta.source_zip.name}")
        log(f"    description: {meta.description}")
        log(f"    tags: {', '.join(meta.tags)}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.browser_channel, headless=args.headless)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(args.login_url or args.base_url)
            if args.username and args.password:
                login_with_credentials_if_provided(page, args.username, args.password)
            else:
                wait_for_manual_login_if_needed(page, args.require_manual_login)
            ensure_project_page(page, args.base_url)
            for meta in metadata_items:
                upload_single_dataset(page, selectors, meta, args)
            log("[done] all datasets uploaded")
            return 0
        except PlaywrightTimeoutError as exc:
            log(f"[error] Playwright timeout: {exc}")
            return 1
        except Exception as exc:
            log(f"[error] {exc}")
            return 1
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
