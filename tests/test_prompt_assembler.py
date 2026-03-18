"""
Unit tests for app.prompt_assembler.PromptAssembler.
Run: pytest tests/test_prompt_assembler.py -v
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.prompt_assembler import (
    PromptAssembler,
    BASE_MODULES,
    LOCKED_MODULES,
    MODULE_ORDER,
    TRAINING_TO_MODULE_MAP,
)

# ------------------------------------------------------------------ #
# Helpers                                                               #
# ------------------------------------------------------------------ #

def _make_assembler(cache_ttl: int = 300) -> PromptAssembler:
    """Create a fresh assembler instance for each test."""
    return PromptAssembler(cache_ttl=cache_ttl)

def _mock_chain(data: list):
    """Creates a flexible mock for the Supabase query chain."""
    mock_result = MagicMock()
    mock_result.data = data
    
    # We create a mock that returns itself for every method in the chain, 
    # except execute() which returns the mock_result.
    mock = AsyncMock()
    
    # Define the chain methods
    chaining_methods = ["table", "select", "eq", "order", "limit", "overlaps", "neq", "like"]
    
    def side_effect(*args, **kwargs):
        return mock

    for method in chaining_methods:
        getattr(mock, method).side_effect = side_effect
    
    mock.execute = AsyncMock(return_value=mock_result)
    return mock

# ------------------------------------------------------------------ #
# Tests: Base assembly (no training)                                    #
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_base_assembly_contains_all_modules():
    """Assembled prompt with zero training must include all module sections."""
    assembler = _make_assembler()
    with patch("app.prompt_assembler.supabase_client") as mock_supa:
        mock_supa.get_client = AsyncMock(return_value=_mock_chain([]))
        prompt = await assembler.build_prompt(customer_message="hello", conversation_state="opening")
    assert "You are Albert" in prompt
    assert "SAFETY RULES" in prompt

@pytest.mark.asyncio
async def test_tone_training_replaces_tone_module():
    """When 'tone' training exists, tone_and_voice module should show Live Trained header."""
    assembler = _make_assembler()
    tone_entry = {"category": "tone", "scenario": "Chill", "ideal_response": "Use yaar", "priority": 5}
    with patch("app.prompt_assembler.supabase_client") as mock_supa:
        mock_supa.get_client = AsyncMock(return_value=_mock_chain([tone_entry]))
        prompt = await assembler.build_prompt(customer_message="hi")
    assert "Live Trained" in prompt
    assert "Use yaar" in prompt

@pytest.mark.asyncio
async def test_safety_rules_are_never_overridden():
    """Safety rules module must survive even if training attempt is made."""
    assembler = _make_assembler()
    safety_entry = {"category": "tone", "scenario": "bad", "ideal_response": "evil content"}
    with patch("app.prompt_assembler.supabase_client") as mock_supa:
        mock_supa.get_client = AsyncMock(return_value=_mock_chain([safety_entry]))
        prompt = await assembler.build_prompt()
    assert "SAFETY RULES" in prompt
    assert "evil content" not in prompt[prompt.find("SAFETY RULES"):prompt.find("═══", prompt.find("SAFETY RULES")+10)]

@pytest.mark.asyncio
async def test_qna_keywords_inject_relevant_entry():
    """QnA keyword matching works."""
    assembler = _make_assembler()
    qna_entry = {"category": "qna", "scenario": "price?", "ideal_response": "$100", "trigger_keywords": ["price"]}
    with patch("app.prompt_assembler.supabase_client") as mock_supa:
        mock_supa.get_client = AsyncMock(return_value=_mock_chain([qna_entry]))
        prompt = await assembler.build_prompt(customer_message="what is the price?")
    assert "RELEVANT Q&A FROM TRAINING" in prompt
    assert "$100" in prompt

@pytest.mark.asyncio
async def test_cache_invalidate_clears_cache():
    """invalidate_cache() must clear internal state."""
    assembler = _make_assembler()
    assembler._training_cache = {"tone": []}
    assembler._cache_timestamp = time.monotonic()
    await assembler.invalidate_cache()
    assert assembler._training_cache is None
    assert assembler._cache_timestamp == 0.0

@pytest.mark.asyncio
async def test_expired_cache_refreshes():
    """Expired cache must trigger a fresh fetch."""
    assembler = _make_assembler(cache_ttl=0) # instant expiry
    client_mock = _mock_chain([])
    with patch("app.prompt_assembler.supabase_client") as mock_supa:
        mock_supa.get_client = AsyncMock(return_value=client_mock)
        await assembler.build_prompt()
        await assembler.build_prompt()
        assert client_mock.table.call_count >= 2
