import json
import time
import greenstalk
import boto3
import os
import logging
from datetime import datetime
from botocore.client import Config
from dotenv import load_dotenv

# Configure standard logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load variables from .env file
load_dotenv()

# Broker Configuration
BEANSTALKD_HOST = '127.0.0.1'
BEANSTALKD_PORT = 11300
TUBE_NAME = 'raw-data'

# MinIO (Data Lake) Configuration via Ngrok
S3_ENDPOINT = os.getenv('S3_ENDPOINT', 'https://ventral-unfondly-rosalyn.ngrok-free.dev')
ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY', 'admin')
SECRET_KEY = os.getenv('MINIO_SECRET_KEY', 'password123')
BUCKET_NAME = os.getenv('MINIO_BUCKET_NAME', 'narative-datalake')

def setup_s3():
    """
    Initializes the Boto3 S3 client for interacting with MinIO.
    """
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
    """
    Continuous worker loop that consumes jobs from Beanstalkd and loads them into MinIO.
    Implements Upsert logic to prevent data duplication.
    """
    s3_client = setup_s3()
    
    logger.info(f"Connecting to Beanstalkd broker at {BEANSTALKD_HOST}:{BEANSTALKD_PORT}")
    with greenstalk.Client((BEANSTALKD_HOST, BEANSTALKD_PORT), watch=TUBE_NAME) as client:
        logger.info(f"Worker online. Listening on tube '{TUBE_NAME}' for new payloads...")
        while True:
            try:
                # Reserve blocks until a job is available
                job = client.reserve()
                logger.debug(f"Reserved Job ID: {job.id}")
                
                # Parse JSON payload
                data = json.loads(job.body)
                platform = data.get('platform', 'unknown')
                author = data.get('author_username', 'unknown')
                post_id = data.get('post_id', job.id)
                
                # Deterministic Object Key (Upsert Logic)
                month_folder = datetime.now().strftime("%Y-%m")
                filename = f"{platform}_{author}_{post_id}.json"
                folder_path = f"twitter/parsed/{month_folder}/"
                object_key = f"{folder_path}{filename}"
                
                # Load payload into Data Lake
                json_bytes = job.body.encode('utf-8')
                s3_client.put_object(
                    Bucket=BUCKET_NAME,
                    Key=object_key,
                    Body=json_bytes,
                    ContentType='application/json'
                )
                logger.info(f"Successfully loaded {object_key} into Silver layer bucket: {BUCKET_NAME}")
                
                # Acknowledge and delete job from queue
                client.delete(job)
                
            except json.JSONDecodeError:
                logger.error(f"Malformed JSON payload in Job {job.id}. Burying job.")
                client.bury(job)
            except Exception as e:
                logger.error(f"Worker encountered an error while processing job: {e}")
                time.sleep(5)

if __name__ == "__main__":
    start_worker()
