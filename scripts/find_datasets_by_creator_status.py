from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


@dataclass(frozen=True)
class MatchRow:
    name: str
    href: str
    dataset_id: str
    creator: str
    status: str
    card_text: str


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find datasets from project list by creator/status/name filters.",
    )
    parser.add_argument("--base-url", required=True, help="Project dataset list URL.")
    parser.add_argument("--creator", help="Creator name to match exactly.")
    parser.add_argument("--status", help="Status label to match (e.g. 審核中, 待審核).")
    parser.add_argument(
        "--strict-status",
        action="store_true",
        help="Only match exact status text; by default, common aliases are included.",
    )
    parser.add_argument("--name-contains", help="Match dataset names containing this text.")
    parser.add_argument("--browser-channel", default="msedge", help="Chromium channel name. Default: msedge")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--require-manual-login", action="store_true")
    parser.add_argument("--login-url", help="Optional login page URL. Defaults to --base-url.")
    parser.add_argument("--username", help="Login username for automated sign-in.")
    parser.add_argument("--password", help="Login password for automated sign-in.")
    parser.add_argument("--output-format", choices=["pretty", "json"], default="pretty")
    parser.add_argument("--output-file", help="Optional path to save query result JSON.")
    parser.add_argument("--max-scroll-steps", type=int, default=120, help="Max scroll iterations while scanning cards.")
    parser.add_argument("--scroll-wait-ms", type=int, default=160, help="Wait time per scroll step.")
    return parser.parse_args()


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
    current_path = urlparse(page.url).path.rstrip("/")
    if current_path == target_path:
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


def status_aliases(status: str | None, strict: bool) -> list[str]:
    if not status:
        return []
    if strict:
        return [status]
    alias_map = {
        "審核中": ["審核中", "待審核"],
        "待審核": ["待審核", "審核中"],
    }
    return alias_map.get(status, [status])


def extract_creator(card_text: str) -> str:
    match = re.search(r"建立者[:：]\s*([^\s]+)", card_text)
    return match.group(1).strip() if match else ""


def extract_status(card_text: str) -> str:
    known = ["待審核", "審核中", "已通過", "已拒絕", "駁回", "approved", "rejected", "pending"]
    for token in known:
        if token in card_text:
            return token
    return ""


def href_to_dataset_id(href: str) -> str:
    match = re.search(r"/datasets/(\d+)", href or "")
    return match.group(1) if match else ""


def collect_matches(
    page: Page,
    creator: str | None,
    statuses: list[str],
    name_contains: str | None,
    max_scroll_steps: int,
    scroll_wait_ms: int,
) -> list[MatchRow]:
    cards = page.locator("xpath=//div[contains(@class, 'ant-card') and .//a[normalize-space()]]")
    seen = set()
    rows: list[MatchRow] = []

    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(250)

    last_height = -1
    stable = 0
    for _ in range(max_scroll_steps):
        count = cards.count()
        for i in range(count):
            card = cards.nth(i)
            try:
                if not card.is_visible():
                    continue
                name_node = card.locator("xpath=.//div[contains(@class, 'ant-card-head-title')]//a[normalize-space()]").first
                if name_node.count() == 0:
                    continue
                name = (name_node.inner_text() or "").strip()
                href = (name_node.get_attribute("href") or "").strip()
                key = href or name
                if not key or key in seen:
                    continue
                seen.add(key)

                text = (card.inner_text() or "").strip()
                row_creator = extract_creator(text)
                row_status = extract_status(text)

                if creator and row_creator != creator:
                    continue
                if statuses and row_status not in statuses:
                    continue
                if name_contains and name_contains not in name:
                    continue

                rows.append(
                    MatchRow(
                        name=name,
                        href=href,
                        dataset_id=href_to_dataset_id(href),
                        creator=row_creator,
                        status=row_status,
                        card_text=" ".join(text.split())[:240],
                    )
                )
            except Exception:
                continue

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
        page.wait_for_timeout(scroll_wait_ms)

    log(f"[scan] 掃描完成，符合條件筆數={len(rows)}")
    return rows


def print_pretty(rows: list[MatchRow], creator: str | None, requested_status: str | None, statuses: list[str], name_contains: str | None) -> None:
    print(
        f"查詢條件: 建立者={creator or '<any>'}, 狀態={requested_status or '<any>'}, "
        f"實際比對狀態={statuses or '<any>'}, 名稱包含={name_contains or '<any>'}"
    )
    print(f"符合筆數: {len(rows)}")
    for row in rows:
        print(f"- {row.name} | {row.status or '<none>'} | {row.creator or '<none>'} | {row.href or '<no-href>'}")


def main() -> int:
    args = parse_args()
    statuses = status_aliases(args.status, args.strict_status)
    log(
        "[start] find datasets "
        f"creator={args.creator or '<any>'}, status={args.status or '<any>'}, "
        f"name_contains={args.name_contains or '<any>'}"
    )

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

            rows = collect_matches(
                page,
                args.creator,
                statuses,
                args.name_contains,
                args.max_scroll_steps,
                args.scroll_wait_ms,
            )
            payload = {
                "creator": args.creator,
                "requested_status": args.status,
                "matched_statuses": statuses,
                "name_contains": args.name_contains,
                "count": len(rows),
                "items": [asdict(row) for row in rows],
            }

            if args.output_file:
                output_path = Path(args.output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                log(f"[output] 已寫入結果: {output_path}")

            if args.output_format == "json":
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print_pretty(rows, args.creator, args.status, statuses, args.name_contains)
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
