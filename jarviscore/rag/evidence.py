"""
Evidence scoring for RAG outputs.
"""
from typing import Dict, Any, Optional
from datetime import datetime


def score_evidence(
    source_reliability: float,
    freshness_days: Optional[int],
    specificity: float,
    corroboration: float,
    model_confidence: float
) -> float:
    """
    Compute a normalized evidence score (0-1).
    """
    freshness = 1.0
    if freshness_days is not None:
        # Decay after 365 days
        freshness = max(0.2, 1.0 - (freshness_days / 365.0))
    score = (
        0.30 * source_reliability +
        0.20 * freshness +
        0.20 * specificity +
        0.20 * corroboration +
        0.10 * model_confidence
    )
    return max(0.0, min(1.0, score))


def build_evidence_record(
    source: str,
    quote: str,
    pointer: str,
    source_reliability: float = 0.7,
    specificity: float = 0.7,
    corroboration: float = 0.5,
    model_confidence: float = 0.7,
    published_at: Optional[str] = None
) -> Dict[str, Any]:
    """
    Build a structured evidence record with score.
    """
    freshness_days = None
    if published_at:
        try:
            dt = datetime.fromisoformat(published_at)
            freshness_days = max(0, (datetime.utcnow() - dt).days)
        except Exception:
            freshness_days = None
    score = score_evidence(
        source_reliability=source_reliability,
        freshness_days=freshness_days,
        specificity=specificity,
        corroboration=corroboration,
        model_confidence=model_confidence,
    )
    return {
        "kind": "rag_evidence",
        "source": source,
        "pointer": pointer,
        "quote": quote,
        "score": score,
        "freshness_days": freshness_days,
        "confidence": model_confidence,
    }

