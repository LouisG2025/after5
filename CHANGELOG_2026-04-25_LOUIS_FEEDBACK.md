# Albert — Changelog for Louis's 25 Apr 2026 Feedback

This document covers everything fixed in response to Louis's WhatsApp feedback.
Skim this before testing — it tells you what to look for.

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
| `app/baileys_client.py` | Send retry + return delivered list. Batch read marking. Timing logs. `import time` fix. |
| `app/webhook.py` | RPUSH all message IDs (was overwriting). Pull list before processing. |
| `app/conversation.py` | Use delivered-chunks list for history + Supabase logging instead of full LLM response. |
| `app/messaging.py` | Provider abstraction returns the delivered list. |
| `app/outbound.py` | All 3 outbound paths only log what actually delivered. |
| `prompts/system_prompt.txt` | Chunking-vs-formatting rewrite. Phase 2 trimmed. Phase 4 optional. New Memory/Callbacks/Subtext/Warmth + Match Pace sections. |
| `tests/test_chunking_logic.py` | Updated typing-delay assertion to new realistic range. |

All 32 existing tests pass.
