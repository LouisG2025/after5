
import re

def normalize_phone(phone_raw: str) -> str:
    """
    Normalizes a raw phone number strings into the 'whatsapp:+[digits]' internal format.
    Correctly handles leading '0' after international country codes (e.g. +971 058 -> 97158).
    """
    if not phone_raw:
        return ""

    # 1. Extract all digits
    digits = "".join(filter(str.isdigit, str(phone_raw)))
    
    # 2. List of common country codes that use a leading '0' for local dialing
    # which must be dropped in international format.
    # 971: UAE, 44: UK, 91: India, etc.
    country_codes = ["971", "44", "91", "1", "61", "92", "27", "49", "33"]
    
    for cc in country_codes:
        # Check if digits start with CC + '0'
        # Example: 971058 -> 97158
        if digits.startswith(cc + "0") and len(digits) > len(cc) + 1:
            digits = cc + digits[len(cc)+1:]
            break
            
    return f"whatsapp:+{digits}"
