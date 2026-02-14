#!/usr/bin/env python3
"""Bulk market matching across platforms by title similarity."""
import argparse
import json
import re
from difflib import SequenceMatcher


def _norm(t):
    t = t.lower().strip()
    t = re.sub(r'[?!.,;:\'"()]', "", t)
    t = re.sub(r"\b(will|the|be|a|an|to|in|on|by|of)\b", "", t)
    return re.sub(r"\s+", " ", t).strip()


def match(kalshi, polymarket, threshold=0.7):
    results = []
    for km in kalshi:
        best, best_score = None, 0
        kn = _norm(km.get("title", ""))
        for pm in polymarket:
            score = SequenceMatcher(None, kn, _norm(pm.get("title", ""))).ratio()
            if score > best_score:
                best_score, best = score, pm
        if best_score >= threshold and best:
            results.append(
                {
                    "kalshi_ticker": km.get("ticker"),
                    "polymarket_slug": best.get("ticker"),
                    "kalshi_title": km.get("title"),
                    "polymarket_title": best.get("title"),
                    "similarity": round(best_score, 3),
                    "needs_verification": best_score < 0.9,
                }
            )
    return sorted(results, key=lambda x: x["similarity"], reverse=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Cross-platform market title matching")
    ap.add_argument("--kalshi", required=True, help="JSON array of Kalshi markets")
    ap.add_argument("--polymarket", required=True, help="JSON array of Polymarket markets")
    ap.add_argument("--threshold", type=float, default=0.7)
    a = ap.parse_args()
    print(json.dumps(match(json.loads(a.kalshi), json.loads(a.polymarket), a.threshold), indent=2))
