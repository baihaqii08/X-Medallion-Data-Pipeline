import os
import json
import time
import urllib.parse
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Load variables from .env file
load_dotenv()

# Mengambil Token dari file .env (SANGAT AMAN!)
TWITTER_AUTH_TOKEN = os.getenv("TWITTER_AUTH_TOKEN", "")
TWITTER_CT0 = os.getenv("TWITTER_CT0", "")

# Inisialisasi list untuk menampung JSON mentah dari GraphQL
intercepted_data = []

# Variabel global untuk mencatat tren apa yang sedang di-scroll
current_trend = "Unknown"

def handle_response(response):
    """
    Fungsi penyadap (interceptor).
    Akan dipanggil setiap kali browser menerima data (response) dari internet.
    """
    try:
        url = response.url
        # Kita incar jalur belakang (GraphQL API / Timeline JSON) milik Twitter
        if response.status == 200 and ("graphql" in url or "timeline.json" in url):
            print(f"✅ [INTERCEPT] Berhasil menyadap payload JSON dari: {url.split('?')[0].split('/')[-1]}")
            data = response.json()
            intercepted_data.append({
                "trend": current_trend, # SEKARANG KITA TAHU TWEET INI DARI TREN APA!
                "url": url,
                "timestamp": datetime.now().isoformat(),
                "raw_json": data
            })
    except Exception as e:
        # Abaikan error jika response bukan JSON atau connection closed
        pass

def extract_clean_trend_names(page):
    """Mengekstrak daftar tren dari halaman Explore Twitter"""
    trends = []
    trend_elements = page.locator("div[data-testid='trend']").all()
    
    for el in trend_elements:
        text = el.inner_text()
        lines = text.split('\n')
        
        valid_lines = []
        for line in lines:
            line_clean = line.strip()
            # Buang baris kosong, karakter titik tengah '·', dan angka urutan murni (misal: '1', '2')
            if line_clean in ['', '·'] or line_clean.isdigit():
                continue
                
            # Buang label kategori bawaan Twitter (Trending, Only on X, posts, dll)
            lower_line = line_clean.lower()
            if "trending" in lower_line: continue
            if "only on x" in lower_line: continue
            if "post" in lower_line: continue
            
            valid_lines.append(line_clean)
            
        if valid_lines:
            # Baris valid pertama yang tersisa hampir dipastikan 100% adalah topik utamanya
            trend_name = valid_lines[0]
            if trend_name not in trends and len(trend_name) > 1:
                trends.append(trend_name)
                
    return trends

def scrape_twitter_batch(max_trends_to_scrape=10, scrolls_per_trend=3):
    global current_trend
    
    profile_dir = os.path.join(os.getcwd(), "twitter_profile")
    raw_dir = os.path.join(os.getcwd(), "raw_batches")
    
    if not os.path.exists(raw_dir):
        os.makedirs(raw_dir)

    with sync_playwright() as p:
        print(f"Membuka browser dengan profil di '{profile_dir}'...")
        browser = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
            channel="msedge", 
            viewport={"width": 1280, "height": 720},
            args=['--disable-blink-features=AutomationControlled']
        )
        
        # MENGINJEKSI COOKIES OTOMATIS
        if TWITTER_AUTH_TOKEN:
            print("Menginjeksi cookies ke dalam browser untuk Login Otomatis...")
            browser.add_cookies([
                {"name": "auth_token", "value": TWITTER_AUTH_TOKEN, "domain": ".twitter.com", "path": "/"},
                {"name": "ct0", "value": TWITTER_CT0, "domain": ".twitter.com", "path": "/"},
                {"name": "auth_token", "value": TWITTER_AUTH_TOKEN, "domain": ".x.com", "path": "/"},
                {"name": "ct0", "value": TWITTER_CT0, "domain": ".x.com", "path": "/"}
            ])
            print("Cookies berhasil diinjeksi!")
        
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # MENGAKTIFKAN PENYADAP JARINGAN (NETWORK INTERCEPTOR)
        page.on("response", handle_response)
        
        # LANGKAH 1: Kumpulkan Daftar Tren
        print("Membuka halaman Trending Indonesia...")
        page.goto("https://x.com/explore/tabs/trending", timeout=60000)
        time.sleep(7)
        page.evaluate("window.scrollBy(0, 1000)")
        time.sleep(2)
        
        trends = extract_clean_trend_names(page)
        
        print(f"\nBerhasil menemukan {len(trends)} Top Trending Topics:")
        for i, t in enumerate(trends, 1):
            print(f"  {i}. {t}")
            
        if not trends:
            print("Gagal menemukan elemen tren. Menggunakan tren cadangan sementara.")
            trends = ["#Indonesia", "Viral"]

        # LANGKAH 2: Looping Setiap Trend dan Intercept Data
        for trend in trends[:max_trends_to_scrape]:
            current_trend = trend
            print(f"\n=======================================================")
            print(f"Mulai menyedot data untuk tren: {trend}")
            print(f"=======================================================")
            
            search_url = f"https://x.com/search?q={urllib.parse.quote(trend)}&src=trend_click"
            page.goto(search_url)
            time.sleep(5) # Tunggu loading awal
            
            for i in range(scrolls_per_trend): # Lakukan scroll untuk memancing lebih banyak data
                print(f"Scroll {i+1}/{scrolls_per_trend} untuk tren '{trend}'...")
                page.evaluate("window.scrollBy(0, 2000)")
                time.sleep(3)
            
        print(f"\n=======================================================")
        print(f"SELESAI KESELURUHAN! Berhasil menyadap {len(intercepted_data)} payload GraphQL.")
        print(f"=======================================================")
        
        browser.close()
        
        # Simpan hasil sadapan ke file lokal
        if intercepted_data:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(raw_dir, f"twitter-batch-{timestamp}.json")
            
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(intercepted_data, f, indent=4, ensure_ascii=False)
                
            print(f"Data Batch berhasil disimpan di: {filename}")
        else:
            print("Gagal menyadap API. Twitter mungkin mengubah URL endpoint-nya atau API tidak dipanggil.")

if __name__ == "__main__":
    # Kita turunkan sementara angkanya agar tes manual Anda berjalan cepat!
    # Anda bisa menaikkannya kembali ke 30 dan 10 saat mau dipasang auto_pipeline.py
    scrape_twitter_batch(max_trends_to_scrape=30, scrolls_per_trend=15)
