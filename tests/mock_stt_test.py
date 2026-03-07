import asyncio
import json
import logging
from unittest.mock import AsyncMock, patch
from fastapi import BackgroundTasks

# Mocking app modules before import if necessary, or just patching
import sys
import os

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.webhook import bird_webhook
from app.config import settings

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_audio_webhook():
    print("\n--- Testing Audio Webhook ---")
    
    # Mock Request
    class MockRequest:
        async def json(self):
            return {
                "event": "whatsapp.inbound",
                "payload": {
                    "id": "msg-audio-123",
                    "sender": {
                        "contact": {
                            "id": "contact-123",
                            "identifierValue": "+447700900000"
                        }
                    },
                    "body": {
                        "type": "audio",
                        "audio": {
                            "url": "https://media.messagebird.com/v1/media/sample-audio-ogg",
                            "caption": ""
                        }
                    }
                }
            }

    background_tasks = BackgroundTasks()
    
    # Patch dependencies
    with patch("app.webhook.redis_client.check_dedup", return_value=False), \
         patch("app.webhook.redis_client.buffer_message", new_callable=AsyncMock) as mock_buffer, \
         patch("app.webhook.redis_client.set_buffer_timer", new_callable=AsyncMock), \
         patch("app.webhook.process_voice_note", new_callable=AsyncMock) as mock_pvn, \
         patch("app.webhook.send_message", new_callable=AsyncMock) as mock_send:
        
        mock_pvn.return_value = "This is a transcribed test message."
        
        # Test 1: Audio message with ACK
        settings.VOICE_NOTE_ACKNOWLEDGE = True
        settings.VOICE_NOTE_ACK_MESSAGE = "Got it, listening..."
        
        response = await bird_webhook(MockRequest(), background_tasks)
        print(f"Response: {response}")
        
        mock_send.assert_called_with("whatsapp:+447700900000", "Got it, listening...")
        mock_pvn.assert_called_with("https://media.messagebird.com/v1/media/sample-audio-ogg")
        mock_buffer.assert_called_with("whatsapp:+447700900000", "This is a transcribed test message.")
        
        print("Test 1 (Audio with ACK): SUCCESS")

async def test_file_audio_webhook():
    print("\n--- Testing File (Audio) Webhook ---")
    
    class MockRequest:
        async def json(self):
            return {
                "event": "whatsapp.inbound",
                "payload": {
                    "id": "msg-file-123",
                    "sender": {
                        "contact": {
                            "identifierValue": "+447700900000"
                        }
                    },
                    "body": {
                        "type": "file",
                        "file": {
                            "files": [
                                {
                                    "contentType": "audio/ogg",
                                    "mediaUrl": "https://media.nest.messagebird.com/audio-file-url"
                                }
                            ]
                        }
                    }
                }
            }

    background_tasks = BackgroundTasks()
    
    with patch("app.webhook.redis_client.check_dedup", return_value=False), \
         patch("app.webhook.redis_client.buffer_message", new_callable=AsyncMock) as mock_buffer, \
         patch("app.webhook.redis_client.set_buffer_timer", new_callable=AsyncMock), \
         patch("app.webhook.process_voice_note", new_callable=AsyncMock) as mock_pvn, \
         patch("app.webhook.send_message", new_callable=AsyncMock) as mock_send:
        
        mock_pvn.return_value = "File transcription result."
        settings.VOICE_NOTE_ACKNOWLEDGE = True
        settings.VOICE_NOTE_ACK_MESSAGE = "" # Silent ACK
        
        response = await bird_webhook(MockRequest(), background_tasks)
        print(f"Response: {response}")
        
        mock_send.assert_not_called()
        mock_pvn.assert_called_with("https://media.nest.messagebird.com/audio-file-url")
        mock_buffer.assert_called_with("whatsapp:+447700900000", "File transcription result.")
        
        print("Test 2 (File Audio): SUCCESS")

if __name__ == "__main__":
    asyncio.run(test_audio_webhook())
    asyncio.run(test_file_audio_webhook())
