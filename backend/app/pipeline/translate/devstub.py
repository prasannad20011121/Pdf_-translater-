"""Development stand-in engine.

It does NOT translate. It transliterates Hindi into Latin letters so that the UI, the
worker and the checks can be exercised on any machine without downloading a model.
Only used by the "dev" profile.
"""

from __future__ import annotations

import os
import re
import time

from .base import DocContext, Translator

_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng", "च": "ch", "छ": "chh", "ज": "j",
    "झ": "jh", "ञ": "ny", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t",
    "थ": "th", "द": "d", "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh",
    "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h",
}
_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e",
    "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o",
}
_MATRAS = {
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "े": "e", "ै": "ai",
    "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e",
}
_SIGNS = {"ं": "n", "ँ": "n", "ः": "h", "।": ".", "॥": "."}
_VIRAMA, _NUKTA = "्", "़"
_DEVA_RUN = re.compile("[\\u0900-\\u097f]+")


def transliterate_word(word: str) -> str:
    out: list[str] = []
    pending_a = False
    for ch in word:
        if ch in _CONS:
            if pending_a:
                out.append("a")
            out.append(_CONS[ch])
            pending_a = True
        elif ch in _MATRAS:
            out.append(_MATRAS[ch])
            pending_a = False
        elif ch == _VIRAMA:
            pending_a = False
        elif ch == _NUKTA:
            continue
        else:
            if pending_a and ch not in ("।", "॥"):
                out.append("a")
            pending_a = False
            out.append(_VOWELS.get(ch) or _SIGNS.get(ch) or "")
    # A trailing inherent "a" is dropped, as Hindi pronunciation does ("kamal", not "kamala").
    return "".join(out)


def transliterate(text: str) -> str:
    return _DEVA_RUN.sub(lambda m: transliterate_word(m.group()), text)


class DevStandIn(Translator):
    def __init__(self, model_id: str, label: str, unit: str = "sentence"):
        self.id = model_id
        self.label = label
        self.unit = unit
        self.uses_placeholders = unit == "paragraph"
        self.delay = float(os.environ.get("PDFT_DEV_DELAY", "0.15"))

    def translate(self, texts: list[str], ctx: DocContext) -> list[str | None]:
        out: list[str | None] = []
        for text in texts:
            if self.delay:
                time.sleep(self.delay)
            out.append(transliterate(text))
        return out
