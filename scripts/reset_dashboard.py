"""One-off: wipe all leads (cascades to messages, conversation_state, bookings, llm_sessions)."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from supabase import create_client
from app.config import settings

sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

before = sb.table("leads").select("id", count="exact").execute()
print(f"leads before: {before.count}")

if before.count and before.count > 0:
    confirm = os.environ.get("CONFIRM_RESET") == "yes"
    if not confirm:
        print("re-run with CONFIRM_RESET=yes to actually delete")
        sys.exit(1)
    sb.table("leads").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

after = sb.table("leads").select("id", count="exact").execute()
print(f"leads after: {after.count}")
for tbl in ("messages", "conversation_state", "bookings", "llm_sessions"):
    r = sb.table(tbl).select("id", count="exact").execute()
    print(f"{tbl}: {r.count}")
