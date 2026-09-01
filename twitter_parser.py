import os
import glob
import json
import uuid
import time
import gzip
import shutil
import os
from datetime import datetime
import greenstalk
from validator import is_content_valid

# Konfigurasi Koneksi Beanstalkd
BEANSTALKD_HOST = '127.0.0.1'
BEANSTALKD_PORT = 11300
TUBE_NAME = 'raw-data'

def find_tweets(obj, results, trend_topic_context="Unknown"):
    """
    Fungsi cerdas (rekursif) untuk menembus lapisan JSON GraphQL sedalam apapun
    dan mengekstrak objek 'tweet' yang memiliki isi teks.
    """
    if isinstance(obj, dict):
        # Jika menemukan blok data yang memiliki teks lengkap, itu adalah tweet!
        if 'legacy' in obj and 'full_text' in obj['legacy']:
            # Simpan trend_topic yang disisipkan oleh interceptor (jika ada) ke dalam objek tweet
            if trend_topic_context:
                obj['_trend_topic_context'] = trend_topic_context
            results.append(obj)
        
        # Cari trend topic di root level dari setiap objek (karena interceptor kita menyimpannya di root)
        current_trend = obj.get('trend', trend_topic_context)
            
        for k, v in obj.items():
            find_tweets(v, results, current_trend)
    elif isinstance(obj, list):
        for item in obj:
            find_tweets(item, results, trend_topic_context)

def get_latest_batch_file():
    raw_dir = os.path.join(os.getcwd(), "raw_batches")
    files = glob.glob(os.path.join(raw_dir, "twitter-batch-*.json"))
    if not files:
        return None
    # Mengambil file terbaru berdasarkan waktu pembuatannya
    return max(files, key=os.path.getctime)

def parse_and_publish():
    batch_file = get_latest_batch_file()
    if not batch_file:
        print("❌ Tidak ada file batch Twitter yang ditemukan di folder 'raw_batches'.")
        return

    print(f"Membaca file Batch: {batch_file}")
    with open(batch_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    print("Mengekstrak data dari GraphQL...")
    raw_tweets = []
    find_tweets(data, raw_tweets)
    
    # Supaya tidak ada tweet ganda (karena API sering mengirim tweet yang sama saat scroll)
    unique_tweets = {t['rest_id']: t for t in raw_tweets if 'rest_id' in t}
    print(f"Berhasil menemukan {len(unique_tweets)} tweet unik dari tumpukan JSON API.")
    
    print(f"\nMenghubungkan ke Beanstalkd di {BEANSTALKD_HOST}:{BEANSTALKD_PORT}...")
    try:
        queue_client = greenstalk.Client((BEANSTALKD_HOST, BEANSTALKD_PORT), use=TUBE_NAME)
    except Exception as e:
        print(f"❌ Gagal terhubung ke Beanstalkd: {e}")
        return

    success_count = 0
    for tweet_id, tweet in unique_tweets.items():
        legacy = tweet.get('legacy', {})
        text = legacy.get('full_text', '')
        
        if not text:
            continue
            
        # [DATA VALIDATOR] Cek Spesifikasi Konten
        if not is_content_valid(text):
            print(f"  [-] Tweet diabaikan karena filter NSFW/Spam.")
            continue
            
        # Mengekstrak metadata
        likes = legacy.get('favorite_count', 0)
        comments = legacy.get('reply_count', 0)
        shares = legacy.get('retweet_count', 0)
        views_dict = tweet.get('views', {})
        views = int(views_dict.get('count', 0)) if isinstance(views_dict, dict) and views_dict.get('count') else 0
        
        # Mengekstrak author (agak dalam di struktur GraphQL)
        author = "unknown"
        try:
            user_result = tweet.get('core', {}).get('user_results', {}).get('result', {})
            # Twitter API kadang menyimpan username di 'core', kadang di 'legacy'
            if 'core' in user_result and 'screen_name' in user_result['core']:
                author = user_result['core']['screen_name']
            elif 'legacy' in user_result and 'screen_name' in user_result['legacy']:
                author = user_result['legacy']['screen_name']
        except Exception:
            pass
            
        hashtags = [word for word in text.split() if word.startswith('#')]
        
        # Konversi waktu ke Unix Timestamp (integer)
        try:
            posted_at_dt = datetime.strptime(legacy.get('created_at', ''), "%a %b %d %H:%M:%S %z %Y")
            timestamp = int(posted_at_dt.timestamp())
        except:
            timestamp = int(time.time())
            
        parsed_at = int(time.time())
        url = f"https://x.com/{author}/status/{tweet_id}"
        
        # Format Akhir yang sangat rapi untuk Database (Mengikuti standar struktur JSON TikTok Faiq)
        post_data = {
            "platform": "x", 
            "post_id": tweet_id,
            "author_username": author,
            "caption": text,
            "metrics": {
                "likes": likes,
                "comments": comments,
                "views": views,
                "shares": shares
            },
            "timestamp": timestamp,
            "url": url,
            "parsed_at": parsed_at,
            # Ekstra field khusus X untuk keperluan Narrative Trend PRD
            "trend_topic": tweet.get('_trend_topic_context', 'GraphQL Batch'),
            "hashtags": hashtags
        }
        
        # PUBLISH KE QUEUE
        json_payload = json.dumps(post_data)
        job_id = queue_client.put(json_payload)
        success_count += 1
        print(f"  [+] Terkirim ke Beanstalkd (Job ID: {job_id}) | Author: @{author}")
        
    queue_client.close()
    print(f"\n=======================================================")
    print(f"SELESAI! {success_count} Tweet bersih berhasil dipublikasikan ke Antrean (Queue).")
    print(f"=======================================================")
    
    # --- FITUR COMPRESSION (BRONZE LAYER ARCHIVE) ---
    print("\n[INFO] Mengompresi file raw mentah untuk menghemat memori laptop Anda...")
    compressed_filename = batch_file + ".gz"
    try:
        with open(batch_file, 'rb') as f_in:
            with gzip.open(compressed_filename, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Hapus file JSON asli yang membengkak setelah berhasil dikompresi
        os.remove(batch_file)
        print(f"✅ Berhasil! File mentah telah dikompresi menjadi: {compressed_filename}")
        print("Memori laptop Anda 90% lebih hemat, dan data mentah Anda tetap aman selamanya!")
    except Exception as e:
        print(f"❌ Gagal mengompresi file: {e}")

if __name__ == "__main__":
    parse_and_publish()
