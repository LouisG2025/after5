import asyncio
import os
import sys
from unittest.mock import AsyncMock

import pytest

# Add project root to path
sys.path.append(os.getcwd())


@pytest.mark.asyncio
async def test_buffering():
    print("\n--- Testing Buffering Logic ---")
    
    # Mock redis_client
    from app.redis_client import redis_client
    original_redis = redis_client.redis
    
    # Create a wrapper that uses a real dictionary for storage
    store = {}
    
    mock_redis = AsyncMock()
    mock_redis.set.side_effect = lambda k, v, ex=None: store.__setitem__(k, v)
    mock_redis.get.side_effect = lambda k: store.get(k)
    mock_redis.exists.side_effect = lambda k: k in store
    mock_redis.delete.side_effect = lambda *keys: [store.pop(k, None) for k in keys]
    mock_redis.rpush.side_effect = lambda k, v: store.setdefault(k, []).append(v) or len(store[k])
    mock_redis.lrange.side_effect = lambda k, s, e: store.get(k, [])
    mock_redis.llen.side_effect = lambda k: len(store.get(k, []))
    mock_redis.expire.side_effect = lambda k, t: True
    
    redis_client.redis = mock_redis
    
    phone = "whatsapp:+447700900000"
    
    # Test 1: Buffer message
    print("Buffering first message...")
    batch_id1 = await redis_client.buffer_message(phone, "Message 1")
    print(f"Batch ID 1: {batch_id1}")
    print(f"Store keys: {store.keys()}")
    assert len(store[f"buffer:{phone}"]) == 1
    
    is_curr = await redis_client.is_batch_current(phone, batch_id1)
    print(f"Is batch 1 current? {is_curr}")
    assert is_curr
    
    # Test 2: Buffer second message
    print("Buffering second message...")
    batch_id2 = await redis_client.buffer_message(phone, "Message 2")
    assert len(store[f"buffer:{phone}"]) == 2
    assert not await redis_client.is_batch_current(phone, batch_id1)
    assert await redis_client.is_batch_current(phone, batch_id2)
    
    # Test 3: Get and clear
    print("Getting and clearing buffer...")
    combined = await redis_client.get_and_clear_buffer(phone)
    print(f"Combined: {combined}")
    assert combined == "Message 1\nMessage 2"
    assert f"buffer:{phone}" not in store
    
    # Test 4: Generation tracking
    print("Testing generation tracking...")
    await redis_client.set_generating(phone)
    assert await redis_client.is_generating(phone)
    await redis_client.clear_generating(phone)
    assert not await redis_client.is_generating(phone)
    
    print("Buffering message during generation test...")
    await redis_client.buffer_message(phone, "Interrupt")
    assert await redis_client.has_new_messages(phone)
    
    print("Cleanup...")
    redis_client.redis = original_redis
    print("--- Buffering Logic Test Passed ---")

if __name__ == "__main__":
    asyncio.run(test_buffering())
