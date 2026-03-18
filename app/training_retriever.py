import logging

logger = logging.getLogger(__name__)

# NOTE: This module is retained for import compatibility only.
# QnA injection is now handled by app.prompt_assembler.PromptAssembler._get_relevant_qna()
# which is called automatically during prompt assembly (build_prompt).
# Returning empty string here prevents double-injection into the system message.

async def get_relevant_training(customer_message: str) -> str:
    """
    DEPRECATED: QnA matching is now handled by PromptAssembler.
    This stub is kept so existing imports in conversation.py still compile.
    """
    return ""
