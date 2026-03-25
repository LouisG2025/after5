import re

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
