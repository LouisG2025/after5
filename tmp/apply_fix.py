import os
filepath = "app/conversation.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

bad = """        # V4: 24h Session Auto-Close — prevents Albert responding to stale sessions
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

good = """        # V4: 24h Session Auto-Close (with returning lead bypass)
        last_updated_str = session.get("last_updated")
        is_cmd = str(message).strip().lower().startswith(("/reset", "#reset"))
        
        if not is_cmd and last_updated_str and session.get("state") not in [ConversationState.CONFIRMED, ConversationState.CLOSED]:
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
                    }
                    await redis_client.save_session(phone, new_session)
                    await redis_client.clear_generating(phone)
                    return
            except Exception as e:
                logger.warning("[Conversation] 24h auto-close check failed for %s: %s", phone, e)"""

if bad in content:
    content = content.replace(bad, good)
elif bad.replace('\n', '\r\n') in content:
    content = content.replace(bad.replace('\n', '\r\n'), good.replace('\n', '\r\n'))

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

print("DONE")
