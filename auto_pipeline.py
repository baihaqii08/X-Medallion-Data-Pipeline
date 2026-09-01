import time
import subprocess
from datetime import datetime

def run_pipeline():
    print(f"\n=======================================================")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] MEMULAI SIKLUS SCRAPING OTOMATIS")
    print(f"=======================================================")
    
    # 1. Menjalankan Pemanen Data (Scraper)
    print(">> Menjalankan twitter_batch_interceptor.py...")
    subprocess.run([".venv\\Scripts\\python.exe", "twitter_batch_interceptor.py"])
    
    # 2. Menjalankan Pembersih Data (Parser)
    print("\n>> Scraping selesai. Memulai twitter_parser.py untuk mempublikasikan data...")
    subprocess.run([".venv\\Scripts\\python.exe", "twitter_parser.py"])
    
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Siklus saat ini rampung. Menunggu siklus berikutnya...")
    print(f"=======================================================\n")

if __name__ == "__main__":
    # Jadwal waktu spesifik: Dibuat setiap 1.5 jam (Sangat aman untuk 1 akun, tapi hasilnya 2x lipat lebih banyak!)
    JADWAL_SCRAPING = ["09:30", "11:00", "12:30", "14:00", "15:30", "16:50"]
    
    print("🤖 Auto-Pipeline Aktif! Sistem siap mengeruk data pada jam-jam berikut:")
    for jadwal in JADWAL_SCRAPING:
        print(f"   ⏰ {jadwal}")
    print("\nPastikan minio_worker.py sedang menyala di terminal lain sebagai penangkap data.")
    print("Menunggu waktu yang ditentukan...")
    
    # Looping abadi mengecek waktu setiap menit
    while True:
        waktu_sekarang = datetime.now().strftime("%H:%M")
        
        if waktu_sekarang in JADWAL_SCRAPING:
            run_pipeline()
            # Tidur 65 detik untuk memastikan skrip tidak tereksekusi dua kali di menit yang sama
            time.sleep(65) 
        else:
            # Cek jam lagi setiap 20 detik
            time.sleep(20)
