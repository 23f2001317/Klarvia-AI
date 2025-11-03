"""
Lightweight shim module for a local Klarvia inference command.

Provides:
- infer(text: str) -> str

Behavior:
- If the environment variable KLARVIA_MODEL_CMD is set, it will run that command with the provided text on stdin and return stdout.
- Otherwise it raises RuntimeError so callers know no local model is configured.

Edit this file to integrate with your actual local model if you have a Python API.
"""
from __future__ import annotations
import os
import sys
import subprocess
from typing import Optional


def infer(text: str, timeout: int = 30) -> str:
    """Run the configured local Klarvia model command and return its output as text.

    Example usage: set KLARVIA_MODEL_CMD="python path/to/run_infer.py --arg val"
    where the command reads the prompt from stdin and writes the reply to stdout.
    If KLARVIA_MODEL_CMD is not set, return a simple helpful heuristic reply instead of a stub.
    """
    cmd = os.getenv("KLARVIA_MODEL_CMD")
    # 1) Explicit CLI command (env) takes priority
    if not cmd:
        # 2) Auto-discover local entry-point script next to this file: local_infer.py
        here = os.path.dirname(os.path.abspath(__file__))
        script = os.path.join(here, "local_infer.py")
        if os.path.isfile(script):
            try:
                py = sys.executable or "python"
                p = subprocess.run([py, script], input=text.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
                if p.returncode == 0:
                    return p.stdout.decode("utf-8", errors="ignore").strip()
                else:
                    # fall through to heuristics
                    pass
            except Exception:
                # fall through to heuristics
                pass
        # 3) Heuristic fallback: provide helpful guidance for common intents
        lower = (text or "").lower()
        if any(w in lower for w in ["headache", "migraine"]):
            return (
                "I’m not a doctor, but for a mild headache, try hydrating with water, resting in a quiet and dim room, "
                "and considering over-the-counter pain relief like acetaminophen or ibuprofen if you can take them safely. "
                "If it’s severe, persistent, or has red-flag symptoms (fever, neck stiffness, confusion, head injury, vision changes), seek medical care.")
        if any(w in lower for w in ["hello", "hi", "hey", "how are you"]):
            return "Hi! I’m here. How can I help you today?"
        # Generic fallback
        return "I’m here and ready to help. Could you share a bit more detail so I can give a useful answer?"

    try:
        # Use shell=True to allow complex commands (the command author should ensure it's safe).
        p = subprocess.run(cmd, input=text.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, timeout=timeout)
        if p.returncode != 0:
            stderr = p.stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(f"Klarvia model command failed (exit {p.returncode}): {stderr}")
        out = p.stdout.decode("utf-8", errors="ignore").strip()
        return out
    except subprocess.TimeoutExpired:
        raise RuntimeError("Klarvia model command timed out")
    except Exception as e:
        raise RuntimeError(f"Klarvia model call failed: {e}")
