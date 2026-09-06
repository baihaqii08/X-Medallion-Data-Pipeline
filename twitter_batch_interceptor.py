from __future__ import annotations

import argparse
import json
import logging
import os
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from settings import env_bool, env_int, load_environment


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

load_environment()

POST_COUNT_PATTERN = re.compile(
    r"^\d+(?:[.,]\d+)?\s*[kmb]?(?:\+)?\s+posts?$",
    re.IGNORECASE,
)


class TwitterBatchInterceptor:
    def __init__(self) -> None:
        self.intercepted_data: list[dict] = []
        self.current_trend = "Unknown"

    def handle_response(self, response: Response) -> None:
        try:
            url = response.url
            if response.status != 200 or not ("graphql" in url or "timeline.json" in url):
                return
            data = response.json()
            endpoint_name = url.split("?", 1)[0].rsplit("/", 1)[-1]
            self.intercepted_data.append(
                {
                    "trend": self.current_trend,
                    "endpoint": endpoint_name,
                    "url": url,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "raw_json": data,
                }
            )
            logger.debug("Intercepted GraphQL endpoint: %s", endpoint_name)
        except Exception as exc:
            logger.debug("Could not decode intercepted response %s: %s", response.url, exc)

    @staticmethod
    def extract_clean_trend_names(page) -> list[str]:
        trends: list[str] = []
        locator = page.locator("div[data-testid='trend']")
        for index in range(locator.count()):
            lines = locator.nth(index).inner_text().splitlines()
            candidates = []
            for line in lines:
                clean = line.strip()
                lower = clean.casefold()
                if not clean or clean == "·" or clean.isdigit():
                    continue
                if "trending" in lower or "only on x" in lower:
                    continue
                if POST_COUNT_PATTERN.fullmatch(clean):
                    continue
                candidates.append(clean)

            if candidates:
                trend_name = candidates[0]
                if len(trend_name) > 1 and trend_name not in trends:
                    trends.append(trend_name)
        return trends

    def write_batch(self, raw_dir: Path) -> Path | None:
        if not self.intercepted_data:
            logger.error("No GraphQL payloads were captured; no Bronze file was created")
            return None

        raw_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        output_path = raw_dir / f"twitter-batch-{timestamp}.json"
        temporary_path = output_path.with_suffix(".json.tmp")
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(self.intercepted_data, handle, ensure_ascii=False)
        os.replace(temporary_path, output_path)
        logger.info(
            "Bronze batch committed: %s (%d intercepted payloads)",
            output_path,
            len(self.intercepted_data),
        )
        return output_path

    def scrape(self, max_trends: int, scrolls_per_trend: int, headless: bool) -> Path | None:
        from playwright.sync_api import sync_playwright

        self.intercepted_data.clear()
        self.current_trend = "Unknown"

        project_dir = Path(__file__).resolve().parent
        profile_dir = project_dir / "twitter_profile"
        raw_dir = project_dir / "raw_batches"
        auth_token = os.getenv("TWITTER_AUTH_TOKEN", "").strip()
        ct0 = os.getenv("TWITTER_CT0", "").strip()
        browser_channel = os.getenv("TWITTER_BROWSER_CHANNEL", "").strip()

        with sync_playwright() as playwright:
            launch_options = {
                "user_data_dir": str(profile_dir),
                "headless": headless,
                "viewport": {"width": 1280, "height": 720},
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if browser_channel:
                launch_options["channel"] = browser_channel

            logger.info(
                "Launching browser: headless=%s channel=%s",
                headless,
                browser_channel or "playwright-chromium",
            )
            context = playwright.chromium.launch_persistent_context(**launch_options)
            failure = None
            try:
                if auth_token and ct0:
                    context.add_cookies(
                        [
                            {"name": name, "value": value, "domain": domain, "path": "/"}
                            for domain in (".twitter.com", ".x.com")
                            for name, value in (("auth_token", auth_token), ("ct0", ct0))
                        ]
                    )
                    logger.info("Authentication cookies loaded from environment")
                elif auth_token or ct0:
                    logger.warning("Both TWITTER_AUTH_TOKEN and TWITTER_CT0 are required for cookie login")

                page = context.pages[0] if context.pages else context.new_page()
                page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                page.on("response", self.handle_response)

                logger.info("Loading X trending topics")
                page.goto(
                    "https://x.com/explore/tabs/trending",
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                page.wait_for_timeout(7_000)
                page.evaluate("window.scrollBy(0, 1000)")
                page.wait_for_timeout(2_000)

                trends = self.extract_clean_trend_names(page)
                if not trends:
                    logger.warning("No dynamic trends detected; using #Indonesia fallback")
                    trends = ["#Indonesia"]
                logger.info("Discovered %d trends; processing up to %d", len(trends), max_trends)

                # Explore-page payloads are not part of a selected trend batch.
                self.intercepted_data.clear()

                for trend in trends[:max_trends]:
                    self.current_trend = trend
                    search_url = (
                        "https://x.com/search?q="
                        f"{urllib.parse.quote(trend)}&src=trend_click&f=live"
                    )
                    logger.info("Extracting trend: %s", trend)
                    page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(5_000)
                    for scroll_index in range(scrolls_per_trend):
                        page.evaluate("window.scrollBy(0, 2000)")
                        page.wait_for_timeout(3_000)
                        logger.debug(
                            "Trend %s scroll %d/%d",
                            trend,
                            scroll_index + 1,
                            scrolls_per_trend,
                        )
            except Exception as exc:
                failure = exc
                logger.exception("Extraction stopped before all trends completed")
            finally:
                context.close()

        output_path = self.write_batch(raw_dir)
        if failure is not None:
            raise RuntimeError(
                f"Extraction failed; partial Bronze batch: {output_path or 'not available'}"
            ) from failure
        return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Capture X GraphQL trend batches")
    parser.add_argument(
        "--max-trends",
        type=int,
        default=env_int("TWITTER_MAX_TRENDS", 30),
        help="Maximum trending topics to process",
    )
    parser.add_argument(
        "--scrolls",
        type=int,
        default=env_int("TWITTER_SCROLLS_PER_TREND", 15),
        help="Scrolls per trending topic",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=env_bool("TWITTER_HEADLESS", False),
        help="Run Playwright without a visible browser window",
    )
    args = parser.parse_args()
    result = TwitterBatchInterceptor().scrape(args.max_trends, args.scrolls, args.headless)
    raise SystemExit(0 if result else 1)
