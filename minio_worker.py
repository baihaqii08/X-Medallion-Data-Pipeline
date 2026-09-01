import json
import time
from datetime import datetime
import greenstalk
import boto3
import os
from botocore.client import Config
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

# Konfigurasi Koneksi (sesuaikan dengan docker-compose)
BEANSTALKD_HOST = '127.0.0.1'
BEANSTALKD_PORT = 11300
TUBE_NAME = 'raw-data'

# Konfigurasi Data Lake Faiq (Laptop 1) via Ngrok (Rahasia dari .env)
S3_ENDPOINT = os.getenv('S3_ENDPOINT', 'https://ventral-unfondly-rosalyn.ngrok-free.dev')
ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY', 'admin')
SECRET_KEY = os.getenv('MINIO_SECRET_KEY', 'password123')
BUCKET_NAME = os.getenv('MINIO_BUCKET_NAME', 'narative-datalake')

def setup_s3():
    client = boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        config=Config(signature_version='s3v4'),
        region_name='us-east-1'
    )
    return client

def start_worker():
    # Menyiapkan klien Boto3 S3
    s3_client = setup_s3()
    
    print(f"Menyambungkan ke Beanstalkd di {BEANSTALKD_HOST}:{BEANSTALKD_PORT}...")
    with greenstalk.Client((BEANSTALKD_HOST, BEANSTALKD_PORT), watch=TUBE_NAME) as client:
        print(f"Worker siap! Mendengarkan *tube* '{TUBE_NAME}' untuk antrean data baru...")
        while True:
            try:
                # Menunggu job baru masuk (script akan berhenti di sini sampai ada job)
                job = client.reserve()
                print(f"\n[+] Menerima Job ID: {job.id}")
                
                # Mem-parsing isi pesan (diharapkan berformat JSON)
                data = json.loads(job.body)
                platform = data.get('platform', 'unknown')
                author = data.get('author_username', 'unknown')
                
                post_id = data.get('post_id', job.id) # Ambil post_id aslinya
                
                # Membuat nama file unik BUKAN berdasarkan waktu, melainkan post_id!
                # Ini menjamin tidak ada duplikasi data di Data Lake (Upsert logic).
                month_folder = datetime.now().strftime("%Y-%m")
                filename = f"{platform}_{author}_{post_id}.json"
                folder_path = f"twitter/parsed/{month_folder}/"
                object_key = f"{folder_path}{filename}"
                
                # Mengunggah data JSON ke Data Lake Faiq via Ngrok
                json_bytes = job.body.encode('utf-8')
                
                s3_client.put_object(
                    Bucket=BUCKET_NAME,
                    Key=object_key,
                    Body=json_bytes,
                    ContentType='application/json'
                )
                print(f"Berhasil menyimpan file {object_key} ke bucket '{BUCKET_NAME}' di Laptop Faiq via Ngrok.")
                
                # Menghapus job dari antrean Beanstalkd jika sukses disimpan
                client.delete(job)
                
            except json.JSONDecodeError:
                print(f"[-] Error: Job {job.id} bukan JSON yang valid. Job dikubur (Bury).")
                client.bury(job)
            except Exception as e:
                print(f"[-] Error saat memproses job: {e}")
                time.sleep(5) # Berhenti sejenak jika ada error server

if __name__ == "__main__":
    start_worker()
