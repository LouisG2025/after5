from app.config import settings

# 1. Fix webhook.py: Handle >24h idle for ALL states (not just CLOSED).
# If it's been > 24h since the last message in ANY state, treat them as a returning lead.
# EXCEPT if the message is a command like `/reset`. Webhook doesn't parse text easily here though.
# Wait, actually, let's just do it in conversation.py!

content_conv = open("app/conversation.py", "r", encoding="utf-8").read()

# I will replace the auto-close block in conversation.py with a fixed version
# that sits AFTER command processing, and if it triggers, it sends the returning template!

bad_block = """        # V4: 24h Session Auto-Close \u2014 prevents Albert responding to stale sessions
        last_updated_str = session.get("last_updated")
        if last_updated_str and session.get("state") not in [ConversationState.CONFIRMED, ConversationState.CLOSED]:
            try:
                from datetime import timezone as _tz
                lu_dt = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
                lu_aware = lu_dt if lu_dt.tzinfo else lu_dt.replace(tzinfo=_tz.utc)
                idle_seconds = (datetime.now(_tz.utc) - lu_aware).total_seconds()
                if idle_seconds > 86400:  # 24 hours
                    logger.info("[Conversation] 24h idle session auto-closing for %s", phone)
                    session["state"] = ConversationState.CLOSED
                    session["last_updated"] = datetime.now(_tz.utc).isoformat()
                    await redis_client.save_session(phone, session)
                    await redis_client.clear_generating(phone)
                    return
            except Exception as e:
                logger.warning("[Conversation] 24h auto-close check failed for %s: %s", phone, e)"""

# Also CRLF version
bad_block_crlf = bad_block.replace('\n', '\r\n')

# We want to remove this block from its current location, and place it AFTER command handling.
content_conv = content_conv.replace(bad_block, "")
content_conv = content_conv.replace(bad_block_crlf, "")

good_block = """        # V4: 24h Session Auto-Close — returning lead logic for any unfinished session
        last_updated_str = session.get("last_updated")
        if last_updated_str and session.get("state") not in [ConversationState.CONFIRMED, ConversationState.CLOSED]:
            try:
                from datetime import timezone as _tz
                lu_dt = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
                lu_aware = lu_dt if lu_dt.tzinfo else lu_dt.replace(tzinfo=_tz.utc)
                idle_seconds = (datetime.now(_tz.utc) - lu_aware).total_seconds()
                if idle_seconds > 86400:  # 24 hours
                    logger.info("[Conversation] %s returning after 24h idle — reopening session.", phone)
                    lead_name = session.get("lead_data", {}).get("first_name", "there")
                    returning_template = f"Hey {lead_name}, Albert here again from After5. Glad you came back — what changed?"
                    # Send template as single message
                    await send_message(phone, returning_template)
                    # Re-initialise session
                    new_session = {
                        "state": ConversationState.OPENING,
                        "history": [{"role": "assistant", "content": returning_template}],
                        "turn_count": 1,
                        "lead_data": session.get("lead_data", {}),
                        "low_content_count": 0,
                        "last_updated": datetime.now(_tz.utc).isoformat()
                    }
                    await redis_client.save_session(phone, new_session)
                    await redis_client.clear_generating(phone)
                    return
            except Exception as e:
                logger.warning("[Conversation] 24h auto-close check failed for %s: %s", phone, e)
"""

# Find point to insert good_block: after the /reset command handling.
# Specifically, after: `await redis_client.clear_generating(phone)\n            return` (around line 128)
marker_string = """        # ... (Step 4 is moved up, so we'll just skip it below) ..."""

idx = content_conv.find(marker_string)
if idx > -1:
    content_conv = content_conv[:idx] + good_block + content_conv[idx:]
    open("app/conversation.py", "w", encoding="utf-8").write(content_conv)
    print("SUCCESS")
else:
    print("MARKER NOT FOUND", content_conv.find("Step 4 is moved up"))

