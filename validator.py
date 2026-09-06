import re
from dataclasses import dataclass


VALIDATION_MODES = {"observe", "balanced", "strict"}

# Balanced mode blocks strong promotional/solicitation signals, while retaining
# legitimate reporting about sensitive topics such as online gambling.
BLOCK_RULES = {
    "sexual_solicitation": re.compile(
        r"\b(open\s+bo|jual\s+(?:konten|video)|vcs\s+(?:murah|private)|"
        r"bokep\s+(?:full|gratis)|link\s+(?:bokep|porno))\b",
        re.IGNORECASE,
    ),
    "gambling_promotion": re.compile(
        r"\b(slot\s+gacor|pasti\s+maxwin|rtp\s+slot|link\s+slot|"
        r"depo(?:sit)?\s+(?:minimal|minim|mulai|\d+)|daftar\s+(?:slot|togel))\b",
        re.IGNORECASE,
    ),
    "known_adult_link": re.compile(
        r"(?:https?://)?(?:www\.)?(?:xnxx|xvideos|pornhub)\.[a-z]{2,}",
        re.IGNORECASE,
    ),
}

CATEGORY_RULES = {
    "nsfw_reference": re.compile(
        r"\b(open\s+bo|bokep|porno|vcs|bugil|telanjang|video\s+syur|"
        r"onlyfans|jual\s+konten|xnxx|xvideos|pornhub)\b",
        re.IGNORECASE,
    ),
    "gambling_reference": re.compile(
        r"\b(slot|judi|judol|gacor|maxwin|rtp|togel|sbobet|parlay|scatter)\b",
        re.IGNORECASE,
    ),
    "financial_spam_reference": re.compile(
        r"\b(pinjol|dana\s+kaget|saldo\s+dana|aplikasi\s+penghasil\s+uang)\b",
        re.IGNORECASE,
    ),
    "ambiguous_spam_reference": re.compile(
        r"\b(viral|cdn|depo|gacha|terabox|scandal)\b",
        re.IGNORECASE,
    ),
}


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    flags: tuple[str, ...] = ()
    reason: str | None = None


def _matched_rules(text: str, rules: dict[str, re.Pattern]) -> tuple[str, ...]:
    return tuple(name for name, pattern in rules.items() if pattern.search(text))


def validate_content(text: str, mode: str = "balanced") -> ValidationResult:
    """Validate content without silently discarding useful narrative data.

    observe: retain all non-empty content and attach quality flags.
    balanced: block only strong promotional/solicitation rules.
    strict: block any content matching a sensitive category.
    """
    if mode not in VALIDATION_MODES:
        raise ValueError(f"Unknown validation mode {mode!r}; choose from {sorted(VALIDATION_MODES)}")

    if not text or not text.strip():
        return ValidationResult(valid=False, reason="empty_content")

    flags = _matched_rules(text, CATEGORY_RULES)
    blocked_rules = _matched_rules(text, BLOCK_RULES)

    if mode == "strict" and flags:
        return ValidationResult(valid=False, flags=flags, reason=f"strict:{flags[0]}")
    if mode == "balanced" and blocked_rules:
        return ValidationResult(valid=False, flags=flags, reason=blocked_rules[0])
    return ValidationResult(valid=True, flags=flags)


def is_content_valid(text: str, mode: str = "balanced") -> bool:
    """Compatibility wrapper for callers that only need a Boolean result."""
    return validate_content(text, mode=mode).valid
