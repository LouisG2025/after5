import re
import random
import time
from app.config import settings


_CONTINUATION_STARTERS = (
    "so ", "and ", "but ", "or ", "which ", "where ", "because ",
    "though ", "still ", "also ", "just ", "plus ", "anyway",
)


def _looks_like_continuation(chunk: str) -> bool:
    """A chunk grammatically continues the prior message when it both:
      1. opens with a connector word (so/and/but/which/etc), AND
      2. is short (< 80 chars) and not a question.
    Both conditions must hold — being lowercase alone isn't enough to override
    an explicit ||| from the LLM. This catches the client's case
    ('so your reps only deal with serious people') without over-merging
    legitimate two-bubble replies.
    """
    if not chunk:
        return False
    if len(chunk) > 80:
        return False
    if chunk.rstrip().endswith("?"):
        return False
    low = chunk.lstrip().lower()
    return low.startswith(_CONTINUATION_STARTERS)


def _merge_continuations(chunks: list[str]) -> list[str]:
    """Post-processor guardrail. If the LLM split a thought into two chunks
    where the second chunk is a short trailing clause, fold it back into the
    first with a blank line. This is the formatting-vs-chunking fix the client
    asked for: 'so your reps only deal with people who are actually serious'
    must stay in the same bubble as the preceding statement."""
    if len(chunks) < 2:
        return chunks
    merged: list[str] = [chunks[0]]
    for nxt in chunks[1:]:
        # Never absorb a link into a prior bubble — links earn their own bubble
        if re.search(r"https?://", nxt):
            merged.append(nxt)
            continue
        if _looks_like_continuation(nxt):
            merged[-1] = merged[-1].rstrip() + "\n\n" + nxt.lstrip()
        else:
            merged.append(nxt)
    return merged


def chunk_message(text: str, is_template: bool = False) -> list[str]:
    """
    Split LLM response into separate WhatsApp messages.
    Priority: ||| markers → [CHUNK] legacy → URL/PS pre-split → single message.
    HARD CAP: 3 chunks maximum.

    Double newlines (\\n\\n) are formatting WITHIN a bubble, NOT chunk
    boundaries. Splitting on them was the source of over-chunking — the LLM
    uses paragraph breaks for readability inside one message.

    If is_template is True, bypass all chunking and return as-is.
    """
    text = text.strip()
    if not text:
        return [text]

    # Template bypass: never chunk the intro template
    if is_template:
        return [text]

    # 1. Priority: Explicit markers
    if "|||" in text:
        chunks = [c.strip() for c in text.split("|||") if c.strip()]
    elif "[CHUNK]" in text:
        chunks = [c.strip() for c in text.split("[CHUNK]") if c.strip()]
    else:
        # Pre-process for links — links always earn their own bubble
        url_pattern = r'(https?://\S+)'
        urls = list(re.finditer(url_pattern, text))
        if urls:
            first_url = urls[0]
            if first_url.start() > 5:
                text = text[:first_url.start()].strip() + "|||" + text[first_url.start():].strip()
                return chunk_message(text)
        # Split before "Ps" or "P.s." or "By the way" — these are afterthoughts
        ps_match = re.search(r'\s+(Ps|P\.s\.|By the way)\s+', text, re.IGNORECASE)
        if ps_match:
            text = text[:ps_match.start()].strip() + "|||" + text[ps_match.start():].strip()
            return chunk_message(text)
        # No explicit chunk marker → ONE bubble. Paragraph breaks (\n\n) are
        # formatting, not chunks. Trust the LLM's |||.
        chunks = [text]

    # Post-processor: merge short trailing continuations back into prior bubble
    chunks = _merge_continuations(chunks)

    # Final cleanup and hard cap
    chunks = [c.strip() for c in chunks if c.strip()]
    if len(chunks) > 3:
        chunks = chunks[:2] + [" ".join(chunks[2:])]

    return chunks or [text]


# Safety-net patterns for AI self-disclosure leakage.
# Per Louis's brief: Albert must never volunteer that he's AI unless directly asked.
# These patterns strip the offending phrase when the LLM leaks them unprompted.
_AI_DISCLOSURE_PATTERNS = [
    r"\b(?:i'?m|i am)\s+(?:an?\s+)?(?:ai|a\s+bot|a\s+robot|a\s+chatbot|an?\s+assistant|an?\s+automated|a\s+computer|a\s+program|a\s+system)\b[^.!?]*[.!?]?",
    r"\b(?:yeah|haha|actually|honestly|to be fair|tbh),?\s+i'?m\s+(?:ai|a\s+bot|a\s+robot|a\s+chatbot)\b[^.!?]*[.!?]?",
    r"\bas an ai\b[^.!?]*[.!?]?",
    r"\b(?:yes|yeah|nope|no),?\s+(?:i'?m|i am)\s+(?:ai|a\s+bot|a\s+robot|a\s+chatbot)\b[^.!?]*[.!?]?",
    r"\b(?:albert|i)\s+(?:is|am)\s+(?:ai|an ai|a bot|a robot|a chatbot)\b[^.!?]*[.!?]?",
]


