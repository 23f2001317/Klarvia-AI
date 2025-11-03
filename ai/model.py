
from __future__ import annotations

import os
import logging
from typing import Optional

logger = logging.getLogger("ai.model")
logger.setLevel(logging.INFO)

_loaded = False
_strategy: str = "fallback"

_unsloth_model = None
_unsloth_tokenizer = None
_unsloth_device = "cpu"

_hf_pipe = None


def _try_load_unsloth(model_path: str) -> bool:
    try:
        from unsloth import FastLanguageModel
        import torch

        max_seq_length = int(os.environ.get("MAX_SEQ_LENGTH", "4096"))
        dtype = None
        load_in_4bit = os.environ.get("LOAD_IN_4BIT", "true").lower() == "true"

        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=model_path,
            max_seq_length=max_seq_length,
            dtype=dtype,
            load_in_4bit=load_in_4bit,
        )

        FastLanguageModel.for_inference(model)

        global _unsloth_model, _unsloth_tokenizer, _unsloth_device
        _unsloth_model = model
        _unsloth_tokenizer = tokenizer
        _unsloth_device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Loaded Unsloth model from %s on %s", model_path, _unsloth_device)
        return True
    except Exception as e:
        logger.warning("Unsloth load failed: %s", e)
        return False


def _try_load_transformers(model_name: str) -> bool:
    try:
        from transformers import pipeline

        global _hf_pipe
        _hf_pipe = pipeline("text-generation", model=model_name)
        logger.info("Loaded transformers pipeline: %s", model_name)
        return True
    except Exception as e:
        logger.warning("Transformers load failed: %s", e)
        return False


def _load_once() -> None:
    global _loaded, _strategy
    if _loaded:
        return

    impl = os.environ.get("MODEL_IMPL", "auto").lower()
    model_path = os.environ.get("MODEL_PATH")
    model_name = os.environ.get("MODEL_NAME", "sshleifer/tiny-gpt2")

    
    if impl == "unsloth" and model_path:
        if _try_load_unsloth(model_path):
            _strategy = "unsloth"
            _loaded = True
            return
    elif impl == "transformers":
        if _try_load_transformers(model_name):
            _strategy = "transformers"
            _loaded = True
            return
    else:
        
        if model_path and _try_load_unsloth(model_path):
            _strategy = "unsloth"
            _loaded = True
            return
        if _try_load_transformers(model_name):
            _strategy = "transformers"
            _loaded = True
            return

    _strategy = "fallback"
    _loaded = True
    logger.info("Using fallback strategy (echo/rule-based)")


def get_reply(user_input: str) -> str:
    """Generate a reply string for the given user_input.

    This function lazy-loads the model on first call based on environment.
    """
    if not isinstance(user_input, str):
        return "I can only process text right now."

    _load_once()

    text = user_input.strip()
    if not text:
        return "Could you please say that again?"

    if _strategy == "unsloth":
        assert _unsloth_model is not None and _unsloth_tokenizer is not None
        history = [
            {"role": "system", "content": "You are a warm, empathetic counsellor named Klarvia."},
            {"role": "user", "content": text},
        ]
        inputs = _unsloth_tokenizer.apply_chat_template(
            history,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        )
        try:
            import torch

            inputs = inputs.to(_unsloth_device)
            outputs = _unsloth_model.generate(
                input_ids=inputs,
                max_new_tokens=int(os.environ.get("MAX_NEW_TOKENS", "200")),
                use_cache=True,
                temperature=float(os.environ.get("TEMPERATURE", "0.7")),
                top_p=float(os.environ.get("TOP_P", "0.9")),
                pad_token_id=_unsloth_tokenizer.eos_token_id,
            )
            assistant_ids = outputs[0, inputs.shape[1]:]
            reply = _unsloth_tokenizer.decode(assistant_ids, skip_special_tokens=True).strip()
            return reply or "I'm here with you. What's on your mind?"
        except Exception as e:
            logger.error("Unsloth inference error: %s", e)
            return _rule_based_reply(text)

    if _strategy == "transformers":
        try:
            assert _hf_pipe is not None
            out = _hf_pipe(text, max_new_tokens=int(os.environ.get("MAX_NEW_TOKENS", "60")))
            gen = out[0].get("generated_text", "").strip()
            reply = gen[len(text):].strip() if gen.startswith(text) else gen
            return reply or _rule_based_reply(text)
        except Exception as e:
            logger.error("Transformers inference error: %s", e)
            return _rule_based_reply(text)

    return _rule_based_reply(text)


def _rule_based_reply(text: str) -> str:
    lower = text.lower()
    if any(k in lower for k in ["hi", "hello", "hey"]):
        return "Hi, I'm Klarvia. How are you feeling right now?"
    if "help" in lower or "support" in lower:
        return "I'm here with you. What's been feeling heaviest lately?"
    return f"You said: '{text}'. Tell me more about that."


def inference_ready() -> bool:
    """Indicate whether a non-fallback strategy was loaded, or fallback is usable."""
    return True
