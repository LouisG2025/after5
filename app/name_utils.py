import re
import unicodedata


def validate_name(name: str) -> bool:
    """
    Returns False if the name looks fake, gibberish, or unsuitable for use
    in an opener. Catches: repeated words, all caps multi-word, emoji-heavy,
    obvious test entries, single characters, and gibberish patterns.
    """
    if not name or not name.strip():
        return False

    cleaned = name.strip()

    # Too short (single char) or too long (probably garbage)
    if len(cleaned) < 2 or len(cleaned) > 50:
        return False

    # Contains emoji (any character in emoji Unicode categories)
    for ch in cleaned:
        if unicodedata.category(ch) in ("So", "Sk") or ord(ch) > 0x1F000:
            return False

    # All caps multi-word ("JOHN SMITH" is fine-ish, but "DIDDY DIDDY DIDDY" is not)
    words = cleaned.split()
    if len(words) > 1 and cleaned == cleaned.upper():
        return False

    # Repeated words: "Diddy Diddy Diddy", "test test"
    lower_words = [w.lower() for w in words]
    if len(lower_words) >= 2 and len(set(lower_words)) == 1:
        return False

    # Obvious test / gibberish entries
    test_names = [
        "test", "testing", "asdf", "qwerty", "aaa", "bbb", "xxx",
        "abc", "none", "null", "na", "n/a", "fake", "anonymous",
        "unknown", "admin", "user", "sample", "demo", "example",
    ]
    if cleaned.lower().rstrip(".!? ") in test_names:
        return False

    # Mostly non-letter characters (gibberish like "12345" or "!@#$%")
    letters = sum(1 for ch in cleaned if ch.isalpha())
    if letters < len(cleaned.replace(" ", "")) * 0.5:
        return False

    return True


def clean_personal_name(name: str) -> str:
    """
    Cleans and formats a personal name for natural display.
    - Trims extra spaces.
    - Strips 'from [Company]' if present.
    - Fixes capitalization (Title Case) if input is all caps or all lowercase.
    - Preserves mixed-case names (e.g. MacDonald).
    - Returns FIRST NAME ONLY for natural WhatsApp conversation.
    """
    if not name:
        return ""
    
    # Trim and remove extra internal spaces
    name = " ".join(name.split())
    
    # Handle "Name from Company" pattern
    if " from " in name.lower():
        parts = re.split(r'\s+from\s+', name, flags=re.IGNORECASE)
        if parts:
            name = parts[0]
    
    # Capitalization logic
    if name.isupper() or name.islower():
        name = name.title()
    
    # Extract first name only for natural conversation
    if name:
        name = name.split()[0]
    
    return name.strip()


def clean_company_name(company: str) -> str:
    """
    Cleans and formats a company name for natural conversation.
    - Trims extra spaces.
    - Removes legal suffixes (Ltd, LLC, Limited, Inc, etc.).
    - Fixes capitalization (Title Case) if input is all caps or all lowercase.
    """
    if not company:
        return ""
    
    # Trim and remove extra internal spaces
    company = " ".join(company.split())
    
    # List of legal suffixes to remove for display (case-insensitive)
    suffixes = [
        r'\bLTD\b\.?',
        r'\bLIMITED\b',
        r'\bLLC\b\.?',
        r'\bINC\b\.?',
        r'\bCORP\b\.?',
        r'\bCORPORATION\b',
        r'\bCO\b\.?',
        r'\bCOMPANY\b',
        r'\bL\.L\.C\b\.?',
        r'\bP\.?T\.?Y\b\.?',
        r'\bS\.?R\.?L\b\.?',
        r'\bS\.?A\.?P\.?A\b\.?'
    ]
    
    # Case-insensitive replacement of suffixes
    for pattern in suffixes:
        company = re.sub(pattern, '', company, flags=re.IGNORECASE).strip()
    
    # Remove any trailing commas that often precede the suffix
    company = company.rstrip(',').strip()
    
    # Handle "your business" default - don't title case it
    if company.lower() == "your business":
        return "your business"
    
    # Capitalization logic
    if company.isupper() or company.islower():
        company = company.title()
    
    return company.strip()