_USER_ASKED_ABOUT_AI_PATTERNS = [
    r"\bare you (?:an? )?(?:ai|bot|robot|chatbot|human|real|person|automated|machine|computer)\b",
    r"\bis this (?:an? )?(?:ai|bot|chatbot|automated)\b",
    r"\bam i (?:talking|chatting|speaking) (?:to|with) (?:an? )?(?:ai|bot|robot|human|real person|machine)\b",
    r"\byou (?:a |an )?(?:ai|bot|robot|chatbot|computer|machine)\??$",
    r"\breal person\b",
    r"\bwho am i (?:talking|speaking) to\b",
]


def user_asked_about_ai(user_message: str) -> bool:
    """Return True if the lead's message is directly asking whether Albert is AI/bot."""
    if not user_message:
        return False
    low = user_message.lower()
    for pattern in _USER_ASKED_ABOUT_AI_PATTERNS:
        if re.search(pattern, low):
            return True
    return False


def strip_ai_disclosure(text: str, user_asked: bool = False) -> str:
    """
    Strip unsolicited AI self-disclosure from Albert's replies.

    Per Louis's brief (system_prompt.txt line 537):
      "If they don't ask, don't volunteer it."

    When user_asked=True, the lead directly asked "are you AI?" so Albert
    is allowed to acknowledge. The filter is a no-op in that case.

    Otherwise we strip any self-disclosure phrases that slipped past the
    prompt so Albert never volunteers his AI status unprompted.
    """
    if not text:
        return text
    if user_asked:
        return text  # Albert is allowed to acknowledge when directly asked

    cleaned = text
    for pattern in _AI_DISCLOSURE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    # Collapse whitespace + dangling punctuation left behind
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"^[\s,.!?]+", "", cleaned)
    cleaned = cleaned.strip()
    # If stripping gutted the whole message, fall back to a safe redirect
    if not cleaned or len(cleaned) < 4:
        return "anyway, what would you like to know"
    return cleaned


