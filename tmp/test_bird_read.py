
import httpx
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("MESSAGEBIRD_API_KEY")
WORKSPACE_ID = os.getenv("MESSAGEBIRD_WORKSPACE_ID")
CHANNEL_ID = os.getenv("MESSAGEBIRD_CHANNEL_ID")
BASE_URL = "https://api.bird.com"

# TEST_MESSAGE_ID = "3e5349b6-95cc-411a-9cad-2f101d7e0ab2"
# TEST_CONVERSATION_ID = "..." # We need a real conversation ID for testing

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
    # Let's try to list conversations first to get a real ID if possible
    headers = {
        "Authorization": f"AccessKey {API_KEY}",
        "Accept": "application/json",
    }
    list_url = f"{BASE_URL}/workspaces/{WORKSPACE_ID}/conversations"
    print(f"Listing conversations to find an ID: {list_url}")
    async with httpx.AsyncClient() as client:
        resp = await client.get(list_url, headers=headers)
        if resp.status_code == 200:
            convs = resp.json().get("items", [])
            if convs:
                conv_id = convs[0]["id"]
                print(f"Found Conversation ID: {conv_id}")
                
                # 1. POST to conversation read endpoint
                url1 = f"{BASE_URL}/workspaces/{WORKSPACE_ID}/conversations/{conv_id}/messages/read"
                await test_endpoint("POST to Conv Read", "POST", url1)
                
                # 1. Current implementation (PATCH to message)
                url_message_status = f"{BASE_URL}/workspaces/{WORKSPACE_ID}/channels/{CHANNEL_ID}/messages/{TEST_MESSAGE_ID}"
                await test_endpoint("PATCH status: read", "PATCH", url_message_status, {"status": "read"})

                # 4. PATCH with readAt (Some newer APIs use timestamps)
                from datetime import datetime
                now = datetime.utcnow().isoformat() + "Z"
                await test_endpoint("PATCH readAt: now", "PATCH", url_message_status, {"readAt": now})

                # 2. PATCH to conversation status
                url2 = f"{BASE_URL}/workspaces/{WORKSPACE_ID}/conversations/{conv_id}"
                await test_endpoint("PATCH Conv Status", "PATCH", url2, {"status": "active"})
            else:
                print("No conversations found.")
        else:
            print(f"Failed to list conversations: {resp.status_code} {resp.text}")

if __name__ == "__main__":
    asyncio.run(main())
