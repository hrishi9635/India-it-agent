"""Talks to a free AI model through the standard 'OpenAI-compatible' web API.
Works with Groq (free cloud) and Ollama (free, on your laptop)."""
import json
import re
import time

import requests


class AIError(Exception):
    pass


class LLM:
    def __init__(self, settings):
        self.base = settings["LLM_BASE_URL"].rstrip("/")
        self.models = [m for m in (settings["LLM_MODEL"], settings.get("LLM_FALLBACK_MODEL")) if m]
        self.key = settings.get("LLM_API_KEY", "")
        self.pause = settings.get("LLM_PAUSE_SECONDS", 0)
        self.local = "localhost" in self.base or "127.0.0.1" in self.base
        self.calls = 0
        self._last = 0.0

    def available(self):
        return bool(self.key) or self.local

    def _post(self, model, messages, max_tokens, json_mode, extra):
        body = {"model": model, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        body.update(extra)
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        return requests.post(f"{self.base}/chat/completions", headers=headers, json=body, timeout=180)

    def chat_json(self, system, user, max_tokens=2500):
        wait = self.pause - (time.time() - self._last)
        if self._last and wait > 0:
            time.sleep(wait)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for model in self.models:
            json_mode = True
            extra = {"reasoning_effort": "low"} if "gpt-oss" in model and not self.local else {}
            for attempt in range(6):
                try:
                    r = self._post(model, messages, max_tokens, json_mode, extra)
                except requests.RequestException as e:
                    if attempt >= 2:
                        raise AIError(f"Could not reach the AI service: {e}") from e
                    time.sleep(10)
                    continue
                if r.status_code == 200:
                    self.calls += 1
                    self._last = time.time()
                    msg = r.json()["choices"][0]["message"]
                    return parse_json(msg.get("content") or "")
                text = r.text[:400]
                if r.status_code == 429:  # free-tier speed limit: wait and retry
                    secs = float(r.headers.get("retry-after", 0) or 0) or 20 * (attempt + 1)
                    print(f"      AI speed limit reached, waiting {int(secs)}s...")
                    time.sleep(min(secs, 120))
                    continue
                if r.status_code in (401, 403):
                    raise AIError("The AI key was refused. Check you copied the whole key (see the guide).")
                if r.status_code == 400 and extra and "reasoning" in text:
                    extra = {}
                    continue
                if r.status_code == 400 and json_mode and ("response_format" in text or "json" in text.lower()):
                    json_mode = False
                    continue
                if r.status_code in (400, 404) and "model" in text.lower():
                    print(f"      Model '{model}' unavailable, trying the next one...")
                    break
                if r.status_code >= 500:
                    time.sleep(15)
                    continue
                raise AIError(f"AI service error {r.status_code}: {text}")
        raise AIError("No AI model worked. Check LLM_MODEL in settings.txt against your provider's model list.")


def parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise AIError("The AI answer was not valid JSON.")
