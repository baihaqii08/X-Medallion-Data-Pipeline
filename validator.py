import re

# Menggunakan regex boundaries (\b) agar tidak salah blokir kata yang mirip (misal: "wujud" tidak diblokir karena "judi")
# Kategori yang di-cover: Pornografi, Prostitusi (Michat/BO), Judi Online (Slot/Togel), Pinjol, dan Spam Link
BAD_WORDS_PATTERN = r'\b(open bo|bokep|bkep|porno|lendir|gacor|slot|judi|zeus|pragmatic|maxwin|pinjol|sange|ngewe|bokp|vcs|judol|bugil|telanjang|colmek|crot|desah|video syur|onlyfans|jablay|lonte|michat|rtp|scatter|fafafa|olympus|mahjong ways|depo|togel|sbobet|parlay|dana kaget|saldo dana|aplikasi penghasil uang|scandal|slutty|doodstream|uc-share|videy|hijab viral|dood|viral|gacha|jp|cdnvidey|cdn|terabox|tobrut|toge|pemersatu bangsa|link pemersatu|xnxx|xvideos|pornhub|jav|j4v|simontok|fap|jual konten|jual video)\b'

def is_content_valid(text: str) -> bool:
    """
    Data Validator Rule Engine.
    Memvalidasi apakah teks aman dari kata-kata terlarang (NSFW, Spam, Judi).
    
    Returns:
        bool: True jika teks aman, False jika mengandung pelanggaran.
    """
    if not text:
        return False
        
    # Normalisasi teks ke huruf kecil untuk pengecekan
    text_lower = text.lower()
    
    # Pencarian pola (pattern matching)
    if re.search(BAD_WORDS_PATTERN, text_lower):
        return False
        
    return True

if __name__ == "__main__":
    # Unit Testing sederhana
    print("Mencoba Rule Engine Validator...")
    print("Aman:", is_content_valid("Pemerintah sedang menangani kasus kebakaran hutan (Karhutla) di Kalimantan."))
    print("Kotor:", is_content_valid("Ayo main slot gacor hari ini pasti maxwin broku!"))
    print("Kotor:", is_content_valid("Open BO area jaksel rate 500k"))
    print("Aman:", is_content_valid("Dia berhasil mewujudkan mimpinya menjadi nyata.")) # Memastikan 'wujud' lolos dari filter 'judi'
