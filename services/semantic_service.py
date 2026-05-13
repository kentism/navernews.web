import os
import json
import asyncio
from typing import List, Optional
import numpy as np
try:
    import google.generativeai as genai
except ImportError:
    genai = None

from app_logging import get_logger

logger = get_logger("semantic_service")

def get_google_api_key():
    # Priority: GOOGLE_API_KEY env var
    return os.getenv("GOOGLE_API_KEY")

async def get_embedding(text: str) -> List[float]:
    """
    Fetches the vector embedding for the given text using Google's embedding model.
    """
    api_key = get_google_api_key()
    if not api_key or not genai:
        if not genai:
            logger.warning("google-generativeai not installed")
        return []

    try:
        # Wrap the synchronous library call in an executor if needed, 
        # but for simplicity we'll configure and call directly.
        genai.configure(api_key=api_key)
        
        # models/embedding-001 is a common choice for semantic similarity
        result = genai.embed_content(
            model="models/embedding-001",
            content=text,
            task_type="retrieval_document"
        )
        return result.get('embedding', [])
    except Exception as exc:
        logger.error("Failed to fetch embedding", extra={"error": str(exc), "text_len": len(text)})
        return []

def calculate_similarity(v1: List[float], v2: List[float]) -> float:
    """
    Calculates cosine similarity between two vectors.
    """
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    
    try:
        a = np.array(v1)
        b = np.array(v2)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
    except Exception as exc:
        logger.error("Similarity calculation failed", extra={"error": str(exc)})
        return 0.0
