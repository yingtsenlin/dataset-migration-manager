from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from types import SimpleNamespace

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from find_datasets_by_creator_status import (
    MatchRow,
    collect_matches,
    ensure_project_page as ensure_project_page_for_query,
    status_aliases,
    wait_for_manual_login_if_needed as wait_login_for_query,
)
from upload_dataset import (
    Selectors as UploadSelectors,
    ensure_project_page as ensure_project_page_for_upload,
    infer_metadata_from_stem,
    upload_single_dataset,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find datasets by creator/status, delete them, then re-upload from matching ZIP files.",
    )
    parser.add_argument("--base-url", required=True, help="Project dataset list URL.")
    parser.add_argument("--source-dir", required=True, help="Directory containing source ZIP files.")
    parser.add_argument("--creator", required=True, help="Creator name to match.")
    parser.add_argument("--status", required=True, help="Status text to match.")
    parser.add_argument("--strict-status", action="store_true", help="Disable status alias matching.")
    parser.add_argument("--browser-channel", default="msedge")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--require-manual-login", action="store_true")
    parser.add_argument("--post-create-wait-ms", type=int, default=1800)
    parser.add_argument("--post-import-wait-ms", type=int, default=4500)
    parser.add_argument("--screenshot-dir", default="debug_shots")
    parser.add_argument("--keep-debug-screenshots", action="store_true")
    return parser.parse_args()


def href_to_dataset_id(href: str) -> str:
    match = re.search(r"/datasets/(\d+)", href or "")
    return match.group(1) if match else ""


def delete_card_by_href(page: Page, href: str, dataset_name: str, screenshot_dir: Path) -> bool:
    # Scope to a specific dataset card by href for precise deletion.
    container_candidates = [
        page.locator(f"xpath=(//*[.//a[@href='{href}'] and .//*[normalize-space()='刪除']])[1]"),
        page.locator(f"xpath=(//*[.//a[contains(@href, '{href}') ] and .//*[normalize-space()='刪除']])[1]"),
    ]

    card = None
    for candidate in container_candidates:
        try:
            if candidate.count() > 0 and candidate.first.is_visible():
                card = candidate.first
                break
        except Exception:
            continue
    if card is None:
        return False

    screenshot_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshot_dir / f"before_delete_{dataset_name}.png"), full_page=True)

    delete_button = card.locator("xpath=.//span[normalize-space()='刪除']").first
    if delete_button.count() == 0 or not delete_button.is_visible():
        return False
    delete_button.click()
    page.wait_for_timeout(500)
    page.screenshot(path=str(screenshot_dir / f"after_delete_click_{dataset_name}.png"), full_page=True)

    confirm_candidates = [
        "xpath=//div[contains(@class, 'ant-popconfirm')]//button[.//span[normalize-space()='確 定'] or normalize-space()='確 定']",
        "xpath=//div[contains(@class, 'ant-popconfirm')]//button[.//span[normalize-space()='確定'] or normalize-space()='確定']",
        "xpath=//div[contains(@class, 'ant-popconfirm')]//button[contains(@class, 'ant-btn-primary')]",
        "xpath=//div[contains(@class, 'ant-modal')]//button[contains(@class, 'ant-btn-primary')]",
    ]
    confirm = None
    for selector in confirm_candidates:
        loc = page.locator(selector)
        try:
            for i in range(loc.count()):
                btn = loc.nth(i)
                if btn.is_visible():
                    confirm = btn
                    break
        except Exception:
            continue
        if confirm is not None:
            break
    if confirm is None:
        return False

    confirm.click()
    page.wait_for_timeout(900)
    page.screenshot(path=str(screenshot_dir / f"after_delete_confirm_{dataset_name}.png"), full_page=True)
    return True


def main() -> int:
    args = parse_args()
    source_dir = Path(args.source_dir)
    if not source_dir.exists():
        print(f"[error] source-dir not found: {source_dir}", file=sys.stderr)
        return 1

    statuses = status_aliases(args.status, args.strict_status)
    upload_args = SimpleNamespace(
        base_url=args.base_url,
        screenshot_dir=args.screenshot_dir,
        keep_debug_screenshots=args.keep_debug_screenshots,
        post_create_wait_ms=args.post_create_wait_ms,
        post_import_wait_ms=args.post_import_wait_ms,
    )
    upload_selectors = UploadSelectors()
    screenshot_dir = Path(args.screenshot_dir)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.browser_channel, headless=args.headless)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(args.base_url)
            wait_login_for_query(page, args.require_manual_login)
            ensure_project_page_for_query(page, args.base_url)

            # Step 1: find target rows
            matches: list[MatchRow] = collect_matches(page, args.creator, statuses)
            if not matches:
                print("[info] no matched datasets to process")
                return 0

            print(f"[info] matched={len(matches)} (creator={args.creator}, statuses={statuses})")
            for row in matches:
                print(f"  - {row.name} | {row.status} | {row.href}")

            # Step 2: delete matched rows (single pass from bottom to top by dataset id)
            rows_sorted = sorted(matches, key=lambda r: int(href_to_dataset_id(r.href) or "0"), reverse=True)
            deleted: list[MatchRow] = []
            failed_delete: list[MatchRow] = []

            for row in rows_sorted:
                ensure_project_page_for_query(page, args.base_url)
                ok = delete_card_by_href(page, row.href, row.name, screenshot_dir)
                if ok:
                    deleted.append(row)
                    print(f"[delete] ok: {row.name} ({row.href})")
                else:
                    failed_delete.append(row)
                    print(f"[delete] failed: {row.name} ({row.href})")
                page.wait_for_timeout(300)

            # Step 3: map deleted datasets to ZIP files
            upload_targets = []
            missing_zip = []
            for row in deleted:
                zip_path = source_dir / f"{row.name}.zip"
                if zip_path.exists():
                    meta = infer_metadata_from_stem(zip_path.stem, zip_path)
                    meta.dataset_name = zip_path.stem
                    upload_targets.append(meta)
                else:
                    missing_zip.append(row.name)

            # Step 4: re-upload
            uploaded = []
            failed_upload = []
            for meta in upload_targets:
                try:
                    ensure_project_page_for_upload(page, args.base_url)
                    upload_single_dataset(page, upload_selectors, meta, upload_args)
                    uploaded.append(meta.dataset_name)
                    print(f"[upload] ok: {meta.dataset_name}")
                except Exception as exc:
                    failed_upload.append((meta.dataset_name, str(exc)))
                    print(f"[upload] failed: {meta.dataset_name} | {exc}")

            # Step 5: summary
            print("\n[summary]")
            print(f"matched={len(matches)}")
            print(f"deleted_ok={len(deleted)}")
            print(f"delete_failed={len(failed_delete)}")
            print(f"zip_missing={len(missing_zip)}")
            print(f"upload_ok={len(uploaded)}")
            print(f"upload_failed={len(failed_upload)}")
            if missing_zip:
                print("[missing_zip_names]")
                for name in missing_zip:
                    print(f"- {name}")
            if failed_delete:
                print("[failed_delete]")
                for row in failed_delete:
                    print(f"- {row.name} | {row.href}")
            if failed_upload:
                print("[failed_upload]")
                for name, err in failed_upload:
                    print(f"- {name} | {err}")

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
