# Albert — Changelog for Louis's 25 Apr 2026 Feedback

This document covers everything fixed in response to Louis's WhatsApp feedback,
plus the additional polishing rounds we did during live testing the same day.
Skim this before testing — it tells you what to look for.

> **Latest update:** the second wave (sections 9-19 below) was added during
> live test sessions on 2026-04-25 and addresses real bugs caught while
> testing on real WhatsApp from Shashank's number.

---

## What Louis flagged → What was fixed

### 1. Formatting vs. Chunking (the big one)
**Louis's example:**
> Was sent as TWO bubbles:
> Bubble 1: "cool, so the way it works is we'd build a bespoke AI agent that sits in your WhatsApp..."
> Bubble 2: "so your reps only deal with people who are actually serious"
>
> Should have been ONE bubble with a blank line.

**Fix:**
- Chunker no longer splits on paragraph breaks (`\n\n`). Those are now formatting *inside* one bubble, not chunk boundaries.
- The LLM now only chunks when it explicitly puts `|||` between thoughts.
- A code-level safety net catches the LLM if it wrongly chunks a short trailing clause that starts with "so", "and", "but", "which" etc., and merges it back into the previous bubble.
- The prompt has a new dedicated section "**CHUNKING vs FORMATTING — THIS DISTINCTION IS CRITICAL**" that uses Louis's exact wrong/right example as the teaching case.

### 2. Reading & typing delays — too long, especially first message
**Louis said:** First message way too slow. Second chunk also dragged when it should be quick.

**Old worst-case for a 200-char first message:** ~26-39 seconds.
**New:** ~14-20 seconds — feels like a real person on their phone, not a stalling system.

**Specifically:**
- Reading delay scales with message length (was a flat 4s minimum).
- Typing delay capped sensibly (was 0.1s/char with no cap → 200 chars = 20s typing).
- **Second chunk is now fast** (max 3.5s, min 1.2s) since the thought is already formed.
- Short ack messages ("yes", "ok") trigger a quick replies (~6-9s total) rather than the same 30s sequence.
- Questions get a small extra ponder bonus.

### 3. Blue ticks out of order
**Louis said:** Blue ticks weren't in correct order, especially when leads sent multiple messages.

**Cause:** The system was tracking only the LATEST message ID. When 3 messages arrived in a burst, only the last one got marked read.

**Fix:** Every incoming message is now added to a Redis list. When the read-receipt timer fires, ALL buffered messages flip to blue **at the same instant**, in parallel — exactly like a real human glancing at their phone.

### 4. Too many qualification questions
**Louis said:** Albert is asking too much before getting to the point.

**Fix:**
- Phase 2 (Discovery) cut from 4 example questions to 2: "what does the business do" + "where are leads coming from". Volume is now optional.
- Phase 4 (AI attitude check) is **skip-by-default**. Default flow is now Phase 1 → 2 → 3 → 5.
- Hard rule one-question-per-message preserved.

### 5. Memory, callbacks, subtext, warmth (Louis asked for human-feel features)
**New prompt section: "MEMORY, CALLBACKS, SUBTEXT, WARMTH — THE FOUR HUMAN TELLS"**

- **Memory** — Albert references real specifics from earlier in the chat (their company name, channels, volumes, exact words).
- **Callbacks** — "going back to what you said about the after hours bit..." — proves he was listening.
- **Subtext** — explicit translation table for what leads *mean* vs what they *type*: "we manage" = struggling, "it's fine" = it's not, "I'll have a think" = not sold, "send me info" = stalling, etc.
- **Warmth first** — when their situation sounds genuinely hard, Albert acknowledges it BEFORE pivoting to the next question.

### 6. Match their pace
New prompt section: short msg → short reply, long thoughtful msg → slightly more developed reply, vibe reply ("haha") → casual reaction back. No more loading 3 sentences onto someone who said "ok".

### 7. Dashboard ↔ mobile sync
**You also flagged:** the dashboard sometimes showed Albert messages that mobile WhatsApp never actually received.

**Cause:** Send-failures from Baileys (network blip, brief disconnect, mid-stream interrupt) were being silently ignored, and the full LLM response was logged to Supabase regardless. Dashboard reads from Supabase → showed phantom messages.

**Fix:**
- `send_message` retries once on transient failures.
- `send_chunked_messages` now returns the list of chunks that *actually* got HTTP 200 from Baileys.
- Only the delivered chunks are logged to Supabase, one per bubble. Dashboard now mirrors WhatsApp bubble-for-bubble.
- Hard error logs appear in the server output if delivery fails so we can spot Baileys disconnections immediately.
- Same fix applied to all 3 outbound paths: initial outreach fallback, returning-lead welcome-back, 24h follow-up.

### 8. Bonus: silent crash bug fixed
`_handle_pause` in `baileys_client.py` was calling `time.time()` without `import time` at module level. Would have crashed any time the silence-check branch ran during a typing-pause. Fixed.

