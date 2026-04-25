import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from app.chunker import chunk_message, calculate_typing_delay

def test_chunking():
    print("\n--- Testing Chunking Logic ---")
    
    # Test 1: Simple message
    msg1 = "Hey, how can I help you today?"
    chunks1 = chunk_message(msg1)
    print(f"Simple: {chunks1}")
    assert len(chunks1) == 1
    
    # Test 2: ||| marker
    msg2 = "Gotcha, that makes sense|||I think we can help with that|||Any questions?"
    chunks2 = chunk_message(msg2)
    print(f"Markers: {chunks2}")
    assert len(chunks2) == 3
    
    # Test 3: [CHUNK] legacy
    msg3 = "First thought[CHUNK]Second thought"
    chunks3 = chunk_message(msg3)
    print(f"Legacy: {chunks3}")
    assert len(chunks3) == 2
    
    # Test 4: Long message WITHOUT explicit markers — per brief, Albert only splits
    # on explicit ||| markers. Length-based auto-splitting was intentionally removed.
    # The chunker should trust the LLM decision and return a single chunk.
    msg4 = (
        "This is a first sentence that is quite long and rambling. "
        "This is a second sentence that adds even more detail to the conversation. "
        "This is a third sentence to ensure we have enough content to trigger the length threshold. "
        "This is a fourth sentence, just for good measure, to make sure it definitely hits the 200 character limit of our chunking logic."
    )
    chunks4 = chunk_message(msg4)
    print(f"Long message without markers (length {len(msg4)}): {len(chunks4)} chunk(s)")
    assert len(chunks4) == 1, "Long messages without ||| markers should stay as one chunk"
    
    # Test 5: Hard cap 3
    msg5 = "One|||Two|||Three|||Four|||Five"
    chunks5 = chunk_message(msg5)
    print(f"Hard cap: {chunks5}")
    assert len(chunks5) <= 3
    
    # Test 6: Typing delay — realistic human phone-typing speed (~20 chars/sec)
    # 18-char message: floor 1.5s for short replies, capped at 2.5s
    delay = calculate_typing_delay("How are you today?")
    print(f"Delay for 'How are you today?': {delay:.2f}s")
    assert 1.2 <= delay <= 2.6, f"Short reply at human pace, got {delay:.2f}s"

if __name__ == "__main__":
    test_chunking()
