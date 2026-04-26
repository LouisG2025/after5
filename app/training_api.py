import os
import json
import logging
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from app.auth import require_api_key
from app.config import settings
from app.redis_client import redis_client
from app.conversation_library import load_conversation_library
from app.supabase_client import supabase_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/training", tags=["training"], dependencies=[Depends(require_api_key)])

CONVERSATIONS_DIR = "conversations"

@router.get("/library")
async def get_library():
    """List all conversation examples in the library."""
    try:
        files = [f for f in os.listdir(CONVERSATIONS_DIR) if f.endswith(".json")]
        examples = []
        for f in files:
            with open(os.path.join(CONVERSATIONS_DIR, f), "r", encoding="utf-8") as jf:
                data = json.load(jf)
                examples.append({
                    "filename": f,
                    "id": data.get("id"),
                    "tags": data.get("tags", {}),
                    "title": f.replace(".json", "").replace("_", " ").title()
                })
        return {"status": "ok", "examples": examples}
    except Exception as e:
        logger.error(f"Error listing library: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/library/{filename}")
async def get_example_detail(filename: str):
    """Get the full content of a conversation example."""
    path = os.path.join(CONVERSATIONS_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Example not found")
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/library")
async def save_example(data: Dict[str, Any]):
    """Save or update a conversation example file."""
    filename = data.get("filename")
    if not filename:
        filename = f"{data.get('id', 'new_example')}.json"
    
    if not filename.endswith(".json"):
        filename += ".json"
        
    path = os.path.join(CONVERSATIONS_DIR, filename)
    try:
        # Remove filename from data before saving to file
        save_data = data.copy()
        if "filename" in save_data:
            del save_data["filename"]
            
        with open(path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, indent=2)
        
        # Reload library into Redis
        await load_conversation_library(redis_client.redis)
        return {"status": "ok", "filename": filename}
    except Exception as e:
        logger.error(f"Error saving example: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/library/{filename}")
async def delete_example(filename: str):
    """Delete a conversation example."""
    path = os.path.join(CONVERSATIONS_DIR, filename)
    if os.path.exists(path):
        os.remove(path)
        await load_conversation_library(redis_client.redis)
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="File not found")

@router.get("/worthy")
async def get_worthy_conversations(limit: int = 50):
    """Get 'training-worthy' conversations from Supabase."""
    try:
        response = await supabase_client.table("training_data") \
            .select("*, leads(first_name, last_name, phone)") \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        return {"status": "ok", "data": response.data}
    except Exception as e:
        logger.error(f"Error fetching worthy conversations: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/export")
async def trigger_export(background_tasks: BackgroundTasks):
    """Trigger the JSONL export process."""
    try:
        from app.training_export import export_training_data
        background_tasks.add_task(export_training_data)
        return {"status": "ok", "message": "Export started in background"}
    except Exception as e:
        logger.error(f"Error triggering export: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/worthy/{id}")
async def update_worthy_review(id: str, data: Dict[str, Any]):
    """Update a training record with manual review/feedback."""
    try:
        update_data = {}
        if "manual_score" in data:
            update_data["manual_score"] = data["manual_score"]
        if "feedback" in data:
            update_data["feedback"] = data["feedback"]
        if "is_reviewed" in data:
            update_data["is_reviewed"] = data["is_reviewed"]
        
        if not update_data:
            return {"status": "ignored", "message": "No data to update"}

        response = await supabase_client.table("training_data") \
            .update(update_data) \
            .eq("id", id) \
            .execute()
            
        return {"status": "ok", "data": response.data}
    except Exception as e:
        logger.error(f"Error updating review: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats")
async def get_training_stats():
    """Get training stats for dashboard overview."""
    try:
        files = [f for f in os.listdir(CONVERSATIONS_DIR) if f.endswith(".json")]
        
        # Count worthy in Supabase
        worthy_res = await supabase_client.table("training_data").select("count").execute()
        worthy_count = worthy_res.data[0]["count"] if worthy_res.data else 0
        
        return {
            "example_count": len(files),
            "worthy_count": worthy_count,
            "redis_worthy_count": await redis_client.redis.scard("training:index")
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}
@router.get("/brain")
async def get_brain_rules():
    """Get active few-shot rules from Dynamic Training table."""
    try:
        response = await supabase_client.get_client()
        res = await response.table("dynamic_training") \
            .select("*") \
            .order("priority", desc=True) \
            .execute()
        return {"status": "ok", "data": res.data}
    except Exception as e:
        logger.error(f"Error fetching brain rules: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/brain")
async def add_brain_rule(data: Dict[str, Any]):
    """Add a new rule to the Dynamic Training brain."""
    try:
        client = await supabase_client.get_client()
        res = await client.table("dynamic_training") \
            .insert(data) \
            .execute()
        return {"status": "ok", "data": res.data}
    except Exception as e:
        logger.error(f"Error adding brain rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/brain/{id}")
async def delete_brain_rule(id: int):
    """Remove a rule from the Dynamic Training brain."""
    try:
        client = await supabase_client.get_client()
        await client.table("dynamic_training") \
            .delete() \
            .eq("id", id) \
            .execute()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error deleting brain rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/worthy/manual")
async def add_worthy_manually(data: Dict[str, Any]):
    """Manually add a conversation to the training pool."""
    try:
        client = await supabase_client.get_client()
        res = await client.table("training_data").insert({
            "lead_id": data.get("lead_id"),
            "score": data.get("score", 100),
            "outcome": data.get("outcome", "manual_pick"),
            "history": data.get("history"),
            "feedback": data.get("feedback", "Manual Pick from Dashboard")
        }).execute()
        return {"status": "ok", "data": res.data}
    except Exception as e:
        logger.error(f"Error manually adding to pool: {e}")
        raise HTTPException(status_code=500, detail=str(e))