---

---

## Live-testing polishing round (added later same day)

### 9. Allowlist with name fallback (`BAILEYS_ALLOWED_NAMES`)
WhatsApp now anonymises personal accounts behind opaque `@lid` IDs (15-digit
strings, not real phone numbers). A strict phone-only allowlist would block
legitimate testers because the LID can't always be resolved to the real phone.

**Fix:** added a second env var `BAILEYS_ALLOWED_NAMES` that matches the
WhatsApp pushName (case-insensitive substring). The allowlist gate now passes
if EITHER the resolved phone OR the pushName matches. Set in `.env` to
`shashank,louis` for testing. For production, leave both empty.

### 10. Typing-indicator before blue-tick (FIXED order)
Before, `conversation.py` step 5 fired a typing indicator BEFORE the LLM call,
which meant Albert showed "typing…" before the lead's message had even been
blue-ticked. Looked like a bot that knew what to say before reading anything.

**Fix:** removed the early typing indicator. The full sequence is now run
inside `send_chunked_messages`: blue-tick → reading delay → think → typing →
review → send. Real-human order.

### 11. Dynamic typing-pause budget (was hard-coded 20s)
When the lead types back during Albert's reply, Albert pauses HIS typing
indicator and waits. The old fixed 20s wait was too long for snappy chats and
not always right for long thoughtful messages.

**Fix:** `_compute_pause_budget` now scales the wait dynamically by the lead's
last message length:
- ≤30 chars → 6s
- 30-120 chars → 10s
- 120-250 chars → 13s
- 250+ chars → 15s

Stored in Redis as `last_lead_msg:{phone}`.

### 12. Batch blue-tick — atomic via Baileys array
Before, marking 3 incoming messages as read fired 3 parallel HTTP POSTs to
the Baileys node. Each POST called `sock.readMessages` separately, leading to
staggered tick rendering on the sender's WhatsApp.

**Fix:** `mark_batch_as_read` now sends ALL message_ids in a single HTTP POST
with `{"message_ids": [...]}`. The Baileys node's `/read` endpoint accepts the
array and passes all IDs to `sock.readMessages` in one atomic call. All ticks
flip blue together — exactly how real WhatsApp behaves.

### 13. Interrupt-path msg_id merge
When the lead sends new messages WHILE Albert is generating a reply, the
old interrupt-recursion in `conversation.py` step 9 silently dropped the new
message_ids. Only the original message would turn blue when the final reply
landed.

**Fix:** the interrupt-recursion now pulls fresh `pending_msg_ids` from Redis,
merges them with the existing burst, and threads the merged list through the
recursive `process_conversation` call. Every message in the burst flips blue.

### 14. Snappy blue-tick (mid-reply glance)
If the lead sends a message while Albert is mid-reply (typing or sending),
the message used to stay grey for 10-20s while the next reply cycle ran.

**Fix:** when the webhook detects a new message AND `is_generating=true`, it
schedules a quick "glance" task that fires after ~1.5s and blue-ticks the new
message. Mimics a real human who finishes their current text, glances at the
new incoming (instant blue tick), THEN takes time to compose the next reply.
Plus a second snappy-tick added in `conversation.py` step 9 right before the
LLM recursion fires.

### 15. Inbound logging via `asyncio.create_task` (was queued behind buffer tasks)
FastAPI's `BackgroundTasks` runs sequentially after the response. The inbound
tracker log was queued AFTER `_delayed_buffer_process` (sleeps 2s + LLM call ~5s
+ chunked send 10-15s). So the user's message wouldn't appear in the dashboard
until ~20s after they sent it, and if anything went sideways during that window
(server reload, exception), the inbound log was lost entirely.

**Fix:** inbound logging now fires via `asyncio.create_task` so it runs
concurrently with the buffer tasks. Dashboard shows the user's message within
~1s of arrival.

### 16. `is_typing` column graceful handling
`tracker.set_typing_status` was 400-erroring on every message because the
`is_typing` column doesn't exist in the `conversation_state` table.

**Fix:** the tracker now caches the missing-column state on first error and
silently no-ops thereafter. Logs a one-time hint to add a migration. Optional
proper fix: `ALTER TABLE conversation_state ADD COLUMN is_typing BOOLEAN DEFAULT FALSE;`

### 17. Strict voice enforcement (cheeky human, not corporate bot)
The earlier prompt described casual British tone but didn't enforce it. The
LLM would drift toward neutral/corporate voice, especially under emotional or
complex moments.

**Fix:** added a new prompt section "STRICT VOICE ENFORCEMENT — NOT OPTIONAL"
with five rules:
- **Rule A:** every reply MUST open with one of an exact list (yeah, so, right,
  alright, the thing is, honestly, actually, wait, depends really, nah, hm,
  fair, nice one, gotcha, makes sense, haha, hey, hey mate, ah, oh).
