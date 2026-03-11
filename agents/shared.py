"""
Shared AI caller: tries ezif.in first, falls back to NVIDIA NIM.
All keys pulled from environment (GitHub secrets).
"""
import os, requests, time

EZIF_KEY    = os.environ.get("AI_API_KEY", "")
EZIF_URL    = "https://ai.ezif.in/v1/chat/completions"

NVIDIA_KEY  = os.environ.get("NVIDIA_API_KEY", "")
NVIDIA_URL  = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL = "meta/llama-3.1-70b-instruct"

def ai(prompt, system="You are a helpful AI assistant.", model_hint="fast", max_tokens=2000):
    """
    Call AI with automatic fallback.
    model_hint: 'fast' = gpt-4o-mini / llama-70b, 'smart' = gpt-4o / llama-70b
    """
    ezif_model  = "gpt-4o-mini" if model_hint == "fast" else "gpt-4o"

    payload = {
        "model": ezif_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens
    }

    # ── Primary: ezif.in ────────────────────────────────────
    if EZIF_KEY:
        try:
            r = requests.post(
                EZIF_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {EZIF_KEY}",
                    "Content-Type":  "application/json"
                },
                timeout=60
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"  ⚠️  ezif.in failed ({e}), trying NVIDIA fallback...")

    # ── Fallback: NVIDIA NIM ─────────────────────────────────
    if NVIDIA_KEY:
        payload["model"] = NVIDIA_MODEL
        try:
            r = requests.post(
                NVIDIA_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {NVIDIA_KEY}",
                    "Content-Type":  "application/json"
                },
                timeout=90
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            raise RuntimeError(f"Both AI providers failed. NVIDIA error: {e}")

    raise RuntimeError("No AI API keys configured.")

