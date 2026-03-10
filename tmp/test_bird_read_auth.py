
import httpx
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("MESSAGEBIRD_API_KEY")
WORKSPACE_ID = os.getenv("MESSAGEBIRD_WORKSPACE_ID")
CHANNEL_ID = os.getenv("MESSAGEBIRD_CHANNEL_ID")
BASE_URL = "https://api.bird.com"
TEST_MESSAGE_ID = "3e5349b6-95cc-411a-9cad-2f101d7e0ab2"

async def test_auth(name, auth_header):
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = f"{BASE_URL}/workspaces/{WORKSPACE_ID}/channels/{CHANNEL_ID}/messages/{TEST_MESSAGE_ID}"
    print(f"\n--- Auth Test: {name} ---")
    print(f"Header: {auth_header[:15]}...")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.patch(url, headers=headers, json={"status": "read"})
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.text}")
    except Exception as e:
        print(f"Error: {e}")

async def main():
    await test_auth("AccessKey", f"AccessKey {API_KEY}")
    await test_auth("Bearer", f"Bearer {API_KEY}")

if __name__ == "__main__":
    asyncio.run(main())
