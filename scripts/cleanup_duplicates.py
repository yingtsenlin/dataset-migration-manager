from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


TIME_PATTERNS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
]


@dataclass(frozen=True)
class Selectors:
    dataset_anchor_by_name_tpl: str = "xpath=//a[normalize-space()='{name}']"
    delete_button_candidates: tuple[str, ...] = (
        "xpath=//span[normalize-space()='刪除']",
        "xpath=//*[self::span or self::button or @role='button'][normalize-space()='刪除']",
        "xpath=//button[contains(normalize-space(.), '刪除')]",
        "xpath=//button[contains(., 'Delete')]",
    )
    confirm_delete_candidates: tuple[str, ...] = (
        "xpath=//div[contains(@class, 'ant-popconfirm')]//button[.//span[normalize-space()='確 定'] or normalize-space()='確 定']",
        "xpath=//div[contains(@class, 'ant-popconfirm')]//button[.//span[normalize-space()='確定'] or normalize-space()='確定']",
        "xpath=//div[contains(@class, 'ant-popconfirm')]//button[contains(., 'Delete')]",
        "xpath=//div[contains(@class, 'ant-modal')]//button[.//span[normalize-space()='確 定'] or normalize-space()='確 定']",
    )


@dataclass
class DatasetCard:
    dataset_name: str
    card_locator: Locator
    entry_locator: Locator
    card_text: str
    created_at: Optional[datetime]
    created_at_raw: Optional[str]
    detection_reason: str


@dataclass
class CleanupDecision:
    keep: DatasetCard
    delete: list[DatasetCard]
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find duplicate datasets by exact name and optionally delete older copies.",
    )
    parser.add_argument("--base-url", required=True, help="Dataset list page URL.")
    parser.add_argument("--dataset-name", required=True, help="Exact dataset name to match.")
    parser.add_argument(
        "--mode",
        choices=["report", "apply"],
        default="report",
        help="report: only print decision, apply: delete older duplicates.",
    )
    parser.add_argument(
        "--browser-channel",
        default="msedge",
        help="Chromium channel name. Default: msedge",
    )
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode.")
    parser.add_argument(
        "--require-manual-login",
        action="store_true",
        help="Pause after opening the page and wait for Enter so you can log in manually.",
    )
    parser.add_argument(
        "--assume-ui-sorted-newest-first",
        action="store_true",
        default=True,
        help="Use top-to-bottom UI order as fallback. Default: enabled because the current page is time-sorted.",
    )
    parser.add_argument(
        "--screenshot-dir",
        help="Optional directory for before/after delete screenshots.",
    )
    return parser.parse_args()


def wait_for_manual_login_if_needed(page: Page, require_manual_login: bool) -> None:
    if not require_manual_login:
        return
    print("頁面已開啟。完成手動登入後，回到終端機按 Enter 繼續。")
    input()
    page.wait_for_timeout(500)


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


