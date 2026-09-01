import os
import glob
import json
import uuid
import time
import gzip
import shutil
import logging
from datetime import datetime
import greenstalk
from validator import is_content_valid

# Configure standard logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Beanstalkd Configuration
BEANSTALKD_HOST = '127.0.0.1'
BEANSTALKD_PORT = 11300
TUBE_NAME = 'raw-data'

def find_tweets(obj, results, trend_topic_context="Unknown"):
    """
    Recursively traverse the GraphQL JSON payload to extract valid tweet objects.
    """
    if isinstance(obj, dict):
        if 'legacy' in obj and 'full_text' in obj['legacy']:
            if trend_topic_context:
                obj['_trend_topic_context'] = trend_topic_context
            results.append(obj)
        
        current_trend = obj.get('trend', trend_topic_context)
            
        for k, v in obj.items():
            find_tweets(v, results, current_trend)
    elif isinstance(obj, list):
        for item in obj:
            find_tweets(item, results, trend_topic_context)

def get_latest_batch_file():
    """
    Retrieves the most recent JSON batch file from the Bronze layer.
    """
    raw_dir = os.path.join(os.getcwd(), "raw_batches")
    files = glob.glob(os.path.join(raw_dir, "twitter-batch-*.json"))
    if not files:
        return None
    return max(files, key=os.path.getctime)

def parse_and_publish():
    """
    Main parsing logic: reads raw data, normalizes it, and publishes to the message queue.
    """
    batch_file = get_latest_batch_file()
    if not batch_file:
        logger.warning("No raw batch files found in the Bronze layer.")
        return

    logger.info(f"Processing Bronze batch file: {batch_file}")
    with open(batch_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    logger.info("Extracting tweet entities from GraphQL nodes...")
    raw_tweets = []
    find_tweets(data, raw_tweets)
    
    # Deduplicate within the current batch using REST ID
    unique_tweets = {t['rest_id']: t for t in raw_tweets if 'rest_id' in t}
    logger.info(f"Extracted {len(unique_tweets)} unique tweets from the batch.")
    
    logger.info(f"Establishing connection to Beanstalkd broker at {BEANSTALKD_HOST}:{BEANSTALKD_PORT}...")
    try:
        queue_client = greenstalk.Client((BEANSTALKD_HOST, BEANSTALKD_PORT), use=TUBE_NAME)
    except Exception as e:
        logger.error(f"Failed to connect to message broker: {e}")
        return

    success_count = 0
    for tweet_id, tweet in unique_tweets.items():
        legacy = tweet.get('legacy', {})
        text = legacy.get('full_text', '')
        
        if not text:
            continue
            
        # [DATA QUALITY] Content Validation
        if not is_content_valid(text):
            logger.debug(f"Filtered out tweet {tweet_id} due to NSFW/Spam content.")
            continue
            
        # Metadata Extraction
        likes = legacy.get('favorite_count', 0)
        comments = legacy.get('reply_count', 0)
        shares = legacy.get('retweet_count', 0)
        views_dict = tweet.get('views', {})
        views = int(views_dict.get('count', 0)) if isinstance(views_dict, dict) and views_dict.get('count') else 0
        
        # Author Extraction
        author = "unknown"
        try:
            user_result = tweet.get('core', {}).get('user_results', {}).get('result', {})
            if 'core' in user_result and 'screen_name' in user_result['core']:
                author = user_result['core']['screen_name']
            elif 'legacy' in user_result and 'screen_name' in user_result['legacy']:
                author = user_result['legacy']['screen_name']
        except Exception:
            pass
            
        hashtags = [word for word in text.split() if word.startswith('#')]
        
        # Timestamp Normalization
        try:
            posted_at_dt = datetime.strptime(legacy.get('created_at', ''), "%a %b %d %H:%M:%S %z %Y")
            timestamp = int(posted_at_dt.timestamp())
        except:
            timestamp = int(time.time())
            
        parsed_at = int(time.time())
        url = f"https://x.com/{author}/status/{tweet_id}"
        
        # Target Unified Schema (Silver Layer Format)
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
            "trend_topic": tweet.get('_trend_topic_context', 'GraphQL Batch'),
            "hashtags": hashtags
        }
        
        # Publish to Message Queue
        json_payload = json.dumps(post_data)
        job_id = queue_client.put(json_payload)
        success_count += 1
        logger.debug(f"Published Job ID {job_id} to queue (Author: {author})")
        
    queue_client.close()
    logger.info(f"Parsing complete. Successfully published {success_count} normalized payloads to Beanstalkd.")
    
    # --- BRONZE LAYER COMPRESSION (GZIP) ---
    logger.info("Initiating compression of the processed raw batch...")
    compressed_filename = batch_file + ".gz"
    try:
        with open(batch_file, 'rb') as f_in:
            with gzip.open(compressed_filename, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        os.remove(batch_file)
        logger.info(f"Compression successful. Archived file: {compressed_filename}")
    except Exception as e:
        logger.error(f"Compression failed for {batch_file}: {e}")

if __name__ == "__main__":
    parse_and_publish()
