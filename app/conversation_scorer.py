import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

async def score_conversation(history: List[Dict[str, str]], outcome: str) -> Dict[str, Any]:
    """
    Score a conversation based on several factors.
    Returns: Score dict with 'total_score', 'worthy' (bool), and breakdown.
    """
    if not history or len(history) < 4:
        return {"total_score": 0, "worthy": False, "reason": "Too short"}

    score = 0
    breakdown = {}

    # 1. Outcome Score (Max 40)
    outcome_scores = {
        "booked": 40,
        "reengaged": 30,
        "qualified": 20,
        "exit_clean": 10,
        "disengaged": 0,
        "rude": -10
    }
    outcome_val = outcome_scores.get(outcome, 0)
    score += outcome_val
    breakdown["outcome"] = outcome_val

    # 2. Tone & Style (Max 30)
    # Check for correct chunking (|||) usage in assistant messages
    assistant_msgs = [m["content"] for m in history if m["role"] == "assistant"]
    chunks_count = sum(1 for m in assistant_msgs if "|||" in m)
    chunking_score = min(15, (chunks_count / len(assistant_msgs)) * 30) if assistant_msgs else 0
    score += chunking_score
    breakdown["chunking"] = round(chunking_score, 2)

    # Check for British Tone keywords
    british_keywords = ["reckon", "bit of", "bits", "fair enough", "look,", "haha", "pretty much", "cheers"]
    keyword_hits = sum(1 for m in assistant_msgs if any(k in m.lower() for k in british_keywords))
    tone_score = min(15, (keyword_hits / len(assistant_msgs)) * 30) if assistant_msgs else 0
    score += tone_score
    breakdown["tone"] = round(tone_score, 2)

    # 3. Pacing & Length (Max 30)
    # Avoid message flooding (too many messages vs lead)
    user_msgs = [m for m in history if m["role"] == "user"]
    ratio = len(assistant_msgs) / len(user_msgs) if user_msgs else 2
    pacing_score = 30 if 0.8 <= ratio <= 1.2 else (20 if 0.5 <= ratio <= 1.5 else 10)
    score += pacing_score
    breakdown["pacing"] = pacing_score

    # Total Score Calculation
    total_score = min(100, max(0, score))
    
    # Determine worthiness
    # Worthy if score > 75 (Excellent) or if outcome is 'booked' regardless of score (success example)
    is_worthy = total_score >= 70 or outcome == "booked"

    return {
        "total_score": total_score,
        "worthy": is_worthy,
        "breakdown": breakdown,
        "outcome": outcome
    }


async def save_for_training(redis, phone: str, history: List[Dict[str, str]], score_results: Dict[str, Any], lead_id: str = None):
    """Save worthy conversations to the training collection in Redis and Supabase."""
    if not score_results.get("worthy"):
        return

    training_id = f"train:{phone}:{int(score_results['total_score'])}"
    training_data = {
        "phone": phone,
        "score": score_results["total_score"],
        "outcome": score_results["outcome"],
        "history": history,
        "lead_id": lead_id
    }

    # 1. Store in Redis (Fast cache/index)
    await redis.set(
        f"training_data:{training_id}",
        json.dumps(training_data),
        ex=86400 * 90  # Keep for 90 days
    )
    await redis.sadd("training:index", training_id)

    # 2. Store in Supabase (Persistent dashboard storage)
    try:
        from app.supabase_client import supabase_client
        await supabase_client.table("training_data").insert({
            "lead_id": lead_id,
            "score": int(score_results['total_score']),
            "outcome": score_results['outcome'],
            "history": history
        }).execute()
        logger.info(f"Saved conversation for {phone} to Supabase training pool")
    except Exception as e:
        logger.error(f"Failed to save training data to Supabase: {e}")

    logger.info(f"Saved conversation {training_id} for training (Score: {score_results['total_score']})")