def format_message(text: str, is_template: bool = False, last_user_message: str = "") -> str:
    """
    Format a single message bubble for readability within WhatsApp.
    Adds line breaks between distinct thoughts within one message.
    This is FORMATTING not CHUNKING. The message stays as one bubble.

    If is_template is True, bypass all formatting and return as-is.

    If last_user_message is provided, AI disclosure stripping becomes
    context-aware (allowed when the lead directly asked about AI).

    Rules:
    - 1 to 2 sentences pass through untouched
    - 3+ sentences get line breaks between thought groups
    - Questions always get their own line at the end
    - Drop the full stop from the very last sentence
    - Preserve any intentional line breaks from the LLM
    """
    text = text.strip()
    if not text:
        return text

    # Template bypass: never reformat the intro template
    if is_template:
        return text

    # Strip unsolicited AI self-disclosure (safety net per Louis's brief).
    # Skipped if the lead directly asked whether we're AI.
    text = strip_ai_disclosure(text, user_asked=user_asked_about_ai(last_user_message))

    # If LLM already included line breaks, preserve their intent.
    # \n\n in the source = paragraph gap (keep as-is)
    # single \n = soft break, keep as single (no escalation to double)
    if "\n" in text:
        # Normalise: collapse 3+ newlines to exactly 2; keep singles as singles
        import re as _re
        normalised = _re.sub(r"\n{3,}", "\n\n", text)
        # Drop trailing full stop on the last non-empty line
        parts = normalised.rstrip().rsplit("\n", 1)
        if parts[-1].endswith("."):
            parts[-1] = parts[-1][:-1]
        return "\n".join(parts) if len(parts) > 1 else parts[0]

    # Split into sentences for processing
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    # Sub-process long sentences to split run-ons with internal line breaks
    processed_sentences = []
    
    def recursive_split(s: str) -> list[str]:
        if len(s) <= 100 or s.rstrip().endswith("?"):
            return [s]
        
        # Look for logical break points (and, but, so, which, where, or, specifically, especially)
        break_patterns = [
            r'\s+and\s+', r'\s+but\s+', r'\s+so\s+', r'\s+which\s+', 
            r'\s+where\s+', r'\s+or\s+', r',\s+(?:some|sometimes|especially|specifically|including)\s+'
        ]
        for pattern in break_patterns:
            matches = list(re.finditer(pattern, s, re.IGNORECASE))
            if matches:
                # Find the most "central" match to split on
                best_match = min(matches, key=lambda m: abs(m.start() - len(s)/2))
                if best_match.start() > 30 and best_match.start() < len(s) - 30:
                    split_idx = best_match.start()
                    # If splitting on a comma, keep comma with part 1
                    if s[split_idx] == ',':
                        split_idx += 1
                    
                    part1 = s[:split_idx].strip()
                    part2 = s[split_idx:].strip()
                    return recursive_split(part1) + recursive_split(part2)
        return [s]

    for s in sentences:
        processed_sentences.extend(recursive_split(s))
    
    sentences = processed_sentences

    # Only auto-paragraph if the message is genuinely long (3+ parts AND
    # >180 chars). Short 1-2 sentence replies stay as a single block per
    # prompt rule "Keep messages to 1 to 2 sentences for most replies."
    total_len = sum(len(s) for s in sentences) + len(sentences)
    if len(sentences) >= 3 and total_len > 180:
        paragraphs = []
        current_para = []

        for i, sentence in enumerate(sentences):
            is_last = (i == len(sentences) - 1)
            is_question = sentence.rstrip().endswith("?")
            
            # If a part is very long, it deserves its own paragraph regardless
            is_very_long = len(sentence) > 80

            # Questions get their own paragraph
            if is_question and current_para:
                paragraphs.append(" ".join(current_para))
                current_para = [sentence]
            elif is_very_long and current_para:
                paragraphs.append(" ".join(current_para))
                current_para = [sentence]
            else:
                current_para.append(sentence)

            # Break into new paragraph every 1-2 parts to keep it scannable
            # If current_para is long or has 2 items, break it
            if (len(current_para) >= 2 or (current_para and len(current_para[0]) > 80)) and not is_last and not is_question:
                paragraphs.append(" ".join(current_para))
                current_para = []

        if current_para:
            paragraphs.append(" ".join(current_para))

        # Join paragraphs with blank line
        result = "\n\n".join(paragraphs)
    else:
        # 1 part: join normally
        result = " ".join(sentences)

    # Drop full stop from the very last character
    if result.endswith("."):
        result = result[:-1]

    return result


def aggregate_messages(buffer: list[str]) -> str:
    """
    Combine multiple incoming messages into one input string.

    When a lead sends multiple messages in quick succession,
    they should be aggregated into one combined input and
    processed as a single LLM call.

    The caller should implement a 5 second silence timer:
    - Message arrives, start 5 second timer
    - If more messages arrive, reset timer to 5 seconds
    - Once 5 seconds of silence passes, call this function
    - Feed the combined result into the LLM as one input
    """
    if not buffer:
        return ""
    return " ".join([msg.strip() for msg in buffer if msg.strip()])


def calculate_blue_tick_delay(last_lead_message_time: float, current_time: float) -> float:
    """Delay before marking the lead's message as read. Minimal delay."""
    gap = current_time - last_lead_message_time

    if gap < 60:
        return random.uniform(0.3, 0.6)
    return random.uniform(0.5, 1.0)


def calculate_reading_delay(incoming_text: str) -> float:
    """Minimal reading delay - just enough to not seem instant."""
    text = (incoming_text or "").strip()
    char_count = len(text)

    if char_count <= 20:
        return random.uniform(0.3, 0.5)
    elif char_count < 100:
        return random.uniform(0.5, 0.8)
    else:
        return random.uniform(0.8, 1.2)


def calculate_typing_delay(text: str, is_first_chunk: bool = True) -> float:
    """Minimal typing delay - quick responses."""
    char_count = len(text)

    if char_count < 30:
        return random.uniform(0.4, 0.7)
    elif char_count < 80:
        return random.uniform(0.6, 1.0)
    else:
        return random.uniform(0.8, 1.5)


def calculate_think_pause() -> float:
    """Minimal think pause."""
    return random.uniform(0.1, 0.3)


def calculate_review_pause() -> float:
    """Minimal review pause."""
    return random.uniform(0.05, 0.15)


