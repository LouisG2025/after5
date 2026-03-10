
import httpx
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("MESSAGEBIRD_API_KEY")
WORKSPACE_ID = os.getenv("MESSAGEBIRD_WORKSPACE_ID")
CHANNEL_ID = os.getenv("MESSAGEBIRD_CHANNEL_ID")
BASE_URL = "https://api.bird.com"

# Using a recent message ID from the user's logs
TEST_MESSAGE_ID = "3e5349b6-95cc-411a-9cad-2f101d7e0ab2"

async def test_endpoint(name, method, url, payload=None):
    headers = {
        "Authorization": f"AccessKey {API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    print(f"\n--- Testing: {name} ---")
    print(f"URL: {url}")
    print(f"Method: {method}")
    try:
        async with httpx.AsyncClient() as client:
            if method == "PATCH":
                resp = await client.patch(url, headers=headers, json=payload)
            elif method == "POST":
                resp = await client.post(url, headers=headers, json=payload)
            else:
                resp = await client.get(url, headers=headers)
                
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.text}")
    except Exception as e:
        print(f"Error: {e}")

async def main():
    # Attempt 1: POST read receipt (WhatsApp Cloud API style)
    url1 = f"{BASE_URL}/workspaces/{WORKSPACE_ID}/channels/{CHANNEL_ID}/messages"
    payload1 = {
        "receiver": {"contacts": [{"identifierValue": "+918160178327"}]}, # Placeholder phone from logs
        "body": {
            "type": "text", # Some APIs require a type even for system updates
            "text": {"text": ""} 
        },
        "status": "read",
        "messageId": TEST_MESSAGE_ID 
    }
    await test_endpoint("POST Read Receipt (Bird Style)", "POST", url1, payload1)

    # Attempt 2: PATCH to message with readAt
    message_url = f"{BASE_URL}/workspaces/{WORKSPACE_ID}/channels/{CHANNEL_ID}/messages/{TEST_MESSAGE_ID}"
    from datetime import datetime
    now = datetime.utcnow().isoformat() + "Z"
    await test_endpoint("PATCH readAt", "PATCH", message_url, {"readAt": now})

if __name__ == "__main__":
    asyncio.run(main())
