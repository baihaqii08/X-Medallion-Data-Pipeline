import time
import subprocess
import logging
from datetime import datetime

# Configure standard logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Daily Cron Schedule (24-Hour Format: HH:MM)
JADWAL_SCRAPING = ["09:30", "11:00", "12:30", "14:00", "15:30", "16:50"]

def run_pipeline():
    """
    Executes the Extraction (Scraper) and Parsing (Data Cleaning) sequence.
    """
    logger.info("=======================================================")
    logger.info("INITIATING AUTOMATED EXTRACTION CYCLE")
    logger.info("=======================================================")
    
    # 1. Execute Extraction Node
    logger.info("Spawning twitter_batch_interceptor.py process...")
    subprocess.run([".venv\\Scripts\\python.exe", "twitter_batch_interceptor.py"])
    
    # 2. Execute Parser Node
    logger.info("Extraction complete. Spawning twitter_parser.py process...")
    subprocess.run([".venv\\Scripts\\python.exe", "twitter_parser.py"])
    
    logger.info("Extraction cycle finalized. Awaiting next scheduled cron trigger.")
    logger.info("=======================================================\n")

if __name__ == "__main__":
    logger.info("Pipeline Scheduler Initialized.")
    logger.info("Scheduled execution times:")
    for schedule in JADWAL_SCRAPING:
        logger.info(f"   -> {schedule}")
    
    logger.info("Ensure the minio_worker.py daemon is running to consume Beanstalkd queues.")
    logger.info("Polling clock for scheduled executions...")
    
    # Infinite polling loop
    while True:
        current_time = datetime.now().strftime("%H:%M")
        
        if current_time in JADWAL_SCRAPING:
            run_pipeline()
            # Sleep for 65 seconds to prevent multi-triggering within the same minute
            time.sleep(65) 
        else:
            time.sleep(20)