def extract_created_time(text: str) -> tuple[Optional[datetime], Optional[str]]:
    patterns = [
        r"(?:建立時間|创建时间|created\s*at|created)[:：\s]*([0-9]{4}[/-][0-9]{1,2}[/-][0-9]{1,2}(?:\s+[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)?)",
        r"([0-9]{4}[/-][0-9]{1,2}[/-][0-9]{1,2}(?:\s+[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        raw = match.group(1).strip()
        for fmt in TIME_PATTERNS:
            try:
                return datetime.strptime(raw, fmt), raw
            except ValueError:
                pass
    return None, None


def candidate_card_locators(entry: Locator) -> list[Locator]:
    return [
        entry.locator(
            "xpath=ancestor::*[contains(@class, 'ant-list-item') or contains(@class, 'card') or contains(@class, 'row')][1]"
        ),
        entry.locator("xpath=ancestor::li[1]"),
        entry.locator("xpath=ancestor::div[1]"),
        entry.locator("xpath=ancestor::div[2]"),
        entry.locator("xpath=ancestor::div[3]"),
        entry.locator("xpath=ancestor::div[4]"),
        entry.locator("xpath=ancestor::div[5]"),
        entry.locator("xpath=ancestor::div[6]"),
    ]


def choose_card_locator(entry: Locator) -> Locator:
    best_locator = entry
    best_text_len = -1
    for candidate in candidate_card_locators(entry):
        try:
            if candidate.count() == 0:
                continue
            text = candidate.first.inner_text(timeout=1000).strip()
            if len(text) > best_text_len:
                best_locator = candidate.first
                best_text_len = len(text)
        except Exception:
            continue
    return best_locator


def collect_duplicate_cards(page: Page, dataset_name: str, selectors: Selectors) -> list[DatasetCard]:
    anchor_selector = selectors.dataset_anchor_by_name_tpl.format(name=dataset_name)
    anchors = page.locator(anchor_selector)
    cards: list[DatasetCard] = []

    for idx in range(anchors.count()):
        entry = anchors.nth(idx)
        card = choose_card_locator(entry)
        text = card.inner_text().strip()
        created_at, raw = extract_created_time(text)
        reason = "timestamp visible in card" if created_at else "fallback to current UI order"
        cards.append(
            DatasetCard(
                dataset_name=dataset_name,
                card_locator=card,
                entry_locator=entry,
                card_text=text,
                created_at=created_at,
                created_at_raw=raw,
                detection_reason=reason,
            )
        )
    return cards


def decide_cleanup(cards: list[DatasetCard], assume_ui_sorted_newest_first: bool) -> CleanupDecision:
    if len(cards) < 2:
        raise ValueError("找不到兩筆以上同名資料集，無法進行重複刪除判斷。")

    cards_with_time = [card for card in cards if card.created_at is not None]
    if len(cards_with_time) == len(cards):
        ordered = sorted(cards, key=lambda item: item.created_at or datetime.min, reverse=True)
        return CleanupDecision(
            keep=ordered[0],
            delete=ordered[1:],
            reason="keep newest dataset by parsed created_at timestamp",
        )

    if assume_ui_sorted_newest_first:
        return CleanupDecision(
            keep=cards[0],
            delete=cards[1:],
            reason="timestamps missing; keep top item because current UI is sorted newest first",
        )

    raise ValueError("建立時間不可用，而且未啟用 UI 排序 fallback，無法安全決定保留項目。")


def save_screenshot(page: Page, screenshot_dir: Optional[Path], name: str) -> None:
    if not screenshot_dir:
        return
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    target = screenshot_dir / name
    page.screenshot(path=str(target), full_page=True)
    print(f"[debug] 已儲存截圖: {target}")


def find_first_visible(locator_root: Locator, candidates: Iterable[str]) -> Locator:
    for selector in candidates:
        scoped = locator_root.locator(selector)
        try:
            count = scoped.count()
        except Exception:
            continue
        for idx in range(count):
            candidate = scoped.nth(idx)
            try:
                if candidate.is_visible():
                    return candidate
            except Exception:
                continue
    raise RuntimeError(f"找不到可見的按鈕，候選 selector: {list(candidates)}")


def find_delete_button_for_card(page: Page, card: DatasetCard, selectors: Selectors) -> Locator:
    container_candidates = [
        card.card_locator,
        card.entry_locator.locator("xpath=ancestor::div[1]"),
        card.entry_locator.locator("xpath=ancestor::div[2]"),
        card.entry_locator.locator("xpath=ancestor::div[3]"),
        card.entry_locator.locator("xpath=ancestor::div[4]"),
        card.entry_locator.locator("xpath=ancestor::div[5]"),
        page.locator(
            f"xpath=//*[.//a[normalize-space()='{card.dataset_name}'] and .//*[normalize-space()='刪除']][1]"
        ),
    ]

    for container in container_candidates:
        try:
            return find_first_visible(container, selectors.delete_button_candidates)
        except Exception:
            continue

    raise RuntimeError(f"找不到資料集 `{card.dataset_name}` 對應列內的刪除按鈕。")


def delete_dataset(page: Page, card: DatasetCard, selectors: Selectors, screenshot_dir: Optional[Path]) -> None:
    print(f"[delete] 準備刪除: {card.dataset_name}")
    save_screenshot(page, screenshot_dir, f"before_delete_{card.dataset_name}.png")

    delete_button = find_delete_button_for_card(page, card, selectors)
    delete_button.click()
    page.wait_for_timeout(800)
    save_screenshot(page, screenshot_dir, f"after_delete_click_{card.dataset_name}.png")

    confirm_button = find_first_visible(page.locator("body"), selectors.confirm_delete_candidates)
    confirm_button.click()
    page.wait_for_timeout(1500)
    save_screenshot(page, screenshot_dir, f"after_delete_confirm_{card.dataset_name}.png")


def print_report(cards: list[DatasetCard], decision: Optional[CleanupDecision]) -> None:
    print("=" * 72)
    print("同名資料集檢查結果")
    for idx, card in enumerate(cards, start=1):
        created_text = card.created_at_raw or "<未解析到建立時間>"
        preview = " ".join(card.card_text.split())[:180]
        print(f"[{idx}] created_at={created_text}")
        print(f"    reason={card.detection_reason}")
        print(f"    text={preview}")
    if decision:
        print("-" * 72)
        print(f"保留: {decision.keep.created_at_raw or '<依 UI 排序判斷>'}")
        print(f"原因: {decision.reason}")
        print(f"刪除筆數: {len(decision.delete)}")
    print("=" * 72)


def main() -> int:
    args = parse_args()
    selectors = Selectors()
    screenshot_dir = Path(args.screenshot_dir) if args.screenshot_dir else None

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.browser_channel, headless=args.headless)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(args.base_url)
            wait_for_manual_login_if_needed(page, args.require_manual_login)
            ensure_project_page(page, args.base_url)
            cards = collect_duplicate_cards(page, args.dataset_name, selectors)
            if len(cards) < 2:
                print("找不到兩筆以上同名資料集，無需執行刪除。")
                return 0

            decision = decide_cleanup(cards, args.assume_ui_sorted_newest_first)
            print_report(cards, decision)

            if args.mode == "report":
                return 0

            for delete_target in decision.delete:
                page.goto(args.base_url)
                page.wait_for_timeout(1500)
                ensure_project_page(page, args.base_url)
                current_cards = collect_duplicate_cards(page, args.dataset_name, selectors)
                refreshed_decision = decide_cleanup(current_cards, args.assume_ui_sorted_newest_first)
                delete_target = refreshed_decision.delete[0]
                delete_dataset(page, delete_target, selectors, screenshot_dir)
                page.goto(args.base_url)
                page.wait_for_timeout(1500)

            print("[done] 同名舊資料集刪除完成。")
            return 0
        except PlaywrightTimeoutError as exc:
            print(f"[error] Playwright timeout: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 1
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
