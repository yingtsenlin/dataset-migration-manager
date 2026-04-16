from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, sync_playwright


@dataclass
class VerifyResult:
    target_count: int
    project_seen_count: int
    matched_count: int
    missing_count: int
    missing: list[str]
    matched: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify target dataset names exist in project page.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--target-file", required=True, help="Text file containing dataset ZIP names or stems.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--browser-channel", default="msedge")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--max-scroll-steps", type=int, default=220)
    parser.add_argument("--scroll-wait-ms", type=int, default=200)
    parser.add_argument("--output-file", required=True)
    return parser.parse_args()


def first_visible(page: Page, selectors: tuple[str, ...]):
    for selector in selectors:
        loc = page.locator(selector)
        try:
            for idx in range(loc.count()):
                node = loc.nth(idx)
                if node.is_visible():
                    return node
        except Exception:
            continue
    return None


def login(page: Page, username: str, password: str) -> None:
    user = first_visible(
        page,
        (
            "xpath=//input[@name='username']",
            "xpath=//input[@id='username']",
            "xpath=//input[contains(@placeholder, '帳號')]",
            "xpath=//input[@type='text']",
        ),
    )
    pw = first_visible(
        page,
        (
            "xpath=//input[@name='password']",
            "xpath=//input[@id='password']",
            "xpath=//input[contains(@placeholder, '密碼')]",
            "xpath=//input[@type='password']",
        ),
    )
    if user is None or pw is None:
        return

    user.fill(username)
    pw.fill(password)
    submit = first_visible(
        page,
        (
            "xpath=//button[@type='submit']",
            "xpath=//button[contains(normalize-space(.), '登入')]",
            "xpath=//button[contains(normalize-space(.), 'Login')]",
        ),
    )
    if submit is not None:
        submit.click()
    else:
        pw.press("Enter")
    page.wait_for_timeout(900)


def ensure_project_page(page: Page, base_url: str) -> None:
    target_path = urlparse(base_url).path.rstrip("/")
    current_path = urlparse(page.url).path.rstrip("/")
    if current_path == target_path:
        return
    page.goto(base_url)
    page.wait_for_timeout(1000)


def scrape_all_names(page: Page, max_steps: int, wait_ms: int) -> set[str]:
    names: set[str] = set()
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(250)

    stable = 0
    last_count = -1
    for _ in range(max_steps):
        batch = page.evaluate(
            """
            () => {
              const selectors = [
                "div.ant-card-head-title a",
                ".ant-card .ant-card-head-title a",
                ".ant-card a"
              ];
              for (const sel of selectors) {
                const nodes = Array.from(document.querySelectorAll(sel));
                if (!nodes.length) continue;
                const out = nodes
                  .map(n => (n.textContent || "").trim())
                  .filter(Boolean);
                if (out.length) return out;
              }
              return [];
            }
            """
        )
        for name in batch:
            names.add(str(name).strip())

        if len(names) == last_count:
            stable += 1
        else:
            stable = 0
        if stable >= 4:
            break
        last_count = len(names)

        page.evaluate("window.scrollBy(0, Math.max(480, Math.floor(window.innerHeight * 0.95)))")
        page.wait_for_timeout(wait_ms)
    return names


def load_targets(path: Path) -> list[str]:
    targets: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        item = raw.strip()
        if not item:
            continue
        stem = Path(item).stem
        targets.append(stem)
    return sorted(dict.fromkeys(targets))


def main() -> int:
    args = parse_args()
    target_names = load_targets(Path(args.target_file))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.browser_channel, headless=args.headless)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(args.base_url)
            login(page, args.username, args.password)
            ensure_project_page(page, args.base_url)
            seen = scrape_all_names(page, args.max_scroll_steps, args.scroll_wait_ms)

            matched = sorted([name for name in target_names if name in seen])
            missing = sorted([name for name in target_names if name not in seen])

            result = VerifyResult(
                target_count=len(target_names),
                project_seen_count=len(seen),
                matched_count=len(matched),
                missing_count=len(missing),
                missing=missing,
                matched=matched,
            )
            Path(args.output_file).write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
            return 0
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
