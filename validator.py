import re
import logging

# Configure standard logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Pattern boundary (\b) used to prevent false positives on substrings
# Categories covered: NSFW, Prostitution, Online Gambling, Scam Links, and Spam
BAD_WORDS_PATTERN = r'\b(open bo|bokep|bkep|porno|lendir|gacor|slot|judi|zeus|pragmatic|maxwin|pinjol|sange|ngewe|bokp|vcs|judol|bugil|telanjang|colmek|crot|desah|video syur|onlyfans|jablay|lonte|michat|rtp|scatter|fafafa|olympus|mahjong ways|depo|togel|sbobet|parlay|dana kaget|saldo dana|aplikasi penghasil uang|scandal|slutty|doodstream|uc-share|videy|hijab viral|dood|viral|gacha|jp|cdnvidey|cdn|terabox|tobrut|toge|pemersatu bangsa|link pemersatu|xnxx|xvideos|pornhub|jav|j4v|simontok|fap|jual konten|jual video)\b'

def is_content_valid(text: str) -> bool:
    """
    Data Quality Validator Rule Engine.
    Evaluates raw text against the negative keyword list to filter out NSFW/Spam.
    
    Args:
        text (str): The raw caption extracted from the social media payload.
        
    Returns:
        bool: True if the content passes validation, False if a violation is detected.
    """
    if not text:
        return False
        
    text_lower = text.lower()
    
    if re.search(BAD_WORDS_PATTERN, text_lower):
        return False
        
    return True

if __name__ == "__main__":
    logger.info("Initializing Unit Tests for Validator Engine...")
    
    # Positive Case
    safe_text = "Pemerintah sedang menangani kasus kebakaran hutan (Karhutla) di Kalimantan."
    logger.info(f"Test Case [SAFE]: Valid = {is_content_valid(safe_text)}")
    
    # Negative Case 1 (Gambling)
    spam_text_1 = "Ayo main slot gacor hari ini pasti maxwin broku!"
    logger.info(f"Test Case [GAMBLING]: Valid = {is_content_valid(spam_text_1)}")
    
    # Negative Case 2 (NSFW)
    spam_text_2 = "Open BO area jaksel rate 500k"
    logger.info(f"Test Case [NSFW]: Valid = {is_content_valid(spam_text_2)}")
    
    # False Positive Prevention Check (ensuring 'wujud' bypasses 'judi')
    edge_case_text = "Dia berhasil mewujudkan mimpinya menjadi nyata."
    logger.info(f"Test Case [EDGE CASE]: Valid = {is_content_valid(edge_case_text)}")
