import asyncio
import sys
from unittest.mock import AsyncMock, patch

# Mock settings and tracker before importing outbound
sys.modules['app.config'] = AsyncMock()
sys.modules['app.supabase_client'] = AsyncMock()
sys.modules['app.redis_client'] = AsyncMock()
sys.modules['app.tracker'] = AsyncMock()

async def verify_payload():
    # Mock the send_template_message tool
    with patch('app.outbound.send_template_message', new_callable=AsyncMock) as mock_send:
        from app.outbound import send_initial_outreach
        
        # Test data
        name = "Nihal"
        phone = "+447555704345"
        company = "After5 Agent"
        form_data = {"source": "Test Form"}
        
        # Run the outbound logic (it has an internal sleep of 15s usually, so we mock sleep too)
        with patch('asyncio.sleep', return_value=None):
            await send_initial_outreach(name, phone, company, form_data)
        
        # Verify the call to send_template_message
        if mock_send.called:
            args, kwargs = mock_send.call_args
            to_phone = args[0]
            template_name = args[1]
            components = kwargs.get('components', [])
            
            print(f"Template Name: {template_name}")
            print(f"Recipient: {to_phone}")
            
            # Check components
            body_params = []
            for comp in components:
                if comp['type'] == 'body':
                    body_params = comp['parameters']
            
            print(f"Body Parameters: {[p['text'] for p in body_params]}")
            
            assert template_name == "after5_outreach"
            assert len(body_params) == 2
            assert body_params[0]['text'] == name
            assert body_params[1]['text'] == company
            print("\n✅ Verification Successful: Payload structure is correct.")
        else:
            print("\n❌ Verification Failed: send_template_message was not called.")

if __name__ == "__main__":
    asyncio.run(verify_payload())
