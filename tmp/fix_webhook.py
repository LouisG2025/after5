import os
filepath = "app/webhook.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

bad = """        # 4. CLOSED State Check — V4: re-open returning leads after 24h
        session = await redis_client.get_session(sender_phone)
        if session and session.get("state") == ConversationState.CLOSED:
            last_updated = session.get("last_updated")
            if last_updated:
                from datetime import datetime
                try:
                    lu_dt = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                    diff = (datetime.utcnow().replace(tzinfo=None) - lu_dt.replace(tzinfo=None)).total_seconds()
                    if diff < 86400:  # Still within 24h cooldown — ignore
                        logger.info(f"[Webhook] {sender_phone} is CLOSED within 24h. Ignoring message.")
                        return {"status": "ignored", "reason": "closed_state"}
"""

good = """        # 4. CLOSED State Check — V4: re-open returning leads after 24h (bypassed for /reset commands)
        session = await redis_client.get_session(sender_phone)
        
        # Extract text early just for the command check
        cmd_check = ""
        if message_type == "text":
            cmd_check = message.get("text", {}).get("body", "").strip().lower()

        if session and session.get("state") == ConversationState.CLOSED and not cmd_check.startswith(("/reset", "#reset")):
            last_updated = session.get("last_updated")
            if last_updated:
                from datetime import datetime
                try:
                    lu_dt = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                    diff = (datetime.utcnow().replace(tzinfo=None) - lu_dt.replace(tzinfo=None)).total_seconds()
                    if diff < 86400:  # Still within 24h cooldown — ignore
                        logger.info(f"[Webhook] {sender_phone} is CLOSED within 24h. Ignoring message.")
                        return {"status": "ignored", "reason": "closed_state"}
"""

if bad in content:
    content = content.replace(bad, good)
    print("DONE 1")
elif bad.replace('\n', '\r\n') in content:
    content = content.replace(bad.replace('\n', '\r\n'), good.replace('\n', '\r\n'))
    print("DONE 2")
else:
    print("NOT FOUND")

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