- **Rule A.1:** NEVER stack two openers ("yeah hey", "so hey", "alright yeah"
  are all banned with explicit BAD/GOOD examples).
- **Rule B:** every reply must contain at least one casual British word (mate,
  look, haha, fair, proper, sound, real one, etc.).
- **Rule C:** banned corporate openers/phrases (Sure!, Of course!, Great
  question, I'd be happy to, Thanks for reaching out, emojis, dashes, colons).
- **Rule D:** at least 1 in 3 replies must include a moment of personality
  (light tease, self-aware aside, reaction beat, pattern interrupt, market
  self-disclosure).
- **Rule E:** reactions without an agenda are valid ("hm, fair enough" + nothing
  is a complete reply when the moment calls for it).

Plus a self-check the LLM runs before output: opener ✓, natural word ✓, no
banned phrases ✓, personality quota ✓.

### 18. Multi-message handling in prompt
When the lead sends 2-3 messages back-to-back, the buffer combines them into
one input. The earlier prompt didn't tell Albert how to prioritise. He was
ignoring substantive content (e.g. a lead-gen pain statement) in favour of
just answering the last message ("plz?").

**Fix:** added "HANDLING MULTIPLE MESSAGES IN ONE TURN" section to the prompt
with priority order — substantive message wins, emotional plea gets
warmth-first acknowledgement, direct questions get answered, combined as one
natural reply. With a worked WRONG/RIGHT example using the actual case Louis
flagged.

### 19. Match-their-pace section
Added an explicit "MATCH THEIR PACE" section so reply LENGTH scales with
incoming length: one-word lead reply gets a one-bubble Albert reply, long
thoughtful gets slightly more developed, vibe reply ("haha", emoji) gets a
casual reaction back.

---

## What was NOT changed (and why)

- **Baileys → Neonize migration**: Louis suggested it as optional ("if you don't need that then it is fine"). Baileys works; migration mid-launch adds risk for marginal gain. Parked until post-launch.

- **Louis's detailed timing strategy**: He said he'd send one separately. Current timings are tuned to realistic human pace; if his strategy lands different numbers we can plug them straight into `app/chunker.py`.

---

## How to verify

1. Run the unit tests: `python -m pytest tests/` (32/32 should pass).
2. Spin up Baileys + the Python backend (instructions in `README.md`).
3. Send Albert these test messages from a different WhatsApp number:
   - **"yes"** → Reply should arrive in ~6-9 seconds, ONE bubble.
   - **"how does it work"** → Trailing "so your reps..." should be in the SAME bubble as the explanation, separated by a blank line.
   - **Three rapid-fire messages** → All three should turn blue at the same moment, then Albert replies once.
   - **A 200+ character thoughtful message** → Albert should read for ~6s, type for ~7s, total ~15-20s.
   - **"I'll have a think"** → Albert should read the subtext and probe gently, not push the link.
4. Open the dashboard and confirm what shows up matches what's on WhatsApp, bubble for bubble.
5. Watch the Python logs for `[timing]` lines — they show exactly when blue ticks fired and when each chunk sent.

---

## Files touched

| File | What changed |
|---|---|
| `app/chunker.py` | Stop splitting on `\n\n`. Continuation merge guardrail. Content-aware human-pace timings. |
| `app/baileys_client.py` | Send retry + return delivered list. Batch read marking via array. Timing logs. `import time` fix. Dynamic typing-pause budget. |
| `app/webhook.py` | RPUSH all message IDs. Pull list before processing. Snappy mid-reply blue-tick. Inbound logging via `asyncio.create_task` (concurrent). Allowlist with name fallback. Track `last_lead_msg`. |
| `app/conversation.py` | Use delivered-chunks list for history + Supabase logging. Removed early typing indicator. Interrupt-path merges fresh msg_ids + fires snappy glance. |
| `app/messaging.py` | Provider abstraction returns the delivered list. Threads `pending_message_ids`. |
| `app/outbound.py` | All 3 outbound paths only log what actually delivered. |
| `app/tracker.py` | `set_typing_status` gracefully handles missing `is_typing` column. |
| `app/config.py` | New `BAILEYS_ALLOWED_NAMES` env var for pushName-based allowlist fallback. |
| `baileys/index.js` | `/read` endpoint accepts both single `message_id` and `message_ids` array. |
| `prompts/system_prompt.txt` | Chunking-vs-formatting rewrite. Phase 2 trimmed. Phase 4 optional. Memory/Callbacks/Subtext/Warmth + Match Pace sections. STRICT VOICE ENFORCEMENT (Rules A, A.1, B, C, D, E). Multi-message handling. Greeter openers + no-stacking rule. |
| `tests/test_chunking_logic.py` | Updated typing-delay assertion to new realistic range. |

All 32 existing tests pass after every change.
