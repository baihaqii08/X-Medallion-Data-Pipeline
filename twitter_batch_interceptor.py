import os
import json
import time
import urllib.parse
import logging
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Configure standard logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

TWITTER_AUTH_TOKEN = os.getenv("TWITTER_AUTH_TOKEN", "")
TWITTER_CT0 = os.getenv("TWITTER_CT0", "")

# Global variables to maintain state during interception
intercepted_data = []
current_trend = "Unknown"

def handle_response(response):
    """
    Network interceptor callback to capture GraphQL JSON payloads.
    """
    try:
        url = response.url
        if response.status == 200 and ("graphql" in url or "timeline.json" in url):
            endpoint_name = url.split('?')[0].split('/')[-1]
            logger.info(f"Intercepted GraphQL payload from endpoint: {endpoint_name}")
            data = response.json()
            intercepted_data.append({
                "trend": current_trend,
                "url": url,
                "timestamp": datetime.now().isoformat(),
                "raw_json": data
            })
    except Exception:
        pass

def extract_clean_trend_names(page):
    """
    Extracts trending topics from the Explore page, filtering out noise.
    """
    trends = []
    trend_elements = page.locator("div[data-testid='trend']").all()
    
    for el in trend_elements:
        text = el.inner_text()
        lines = text.split('\n')
        
        valid_lines = []
        for line in lines:
            line_clean = line.strip()
            # Filter empty lines, bullet points, and numerical rankings
            if line_clean in ['', '·'] or line_clean.isdigit():
                continue
                
            lower_line = line_clean.lower()
            if "trending" in lower_line: continue
            if "only on x" in lower_line: continue
            if "post" in lower_line: continue
            
            valid_lines.append(line_clean)
            
        if valid_lines:
            trend_name = valid_lines[0]
            if trend_name not in trends and len(trend_name) > 1:
                trends.append(trend_name)
                
    return trends

def scrape_twitter_batch(max_trends_to_scrape=10, scrolls_per_trend=3):
    """
    Main extraction function for batch processing X (Twitter) trends.
    """
    global current_trend
    
    profile_dir = os.path.join(os.getcwd(), "twitter_profile")
    raw_dir = os.path.join(os.getcwd(), "raw_batches")
    
    if not os.path.exists(raw_dir):
        os.makedirs(raw_dir)

    with sync_playwright() as p:
        logger.info(f"Initializing browser context with profile at {profile_dir}")
        browser = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
            channel="msedge", 
            viewport={"width": 1280, "height": 720},
            args=['--disable-blink-features=AutomationControlled']
        )
        
        if TWITTER_AUTH_TOKEN:
            logger.info("Injecting authentication cookies...")
            browser.add_cookies([
                {"name": "auth_token", "value": TWITTER_AUTH_TOKEN, "domain": ".twitter.com", "path": "/"},
                {"name": "ct0", "value": TWITTER_CT0, "domain": ".twitter.com", "path": "/"},
                {"name": "auth_token", "value": TWITTER_AUTH_TOKEN, "domain": ".x.com", "path": "/"},
                {"name": "ct0", "value": TWITTER_CT0, "domain": ".x.com", "path": "/"}
            ])
            logger.info("Authentication cookies injected successfully.")
        
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # Attach network interceptor
        page.on("response", handle_response)
        
        logger.info("Navigating to Trending tab...")
        page.goto("https://x.com/explore/tabs/trending", timeout=60000)
        time.sleep(7)
        page.evaluate("window.scrollBy(0, 1000)")
        time.sleep(2)
        
        trends = extract_clean_trend_names(page)
        
        logger.info(f"Successfully extracted {len(trends)} trending topics.")
        for i, t in enumerate(trends, 1):
            logger.debug(f"Trend {i}: {t}")
            
        if not trends:
            logger.warning("Failed to extract dynamic trends. Falling back to default topics.")
            trends = ["#Indonesia", "Viral"]

        for trend in trends[:max_trends_to_scrape]:
            current_trend = trend
            logger.info(f"Initiating extraction sequence for trend: {trend}")
            
            search_url = f"https://x.com/search?q={urllib.parse.quote(trend)}&src=trend_click"
            page.goto(search_url)
            time.sleep(5)
            
            for i in range(scrolls_per_trend):
                logger.info(f"Pagination scroll {i+1}/{scrolls_per_trend} for trend '{trend}'")
                page.evaluate("window.scrollBy(0, 2000)")
                time.sleep(3)
            
        logger.info(f"Extraction sequence completed. Total intercepted payloads: {len(intercepted_data)}")
        browser.close()
        
        if intercepted_data:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(raw_dir, f"twitter-batch-{timestamp}.json")
            
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(intercepted_data, f, indent=4, ensure_ascii=False)
                
            logger.info(f"Bronze layer batch file committed: {filename}")
        else:
            logger.error("API Interception failed. No payloads captured.")

if __name__ == "__main__":
    scrape_twitter_batch(max_trends_to_scrape=30, scrolls_per_trend=15)
