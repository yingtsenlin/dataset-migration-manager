from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete datasets by dataset IDs or hrefs from project list page.",
    )
    parser.add_argument("--base-url", required=True, help="Project dataset list URL.")
    parser.add_argument("--from-find-json", default="artifacts/find_result.json", help="Path to JSON from find script.")
    parser.add_argument("--dataset-id", action="append", default=[], help="Dataset ID to delete. Can be repeated.")
    parser.add_argument("--href", action="append", default=[], help="Dataset href to delete. Can be repeated.")
    parser.add_argument("--delete-old-only", action="store_true", help="Keep newest ID per exact name and delete only older ones.")
    parser.add_argument("--browser-channel", default="msedge")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--require-manual-login", action="store_true")
    parser.add_argument("--login-url", help="Optional login page URL. Defaults to --base-url.")
    parser.add_argument("--username", help="Login username for automated sign-in.")
    parser.add_argument("--password", help="Login password for automated sign-in.")
    parser.add_argument("--screenshot-dir", default="debug_shots")
    parser.add_argument("--result-file", default="artifacts/delete_result.json", help="Where to write result JSON.")
    return parser.parse_args(args)


def wait_for_manual_login_if_needed(page: Page, require_manual_login: bool) -> None:
    if not require_manual_login:
        return
    log("頁面已開啟。請先在瀏覽器完成手動登入；登入完成後回到終端機按 Enter 繼續。")
    try:
        input()
        page.wait_for_timeout(400)
        return
    except EOFError:
        log("[info] 目前環境無法接收 Enter，改為被動等待你完成登入（不會自動點擊頁面）。")
    for _ in range(600):
        try:
            project_menu = page.locator("xpath=//span[normalize-space()='專案']").first
            if project_menu.count() > 0 and project_menu.is_visible():
                page.wait_for_timeout(400)
                return
        except Exception:
            pass
        page.wait_for_timeout(1000)
    raise TimeoutError("等待手動登入逾時，請確認是否已登入並停留在系統內頁。")


def login_with_credentials_if_provided(page: Page, username: str | None, password: str | None) -> bool:
    if not username or not password:
        return False
    log("[login] 使用自動登入流程")
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

    def _first_visible(selectors: tuple[str, ...]):
        for selector in selectors:
            loc = page.locator(selector)
            try:
                for i in range(loc.count()):
                    node = loc.nth(i)
                    if node.is_visible():
                        return node
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
    if urlparse(page.url).path.rstrip("/") == target_path:
        log(f"[nav] 已在目標專案頁: {target_path}")
        return

    project_match = re.search(r"(/projects/\d+)", base_url)
    project_path = project_match.group(1) if project_match else target_path

    for selector in (
        "xpath=//li[@role='menuitem'][.//span[normalize-space()='專案']]",
        "xpath=//*[contains(@class, 'ant-menu-item')][.//span[normalize-space()='專案']]",
    ):
        node = page.locator(selector).first
        try:
            if node.count() > 0 and node.is_visible():
                node.click()
                page.wait_for_timeout(700)
                break
        except Exception:
            continue

    for selector in (f"xpath=//a[@href='{project_path}']", f"xpath=//a[contains(@href, '{project_path}')]"):
        node = page.locator(selector).first
        try:
            if node.count() > 0 and node.is_visible():
                node.click()
                page.wait_for_timeout(700)
                break
        except Exception:
            continue

    if urlparse(page.url).path.rstrip("/") != target_path:
        page.goto(base_url)
        page.wait_for_timeout(700)
    log(f"[nav] 已切換到專案頁: {target_path}")


def href_to_id(href: str) -> str:
    match = re.search(r"/datasets/(\d+)", href or "")
    return match.group(1) if match else ""


def id_to_href(base_url: str, dataset_id: str) -> str:
    project_match = re.search(r"(/projects/\d+)", base_url)
    prefix = project_match.group(1) if project_match else "/projects/1"
    return f"{prefix}/datasets/{dataset_id}"


def load_targets(args: argparse.Namespace) -> list[dict]:
    rows: list[dict] = []
    for href in args.href:
        rows.append({"dataset_id": href_to_id(href), "href": href, "name": ""})
    for dataset_id in args.dataset_id:
        rows.append({"dataset_id": str(dataset_id), "href": "", "name": ""})

    if args.from_find_json:
        p = Path(args.from_find_json)
        if p.exists():
            payload = json.loads(p.read_text(encoding="utf-8"))
            for item in payload.get("items", []):
                href = item.get("href", "")
                rows.append(
                    {
                        "dataset_id": item.get("dataset_id") or href_to_id(href),
                        "href": href,
                        "name": item.get("name", ""),
                    }
                )

    dedup = {}
    for row in rows:
        dataset_id = str(row.get("dataset_id") or "").strip()
        if not dataset_id:
            continue
        row["dataset_id"] = dataset_id
        dedup[dataset_id] = row
    items = list(dedup.values())
    log(f"[targets] 載入可刪除目標 {len(items)} 筆（去重後）")

    if not args.delete_old_only:
        log("[targets] delete_old_only=False，按輸入 ID 全部刪除")
        return items

    grouped = {}
    for item in items:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        grouped.setdefault(name, []).append(item)

    old_items = []
    for name, group in grouped.items():
        if len(group) <= 1:
            continue
        ordered = sorted(group, key=lambda r: int(r["dataset_id"]), reverse=True)
        keep_id = ordered[0]["dataset_id"]
        delete_ids = [item["dataset_id"] for item in ordered[1:]]
        log(f"[targets] {name}: 保留最大ID={keep_id}，刪除較小ID={delete_ids}")
        old_items.extend(ordered[1:])
    log(f"[targets] delete_old_only=True，最終刪除目標 {len(old_items)} 筆")
    return old_items


