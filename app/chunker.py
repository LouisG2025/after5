import re
import random
from app.config import settings

def chunk_message(text: str) -> list[str]:
    """
    Split LLM response into separate WhatsApp messages.
    Priority: ||| markers → [CHUNK] legacy → smart splitting → single message.
    HARD CAP: 5 chunks maximum.
    """
    text = text.strip()
    if not text:
        return [text]
    
    # 1. Priority: Explicit markers
    if "|||" in text:
        chunks = [c.strip() for c in text.split("|||") if c.strip()]
    elif "[CHUNK]" in text:
        chunks = [c.strip() for c in text.split("[CHUNK]") if c.strip()]
    else:
        # Pre-process for links, "Ps", and Greetings
        # Split after greeting: "Hey [Name]," or "Hi [Name]," followed by space and text
        greeting_match = re.match(r'^(Hey|Hi)\s+[A-Z][a-z]+,\s+', text)
        if greeting_match and len(text) > 40:
            end = greeting_match.end()
            text = text[:end] + "|||" + text[end:]
            return chunk_message(text)

        # Split before URL
        url_pattern = r'(https?://\S+)'
        urls = list(re.finditer(url_pattern, text))
        if urls:
            # Only split if the URL isn't already the start of the message
            first_url = urls[0]
            if first_url.start() > 5: # Some buffer
                text = text[:first_url.start()].strip() + "|||" + text[first_url.start():].strip()
                return chunk_message(text)

        # Split before "Ps" or "P.s." or "By the way"
        ps_match = re.search(r'\s+(Ps|P\.s\.|By the way)\s+', text, re.IGNORECASE)
        if ps_match:
            text = text[:ps_match.start()].strip() + "|||" + text[ps_match.start():].strip()
            return chunk_message(text)

        # 2. Human logic Fallback: Split at punctuation
        # We use a simple split and handle abbreviations later if needed, 
        # or just use a more compatible regex.
        raw_chunks = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current_chunk = ""
        
        for rc in raw_chunks:
            if not rc: continue
            rc = rc.strip()
            
            if not current_chunk:
                current_chunk = rc
            elif len(current_chunk) > 120 or current_chunk.endswith('?') or current_chunk.endswith('!'):
                chunks.append(current_chunk)
                current_chunk = rc
            else:
                current_chunk += f" {rc}"
        
        if current_chunk:
            chunks.append(current_chunk)

    # Final cleanup and hard cap
    chunks = [c.strip() for c in chunks if c.strip()]
    if len(chunks) > 5:
        chunks = chunks[:4] + [" ".join(chunks[4:])]
    
    return chunks or [text]


def calculate_typing_delay(text: str) -> float:
    """
    Calculate human-like delay.
    - Faster for short reflexive pings (<15 chars)
    - Normal for conversational text (~300 CPM)
    """
    char_count = len(text)
    
    # 300 CPM = 5 chars per second -> 0.2s per char
    # We add a small per-chunk overhead (thinking time)
    overhead = random.uniform(0.5, 1.2)
    base_typing = char_count * 0.15 # 400 CPM roughly
    
    total = overhead + base_typing
    
    # Caps and Floors
    if char_count < 15:
        # For very short strings, we reduce overhead and typing speed impact
        short_overhead = random.uniform(0.3, 0.7)
        total = short_overhead + (char_count * 0.05)
        return max(0.6, min(1.2, total))
    
    return max(1.2, min(5.0, total + random.uniform(-0.3, 0.3)))
