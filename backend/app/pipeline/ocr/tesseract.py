"""Tesseract OCR on a page image, with a second reading to check the numbers.

Tesseract runs as a separate program per call, so it holds no memory between pages.

Language order matters. With "hin+eng" the Hindi model leads and Tesseract drops the
digit 1 all over a page: "ज्ञापांक-1234/2026" comes out as "234/2026", "12.03.2026"
as "2.03.2026", "Rs. 11,800/-" as ",800/-". With "eng+hin" the numbers come through
and the Hindi is as good. It still slips now and then ("1 234/2026", a lost "1"), so
a second, English-only pass reads the page again: it reads digits very reliably,
even inside Hindi lines. Where the two readings of a number differ only by digits 1
the primary reading has lost, the number is repaired; where they disagree in any
other way, the number is reported as uncertain so it can be flagged for review.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache

import pytesseract
from PIL import Image

from ..extract import Block
from ..legacy import ENGLISH_WORDS
from ..normalize import normalize_text

log = logging.getLogger("pdft.ocr")

LANGS = "eng+hin"
CHECK_LANG = "eng"          # the digits cross-check pass
REPAIR_MIN_CONFIDENCE = 60  # the check pass must be this sure of a word to repair with it
FLAG_MIN_CONFIDENCE = 80    # ... and this sure to call a disagreement uncertain
MIN_COVER = 0.8             # the check word must span this much of the primary number's words


@lru_cache(maxsize=4)
def available(cmd: str | None) -> bool:
    if not cmd:
        return False
    pytesseract.pytesseract.tesseract_cmd = cmd
    try:
        langs = set(pytesseract.get_languages(config=""))
    except Exception:
        return False
    return "hin" in langs and "eng" in langs


@dataclass
class OcrResult:
    blocks: list[Block]
    mean_confidence: float
    # Numbers whose two OCR readings disagreed (also listed on each block).
    uncertain_numbers: list[str] = field(default_factory=list)
    repaired_numbers: int = 0   # numbers fixed with the check pass
    checked: bool = False       # the check pass ran


@dataclass
class _Word:
    text: str
    conf: float
    key: tuple[int, int, int]           # block, paragraph, line
    box: tuple[int, int, int, int]      # x0, y0, x1, y1


def _read_words(image: str | Image.Image, lang: str, psm: int) -> list[_Word]:
    data = pytesseract.image_to_data(image, lang=lang, config=f"--psm {psm}", output_type=pytesseract.Output.DICT)
    words: list[_Word] = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        if not text:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        words.append(_Word(text, float(data["conf"][i]), key, (x, y, x + w, y + h)))
    return words


# ---- the numbers cross-check ----------------------------------------------------------------

_SEPS = ".,/:-–"
# A number in the check pass (English only, so ASCII digits).
_CHECK_NUMBER = re.compile("[.,/:\\-–]*[0-9](?:[0-9.,/:\\-–]*[0-9])?")
# A number in the primary reading. It may be split by a space ("1 234/2026"), use
# Devanagari digits, or show a 1 as "]" ("]234").
_PRIMARY_NUMBER = re.compile(
    "[.,/:\\-–]*[0-9०-९\\]](?:[0-9०-९.,/:\\-–\\] ]*[0-9०-९\\]])?"
)
_HAS_DIGIT = re.compile("[0-9०-९]")
_DEVA_DIGIT = re.compile("[०-९]")
# A word that is only a number.
_PURE_NUMBER = re.compile(
    "[.,/:\\-–()]*[0-9०-९][0-9०-९.,/:\\-–]*[.,/:\\-–()]*"
)
LETTERS_MIN_CONFIDENCE = 85  # the check pass must be this sure a "number" is a word


def _lost_only_ones(primary: str, check: str) -> bool:
    """Is primary the check reading with some digits 1 (and separators) missing?"""
    i = 0
    lost_one = False
    for ch in check:
        if i < len(primary) and primary[i] == ch:
            i += 1
        elif ch == "1":
            lost_one = True
        elif ch not in _SEPS:
            return False
    return i == len(primary) and lost_one


def _overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> tuple[int, int]:
    return min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])


def _cluster(check_word: _Word, words: list[_Word]) -> list[int]:
    """Indexes of primary words on one line under a word of the check pass."""
    by_line: dict[tuple[int, int, int], list[int]] = {}
    for i, w in enumerate(words):
        dx, dy = _overlap(w.box, check_word.box)
        min_h = min(w.box[3] - w.box[1], check_word.box[3] - check_word.box[1])
        if w.text and dx > 0 and dy >= 0.5 * max(min_h, 1):
            by_line.setdefault(w.key, []).append(i)
    if not by_line:
        return []
    line = max(by_line.values(), key=len)
    return sorted(line, key=lambda i: words[i].box[0])


# The danda and what OCR makes of it in Latin script.
_DANDA_LIKE = "।॥|!lI"
_DANDA = "।॥|!"


def _danda_beside(text: str, after: bool) -> bool:
    """Is there a danda (or a look-alike) right next to the number?

    text: the primary text after (or before) the number. "l" and "I" only count when
    they touch the number or stand alone, so "Total 1,500" is not a danda.
    """
    if not after:
        text = text[::-1]
    if text[:1] and text[0] in _DANDA_LIKE:
        return True
    rest = text.lstrip(" ")
    if not rest:
        return False
    if rest[0] in _DANDA:
        return True
    return rest[0] in "lI" and (len(rest) == 1 or rest[1] == " ")


def _cross_check(words: list[_Word], check_words: list[_Word]) -> tuple[int, dict[tuple[int, int, int], list[str]]]:
    """Repair numbers in `words` in place from the check reading.

    Only a check word that spans the whole primary number is used, so a number the
    check pass broke into pieces (common on noisy scans) is simply left alone.
    Returns the number of repairs and the uncertain numbers per line.
    """
    repaired = 0
    uncertain: dict[tuple[int, int, int], list[str]] = {}
    for cw in check_words:
        spans = _CHECK_NUMBER.findall(cw.text)
        if len(spans) != 1:
            continue
        check_number = spans[0]
        idx = _cluster(cw, words)
        if not idx:
            continue
        # Positions of each primary word in the joined cluster text.
        starts, pos = [], 0
        for i in idx:
            starts.append(pos)
            pos += len(words[i].text) + 1
        joined = " ".join(words[i].text for i in idx)
        found = list(_PRIMARY_NUMBER.finditer(joined))
        found = [m for m in found if _HAS_DIGIT.search(m.group()) or m.group().strip("]" + _SEPS + " ") == ""]
        if len(found) != 1:
            continue  # the check pass read digits in Hindi letters, or the words don't line up
        m = found[0]
        primary = m.group()
        if _DEVA_DIGIT.search(primary):
            continue  # Devanagari digits: the English pass can't read them
        touched = [k for k, i in enumerate(idx)
                   if starts[k] < m.end() and starts[k] + len(words[i].text) > m.start()]
        px0 = min(words[idx[k]].box[0] for k in touched)
        px1 = max(words[idx[k]].box[2] for k in touched)
        if min(cw.box[2], px1) - max(cw.box[0], px0) < MIN_COVER * max(px1 - px0, 1):
            continue  # the check pass saw only part of this number
        # A danda next to the number is often read as a "1" by the check pass. Try
        # the reading without it too.
        readings = [check_number]
        if check_number.endswith("1") and _danda_beside(joined[m.end():], after=True):
            readings.append(check_number[:-1])
        if readings[-1].startswith("1") and _danda_beside(joined[:m.start()], after=False):
            readings.append(readings[-1][1:])
        compact = primary.replace(" ", "").replace("]", "1")
        check_number = compact if compact in readings else readings[-1]
        if not _HAS_DIGIT.search(check_number):
            continue
        if compact == check_number:
            if compact == primary:
                continue  # both readings agree
            fixed = True   # same number, written with a stray space or "]"
        else:
            fixed = _lost_only_ones(compact, check_number) and cw.conf >= REPAIR_MIN_CONFIDENCE
            tail = check_number[len(compact):]
            if fixed and check_number.startswith(compact) and set(tail) == {"1"}:
                # Only trailing 1s are new. If the check word also reaches past the
                # primary number, that "1" is more likely a danda the primary pass
                # didn't see: don't repair, flag it.
                char_w = (px1 - px0) / max(len(primary), 1)
                if cw.box[2] > px1 + 0.25 * char_w:
                    fixed = False
        if not fixed:
            if cw.conf >= FLAG_MIN_CONFIDENCE:
                uncertain.setdefault(words[idx[0]].key, []).append(primary.strip(_SEPS + " ") or primary)
            continue
        # Rewrite the primary words that the number touches as one word.
        first, last = touched[0], touched[-1]
        seg_start, seg_end = starts[first], starts[last] + len(words[idx[last]].text)
        new_text = joined[seg_start:m.start()] + check_number + joined[m.end():seg_end]
        log.debug("OCR number %r repaired to %r", primary, check_number)
        words[idx[first]].text = new_text
        for k in touched[1:]:
            words[idx[k]].text = ""
        repaired += 1

    # The other way round: a number where the check pass confidently reads a Latin
    # word ("Rs." read as "47." by the primary pass on a skewed scan).
    for word in words:
        if not _PURE_NUMBER.fullmatch(word.text):
            continue
        under = [check_words[i] for i in _cluster(word, check_words)]
        if not under or any(_HAS_DIGIT.search(c.text) for c in under):
            continue
        best = max(under, key=lambda c: _overlap(c.box, word.box)[0])
        covered = _overlap(best.box, word.box)[0] >= MIN_COVER * max(word.box[2] - word.box[0], 1)
        if not covered or best.conf < LETTERS_MIN_CONFIDENCE:
            continue
        latin = best.text.strip(_SEPS + "()[]'\"!?;")
        if _DEVA_DIGIT.search(word.text):
            # The English pass reads real Devanagari digits as junk letters, so only
            # a known English word counts ("Rs." read as "४७." by the Hindi model).
            is_word = latin.lower() in ENGLISH_WORDS
        else:
            is_word = sum(c.isascii() and c.isalpha() for c in latin) >= 2
        if is_word:
            uncertain.setdefault(word.key, []).append(word.text.strip(_SEPS + "() ") or word.text)
    return repaired, uncertain


# ---- OCR a page -----------------------------------------------------------------------------

def ocr_image(image: Image.Image, cmd: str, psm: int = 3, cross_check: bool = True) -> OcrResult:
    """Read a page image. With cross_check, a second English-only pass checks the numbers."""
    pytesseract.pytesseract.tesseract_cmd = cmd
    fd, path = tempfile.mkstemp(prefix="pdft_ocr_", suffix=".png")
    os.close(fd)
    try:
        image.save(path, format="PNG", compress_level=1)   # written once, read by both passes
        words = _read_words(path, LANGS, psm)
        repaired, uncertain, checked = 0, {}, False
        if cross_check and any(_HAS_DIGIT.search(w.text) or "]" in w.text for w in words):
            try:
                check_words = _read_words(path, CHECK_LANG, psm)
                repaired, uncertain = _cross_check(words, check_words)
                checked = True
            except Exception:  # the check is a bonus; never lose the page over it
                log.exception("OCR numbers cross-check failed")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    paragraphs: dict[tuple[int, int], dict[int, list[str]]] = {}
    boxes: dict[tuple[int, int], list[int]] = {}
    para_uncertain: dict[tuple[int, int], list[str]] = {}
    confidences: list[float] = []
    for w in words:
        if not w.text:
            continue
        if w.conf >= 0:
            confidences.append(w.conf)
        key = (w.key[0], w.key[1])
        paragraphs.setdefault(key, {}).setdefault(w.key[2], []).append(w.text)
        x0, y0, x1, y1 = w.box
        box = boxes.setdefault(key, [x0, y0, x1, y1])
        box[0], box[1] = min(box[0], x0), min(box[1], y0)
        box[2], box[3] = max(box[2], x1), max(box[3], y1)
    for line_key, numbers in uncertain.items():
        para_uncertain.setdefault((line_key[0], line_key[1]), []).extend(numbers)

    blocks: list[Block] = []
    all_uncertain: list[str] = []
    for key in sorted(paragraphs):
        lines = paragraphs[key]
        text = normalize_text(" ".join(" ".join(lines[n]) for n in sorted(lines)))
        if text:
            x0, y0, x1, y1 = boxes[key]
            numbers = [n for n in para_uncertain.get(key, []) if n in text]
            all_uncertain.extend(numbers)
            blocks.append(Block(text, (x0, y0, x1, y1), uncertain_numbers=numbers))
    mean = sum(confidences) / len(confidences) if confidences else 0.0
    return OcrResult(blocks, mean, all_uncertain, repaired, checked)