def save_shot(page: Page, screenshot_dir: Path, name: str) -> None:
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshot_dir / name), full_page=True)


def scroll_until_card_visible(page: Page, href: str, max_steps: int = 300) -> bool:
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(250)
    last_height = -1
    stable = 0
    card_selector = f"xpath=//div[contains(@class, 'ant-card') and .//a[@href='{href}']]"

    for _ in range(max_steps):
        card = page.locator(card_selector).first
        try:
            if card.count() > 0 and card.is_visible():
                return True
        except Exception:
            pass

        current_height = page.evaluate("document.documentElement.scrollHeight")
        at_bottom = page.evaluate("window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4")
        if at_bottom and current_height == last_height:
            stable += 1
        else:
            stable = 0
        if stable >= 2:
            break
        last_height = current_height
        page.evaluate("window.scrollBy(0, Math.max(420, Math.floor(window.innerHeight * 0.9)))")
        page.wait_for_timeout(220)
    return False


def delete_by_href(page: Page, href: str, label: str, screenshot_dir: Path) -> bool:
    if not scroll_until_card_visible(page, href):
        log(f"[delete] 無法在頁面中定位 href={href}")
        return False

    card = page.locator(f"xpath=//div[contains(@class, 'ant-card') and .//a[@href='{href}']]").first
    if card.count() == 0:
        return False
    if not card.is_visible():
        return False

    delete_button = card.locator("xpath=.//span[normalize-space()='刪除']").first
    if delete_button.count() == 0 or not delete_button.is_visible():
        return False

    save_shot(page, screenshot_dir, f"before_delete_{label}.png")
    delete_button.click()
    page.wait_for_timeout(450)
    save_shot(page, screenshot_dir, f"after_delete_click_{label}.png")

    confirm_candidates = (
        "xpath=//div[contains(@class, 'ant-popconfirm')]//button[.//span[normalize-space()='確 定'] or normalize-space()='確 定']",
        "xpath=//div[contains(@class, 'ant-popconfirm')]//button[.//span[normalize-space()='確定'] or normalize-space()='確定']",
        "xpath=//div[contains(@class, 'ant-popconfirm')]//button[contains(@class, 'ant-btn-primary')]",
        "xpath=//div[contains(@class, 'ant-modal')]//button[contains(@class, 'ant-btn-primary')]",
    )

    confirm = None
    for selector in confirm_candidates:
        loc = page.locator(selector)
        for i in range(loc.count()):
            btn = loc.nth(i)
            try:
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
    save_shot(page, screenshot_dir, f"after_delete_confirm_{label}.png")
    return True


def main(args_list: list[str] | None = None) -> int:
    args = parse_args(args_list)
    log(f"[start] delete datasets base_url={args.base_url}")
    targets = load_targets(args)
    if not targets:
        log("[info] no targets to delete")
        return 0

    screenshot_dir = Path(args.screenshot_dir)
    results = []

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

            for row in sorted(targets, key=lambda r: int(r["dataset_id"]), reverse=True):
                dataset_id = row["dataset_id"]
                href = row.get("href") or id_to_href(args.base_url, dataset_id)
                name = (row.get("name") or "").strip()
                label = name or dataset_id

                ensure_project_page(page, args.base_url)
                ok = delete_by_href(page, href, label, screenshot_dir)
                results.append({"dataset_id": dataset_id, "href": href, "name": name, "deleted": ok})
                log(f"[delete] {'ok' if ok else 'failed'} | id={dataset_id} | {label}")
                page.wait_for_timeout(180)

            ok_count = sum(1 for r in results if r["deleted"])
            fail_count = len(results) - ok_count
            payload = {
                "base_url": args.base_url,
                "target_count": len(results),
                "deleted_ok": ok_count,
                "deleted_failed": fail_count,
                "delete_old_only": args.delete_old_only,
                "items": results,
            }
            result_path = Path(args.result_file)
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            log(f"[summary] deleted_ok={ok_count}, deleted_failed={fail_count}")
            log(f"[summary] result_file={result_path}")
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
