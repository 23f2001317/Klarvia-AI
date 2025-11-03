#!/usr/bin/env python3
"""
Local Klarvia model logic (rule-based, offline-only).

Reads prompt from stdin and prints a short, helpful reply. This is designed to be
fast, deterministic, and TTS-friendly (concise sentences). Replace or extend the
handlers below to plug in your own local model.
"""
from __future__ import annotations
import sys
import re


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def limit(s: str, max_len: int = 480) -> str:
    """Keep replies short for TTS latency."""
    s = s.strip()
    return s if len(s) <= max_len else s[: max_len - 1].rstrip() + "…"


def reply_greeting(_: str) -> str:
    return "Hi! I’m Klarvia. How can I help you today?"


def reply_how_are_you(_: str) -> str:
    return "I’m doing well and ready to help. What would you like to do next?"


def reply_thanks(_: str) -> str:
    return "You’re welcome. If you need anything else, just ask."


def reply_headache(_: str) -> str:
    return (
        "For a mild headache, try water, rest in a dim quiet room, and consider OTC pain relief if safe for you. "
        "If it’s severe, persistent, or has red flags like fever, neck stiffness, confusion, injury, or vision changes, seek medical care."
    )


def reply_who_are_you(_: str) -> str:
    return "I’m Klarvia, a concise voice-first assistant here to help with quick answers and simple tasks."


def fallback(user: str) -> str:
    # Lightweight generic helper with reflective acknowledgement
    u = norm(user)
    if len(u) > 140:
        u = u[:140].rstrip() + "…"
    return f"I hear you: ‘{u}’. Tell me what outcome you want, and I’ll suggest the quickest next step."


def infer_local(user_text: str) -> str:
    t = user_text.lower()
    # Greetings
    if re.search(r"\b(hi|hello|hey|good\s*(morning|afternoon|evening))\b", t):
        return reply_greeting(t)
    # How are you
    if re.search(r"\bhow are you\b", t):
        return reply_how_are_you(t)
    # Thanks
    if re.search(r"\b(thanks|thank you|appreciate it)\b", t):
        return reply_thanks(t)
    # Identity
    if re.search(r"\b(who are you|what is klarvia|tell me about you)\b", t):
        return reply_who_are_you(t)
    # Headache / migraine
    if re.search(r"\b(headache|migraine|head\s*pain)\b", t):
        return reply_headache(t)
    # Simple lifestyle tips
    if re.search(r"\b(stress|anxious|anxiety)\b", t):
        return (
            "Try a short breathing break: inhale 4s, hold 4s, exhale 6s for 1–2 minutes. "
            "A brief walk or a glass of water can also help reset."
        )
    # Fallback
    return fallback(user_text)


def main() -> None:
    try:
        text = sys.stdin.read()
    except Exception:
        text = ""
    text = (text or "").strip()
    if not text:
        print("", end="")
        return
    print(limit(infer_local(text)))


if __name__ == "__main__":
    main()
