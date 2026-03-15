import re

def clean_response(response_text: str) -> str:
    """Same regex as implemented in app/conversation.py"""
    return re.sub(r'\[[A-Z\s_]+:?.*?\]', '', response_text).strip()

def test_cleaning():
    test_cases = [
        ("Hello mate! [SYSTEM ACTION: SET STATE TO CLOSED]", "Hello mate!"),
        ("Sounds good. [SYSTEM_ACTION: BOOKED]", "Sounds good."),
        ("Actually, I think we have crossed wires. [SYSTEM ACTION: CLOSED] Take care.", "Actually, I think we have crossed wires.  Take care."),
        ("No tags here.", "No tags here."),
        ("[SYSTEM ACTION] Leading tag", "Leading tag"),
        ("Wait... [no_reply]", "Wait... [no_reply]"), # Lowercase shouldn't match A-Z regex unless specified, but we want to catch casing variations if we used [a-z] or case-insensitive flag.
    ]
    
    # Let's refine the regex in the test to match the case-insensitive [NO_REPLY] if needed, 
    # but the current implementation in app/conversation.py uses a separate check for [NO_REPLY].
    
    for input_text, expected in test_cases:
        actual = clean_response(input_text)
        print(f"Input:    {input_text}")
        print(f"Expected: {expected}")
        print(f"Actual:   {actual}")
        assert actual == expected or actual.replace("  ", " ") == expected
        print("✅ Passed")

if __name__ == "__main__":
    test_cleaning()
    print("\nAll cleaning tests passed!")
