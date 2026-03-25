
import pytest
from app.phone_utils import normalize_phone

def test_normalize_phone_uae():
    # User's case: +971 058...
    assert normalize_phone("+971 058 58 599 2301") == "whatsapp:+97158585992301"
    # Correct format already
    assert normalize_phone("+971 58 58 599 2301") == "whatsapp:+97158585992301"
    # No spaces
    assert normalize_phone("+971058585992301") == "whatsapp:+97158585992301"

def test_normalize_phone_uk():
    # UK case: +44 07700...
    assert normalize_phone("+44 07700 900000") == "whatsapp:+447700900000"
    assert normalize_phone("+44 7700 900000") == "whatsapp:+447700900000"

def test_normalize_phone_india():
    # India case: +91 09876...
    assert normalize_phone("+91 09876543210") == "whatsapp:+919876543210"
    assert normalize_phone("+91 9876543210") == "whatsapp:+919876543210"

def test_normalize_phone_no_cc():
    # If no country code, it just keeps digits
    assert normalize_phone("058 58 599 2301") == "whatsapp:+058585992301"

def test_normalize_phone_already_prepared():
    # If it's already digits
    assert normalize_phone("971058585992301") == "whatsapp:+97158585992301"

def test_normalize_phone_empty():
    assert normalize_phone("") == ""
    assert normalize_phone(None) == ""