def calculate_full_sequence(incoming_text: str, outgoing_text: str, last_lead_message_time: float, current_time: float) -> dict:
    """
    Calculate the full timing sequence for a single message reply.
    Returns dict with each step's delay for the caller to execute in order.

    The caller should execute these stages in order:

    1. Aggregation: Wait for 5 seconds of silence (handled externally)
    2. Blue tick + LLM call: Fire both simultaneously
    3. Reading delay: Visible pause, LLM generating in parallel
    4. Think pause: 1 second before typing starts
    5. Typing: Cosmetic duration, overlaps with LLM if still generating
    6. Review pause: 0.5 second before sending
    7. Send

    Poll should_interrupt() every 500ms throughout stages 2-7.
    """
    return {
        "blue_tick_delay": calculate_blue_tick_delay(last_lead_message_time, current_time),
        "reading_delay": calculate_reading_delay(incoming_text),
        "think_pause": calculate_think_pause(),
        "typing_delay": calculate_typing_delay(outgoing_text),
        "review_pause": calculate_review_pause(),
    }


def calculate_chunk_sequence(incoming_text: str, chunks: list[str], last_lead_message_time: float, current_time: float) -> list[dict]:
    """
    Calculate the full timing sequence for a multi-chunk reply.

    First chunk gets the full sequence:
    blue_tick → reading → think_pause → typing → review_pause → send

    Subsequent chunks get ONLY typing delay:
    typing indicator drops for a split second → comes back on →
    types for character-based duration → sends immediately.
    No reading delay, no think pause, no review pause between chunks.

    IMPORTANT: Call should_interrupt() between each chunk.
    If lead sent a new message, cancel remaining chunks and reprocess.
    """
    if not chunks:
        return []

    sequences = []

    # First chunk gets the full sequence
    sequences.append({
        "blue_tick_delay": calculate_blue_tick_delay(last_lead_message_time, current_time),
        "reading_delay": calculate_reading_delay(incoming_text),
        "think_pause": calculate_think_pause(),
        "typing_delay": calculate_typing_delay(chunks[0], is_first_chunk=True),
        "review_pause": calculate_review_pause(),
    })

    # Subsequent chunks: typing only, capped lower so continuations land fast
    for chunk in chunks[1:]:
        sequences.append({
            "blue_tick_delay": 0,
            "reading_delay": 0,
            "think_pause": 0,
            "typing_delay": calculate_typing_delay(chunk, is_first_chunk=False),
            "review_pause": 0,
        })

    return sequences


def should_interrupt(
    lead_is_typing: bool,
    lead_sent_new_message: bool,
    typing_start_time: float,
    typing_stop_time: float,
    max_typing_wait: float = 20.0,
    typing_silence_threshold: float = 5.0
) -> str:
    """
    Determine whether Albert should interrupt his current response.
    Poll this every 500ms throughout the ENTIRE response sequence
    (reading delay, think pause, typing, review pause, between chunks).

    Parameters:
        lead_is_typing: Is the lead currently showing a typing indicator
        lead_sent_new_message: Did the lead send a new message
        typing_start_time: Timestamp when lead first started typing (0 if not typing)
        typing_stop_time: Timestamp when lead last showed typing activity (0 if not typing)
        max_typing_wait: Max seconds to wait for lead to finish typing (default 20)
        typing_silence_threshold: Seconds of no typing before resuming (default 5)

    Returns:
        - "reprocess": Lead sent a new message. Cancel everything.
          Add new message to aggregation buffer. Reset 5 second silence
          timer. Go back to stage 1 and reprocess with full conversation
          history including the new message.

        - "pause": Lead is typing. Albert should:
          1. Immediately remove typing indicator
          2. Wait and keep polling. One of three things will happen:
             a. Lead sends a message → next poll returns "reprocess"
             b. Lead stops typing for 5+ seconds → next poll returns "resume"
             c. Lead types for 20+ seconds without sending → returns "resume"

        - "resume": Lead stopped typing without sending, or timed out.
          Albert should resume from where he paused. If typing indicator
          was showing before, turn it back on and continue.

        - "continue": No interruption detected. Keep going with current step.
    """
    current_time = time.time()

    # New message always triggers full reprocess
    if lead_sent_new_message:
        return "reprocess"

    # Lead is actively typing right now
    if lead_is_typing:
        # Check if they've been typing longer than max wait
        if typing_start_time > 0:
            typing_duration = current_time - typing_start_time
            if typing_duration >= max_typing_wait:
                return "resume"
        return "pause"

    # Lead is NOT typing right now but WAS typing recently
    if typing_stop_time > 0:
        silence_since_typing = current_time - typing_stop_time
        if silence_since_typing >= typing_silence_threshold:
            # They stopped typing for 5+ seconds without sending, resume
            return "resume"
        # Still within the 5 second window, keep pausing
        return "pause"

    return "continue"
