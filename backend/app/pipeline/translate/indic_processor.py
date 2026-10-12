"""IndicTrans2 pre- and post-processing, with a pure-Python fallback.

IndicTrans2 expects its input prepared the way its training data was: punctuation
normalised, Indic text normalised and tokenised, numbers/URLs/e-mails swapped for
<ID1>-style placeholders, and the language tags in front ("hin_Deva eng_Latn ...").
Its English output then needs the placeholders put back and Moses detokenising.

AI4Bharat's IndicTransToolkit does this, but its IndicProcessor is a Cython
extension with no Windows wheels (installing it on a laptop needs the MSVC Build
Tools). So when it can't be imported, `SimpleIndicProcessor` below is used: a
pure-Python port of IndicTransToolkit 1.1.1's processor.pyx (MIT, Varun Gumma) and
the parts of indic-nlp-library it calls (MIT, Anoop Kunchukuttan), for the
Hindi -> English direction this app uses.

What may differ from IndicTransToolkit:
- Indic normalisation is the Devanagari normaliser only (nukta decomposition, "|" to
  danda, visarga after a letter, zero-width/BOM/soft-hyphen removal). Other scripts
  get the script-independent part only, and non-Devanagari sources are not
  transliterated, so only Devanagari-script source languages are accepted.
- English sources (en -> Indic) are not supported (no Moses tokeniser here).
- The Moses rule that turns "digit space digit" into "digit.digit" is left out: the
  toolkit applies it to ordinary spaces, which can corrupt numbers ("2 3" -> "2.3").
- Placeholder matches are replaced longest first (the toolkit's order is random, so
  "12.03" could be replaced inside "12.03.2026"), and "|" is not treated as a
  hashtag/mention marker (it is an OCR'd danda in these documents).
- Moses detokenising uses sacremoses when it is installed (as the toolkit does),
  otherwise a port of its English rules; rare quote and currency cases may differ.
- Indic-script targets get a simple detokeniser only (this app translates to English).

Set PDFT_INDIC_PROCESSOR=builtin to force the fallback (for comparing the two).
"""

from __future__ import annotations

import html
import logging
import os
import re
import string
import unicodedata

log = logging.getLogger("pdft.indictrans2")

FLORES_TO_ISO = {
    "asm_Beng": "as", "awa_Deva": "hi", "ben_Beng": "bn", "bho_Deva": "hi", "brx_Deva": "hi",
    "doi_Deva": "hi", "eng_Latn": "en", "gom_Deva": "kK", "gon_Deva": "hi", "guj_Gujr": "gu",
    "hin_Deva": "hi", "hne_Deva": "hi", "kan_Knda": "kn", "kas_Arab": "ur", "kas_Deva": "hi",
    "kha_Latn": "en", "lus_Latn": "en", "mag_Deva": "hi", "mai_Deva": "hi", "mal_Mlym": "ml",
    "mar_Deva": "mr", "mni_Beng": "bn", "mni_Mtei": "hi", "npi_Deva": "ne", "ory_Orya": "or",
    "pan_Guru": "pa", "san_Deva": "hi", "sat_Olck": "or", "snd_Arab": "ur", "snd_Deva": "hi",
    "tam_Taml": "ta", "tel_Telu": "te", "urd_Arab": "ur", "unr_Deva": "hi",
}

# Indic (and Arabic, Ol Chiki, Meetei) digits -> ASCII, as the toolkit does.
_DIGIT_BLOCKS = (0x0966, 0x09E6, 0x0A66, 0x0AE6, 0x0B66, 0x0C66, 0x0CE6, 0x0660, 0x06F0, 0x1C50, 0xABF0)
DIGITS = {block + d: str(d) for block in _DIGIT_BLOCKS for d in range(10)}

# ---- punctuation normalisation (toolkit _punc_norm) ----------------------------------------

_PUNC_REPLACEMENTS: list[tuple[re.Pattern, object]] = [
    (re.compile(r"\r"), ""),
    (re.compile(r"\(\s*"), "("),
    (re.compile(r"\s*\)"), ")"),
    (re.compile(r"\s:\s?"), ":"),
    (re.compile(r"\s;\s?"), ";"),
    (re.compile("[`\u00b4\u2018\u201a\u2019]"), "'"),
    (re.compile("[\u201e\u201c\u201d\u00ab\u00bb]"), '"'),
    (re.compile("[\u2013\u2014]"), "-"),
    (re.compile(r" %"), "%"),
    (re.compile(r" [?!;]"), lambda m: m.group(0).strip()),
]
_MULTISPACE = re.compile(r"[ ]{2,}")
_END_BRACKET_SPACE_PUNC = re.compile(r"\) ([\.!:?;,])")
_DIGIT_SPACE_PERCENT = re.compile(r"(\d) %")
_DOUBLE_QUOT_PUNC = re.compile(r"\"([,\.]+)")


def punc_norm(text: str) -> str:
    for pattern, repl in _PUNC_REPLACEMENTS:
        text = pattern.sub(repl, text)
    text = _MULTISPACE.sub(" ", text)
    text = _END_BRACKET_SPACE_PUNC.sub(r")\1", text)
    text = _DIGIT_SPACE_PERCENT.sub(r"\1%", text)
    text = _DOUBLE_QUOT_PUNC.sub(r'\1"', text)
    return text.strip()


# ---- placeholders (toolkit _wrap_with_placeholders) -----------------------------------------

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# The toolkit's "(?:[...]+)+" is the same language as "[...]+" without the nested
# quantifier (which can backtrack exponentially).
URL_PATTERN = re.compile(
    r"\b(?<![\w/.])(?:(?:https?|ftp)://)?(?:(?:[\w-]+\.)+(?!\.))[\w/\-?#&=%.]+(?!\.\w+)\b"
)
NUMERAL_PATTERN = re.compile(
    r"(~?\d+\.?\d*\s?%?\s?-?\s?~?\d+\.?\d*\s?%|~?\d+%|\d+[-\/.,:']\d+[-\/.,:'+]\d+(?:\.\d+)?|\d+[-\/.:'+]\d+(?:\.\d+)?)"
)
OTHER_PATTERN = re.compile(r"[A-Za-z0-9]*[#@]\w+")

# How the model sometimes mangles "<ID1>"; each variant maps back to the original.
_INDIC_FAILURE_CASES = [
    "آی ڈی ", "ꯑꯥꯏꯗꯤ", "आईडी", "आई . डी . ", "आई . डी .", "आई. डी. ", "आई. डी.", "आय. डी. ",
    "आय. डी.", "आय . डी . ", "आय . डी .", "आइ . डी . ", "आइ . डी .", "आइ. डी. ", "आइ. डी.", "ऐटि",
    "آئی ڈی ", "ᱟᱭᱰᱤ ᱾", "आयडी", "ऐडि", "आइडि", "ᱟᱭᱰᱤ",
]


def _placeholder_variants(n: int) -> list[str]:
    out = []
    for tag in ("ID", "id"):
        out += [f"<{tag}{n}>", f"< {tag}{n} >", f"[{tag}{n}]", f"[ {tag}{n} ]", f"[{tag} {n}]",
                f"<{tag}{n}]", f"< {tag}{n}]", f"<{tag}{n} ]"]
    for case in _INDIC_FAILURE_CASES:
        out += [f"<{case}{n}>", f"< {case}{n} >", f"< {case} {n} >", f"<{case} {n}]",
                f"< {case} {n} ]", f"[{case}{n}]", f"[{case} {n}]", f"[ {case}{n} ]",
                f"[ {case} {n} ]", f"{case} {n}", f"{case}{n}"]
    return out


def wrap_with_placeholders(text: str) -> tuple[str, dict[str, str]]:
    """Swap e-mails, URLs, numbers and #/@ tags for <IDn>; return the restore map."""
    mapping: dict[str, str] = {}
    serial = 1
    for pattern in (EMAIL_PATTERN, URL_PATTERN, NUMERAL_PATTERN, OTHER_PATTERN):
        matches = sorted(set(pattern.findall(text)), key=lambda m: (-len(m), m))
        for match in matches:
            if pattern is URL_PATTERN and len(match.replace(".", "")) < 4:
                continue
            if pattern is NUMERAL_PATTERN and len(match.replace(" ", "").replace(".", "").replace(":", "")) < 4:
                continue
            if match not in text:  # already inside an earlier placeholder
                continue
            for variant in _placeholder_variants(serial):
                mapping[variant] = match
            text = text.replace(match, f"<ID{serial}>")
            serial += 1
    text = re.sub(r"\s+", " ", text).replace(">/", ">").replace("]/", "]")
    return text, mapping


def restore_placeholders(text: str, mapping: dict[str, str]) -> str:
    # Longest variants first, so "<ID1>" never eats the start of "<ID10>"-like forms.
    for key in sorted(mapping, key=len, reverse=True):
        if key in text:
            text = text.replace(key, mapping[key])
    return text


# ---- Indic normalisation and tokenisation (indic-nlp-library) -------------------------------

_NUKTA = "\u093c"
_NUKTA_DECOMPOSE = {
    "\u0929": "\u0928", "\u0931": "\u0930", "\u0934": "\u0933", "\u0958": "\u0915",
    "\u0959": "\u0916", "\u095a": "\u0917", "\u095b": "\u091c", "\u095c": "\u0921",
    "\u095d": "\u0922", "\u095e": "\u092b", "\u095f": "\u092f",
}
_VISARGA_AFTER_LETTER = re.compile("([\u0900-\u097f]):")
_DEVANAGARI_LANGS = {"hi", "mr", "sa", "kK", "ne", "sd"}


def normalize_indic(text: str, iso_lang: str = "hi") -> str:
    """indic-nlp-library BaseNormalizer + DevanagariNormalizer (default options)."""
    for ch in ("\ufeff", "\ufffe", "\u2060", "\u00ad", "\u200c", "\u200d"):
        text = text.replace(ch, "")
    text = text.replace("\u200b", " ").replace("\u00a0", " ")
    for src, dst in (("\u201e", '"'), ("\u201c", '"'), ("\u201d", '"'), ("\u2013", "-"),
                     ("\u2014", " - "), ("\u00b4", "'"), ("\u2018", "'"), ("\u201a", "'"),
                     ("\u2019", "'"), ("''", '"'), ("\u00b4\u00b4", '"'), ("\u2026", "...")):
        text = text.replace(src, dst)
    if iso_lang in _DEVANAGARI_LANGS:
        text = text.replace("\u0972", "\u090f")
        for composite, base in _NUKTA_DECOMPOSE.items():
            text = text.replace(composite, base + _NUKTA)
        text = text.replace("|", "\u0964")
        text = _VISARGA_AFTER_LETTER.sub("\\1\u0903", text)
    return text


_TOKENIZE_INDIC = re.compile(
    "([" + re.escape(string.punctuation) + "\u0964\u0965\uaaf1\uaaf0\uabeb\uabec\uabed\uabee\uabef\u1c7e\u1c7f])"
)
_NUM_SEQ = re.compile(r"([0-9]+ [,.:/] )+[0-9]+")


def trivial_tokenize(text: str) -> list[str]:
    """indic-nlp-library trivial_tokenize_indic: split off punctuation, keep numbers whole."""
    s = re.sub(r"[ ]+", " ", _TOKENIZE_INDIC.sub(r" \1 ", text.replace("\t", " "))).strip(" ")
    s = _NUM_SEQ.sub(lambda m: m.group(0).replace(" ", ""), s)
    return s.split(" ")


def trivial_detokenize_indic(text: str) -> str:
    text = re.sub(r"\s+([\u0964\u0965,.?!:;%)\]}])", r"\1", text)
    text = re.sub(r"([(\[{])\s+", r"\1", text)
    return re.sub(r" {2,}", " ", text).strip()


# ---- Moses detokeniser, English rules (sacremoses port) -------------------------------------

_IS_PUNCT = re.compile(r"^[\,\.\?\!\:\;\\\%\}\]\)]+$")
_IS_OPEN_QUOTE = re.compile(r"""^[\'\"„“`]+$""")
_IS_EN_CONTRACTION = re.compile(r"^'[^\W\d_]")
_XML_UNESCAPE = [("&bar;", "|"), ("&#124;", "|"), ("&lt;", "<"), ("&gt;", ">"), ("&bra;", "["),
                 ("&ket;", "]"), ("&quot;", '"'), ("&apos;", "'"), ("&#91;", "["), ("&#93;", "]"),
                 ("&amp;", "&")]


def _is_currency_or_opening(token: str) -> bool:
    return all(unicodedata.category(c) == "Sc" or c in "([{¿¡" for c in token)


def moses_detokenize_en(text: str) -> str:
    """Join Moses-tokenised English ("extended to 25.03.2026 .") back into text."""
    text = f" {text} ".replace(" @-@ ", "-")
    for src, dst in _XML_UNESCAPE:
        text = text.replace(src, dst)
    tokens = text.split()
    quotes: dict[str, int] = {}
    out, prepend = "", " "
    for i, token in enumerate(tokens):
        if _is_currency_or_opening(token):
            out += prepend + token
            prepend = ""
        elif _IS_PUNCT.match(token):
            out += token
            prepend = " "
        elif i > 0 and _IS_EN_CONTRACTION.match(token):
            out += token
            prepend = " "
        elif _IS_OPEN_QUOTE.match(token):
            quote = '"' if re.match(r"^[„“”]+$", token) else token
            count = quotes.get(quote, 0)
            if count % 2 == 0:
                if token == "'" and i > 0 and tokens[i - 1].endswith("s"):
                    out += token  # possessive: "the Jones' house"
                    prepend = " "
                    continue
                out += prepend + token
                prepend = ""
            else:
                out += token
                prepend = " "
            quotes[quote] = count + 1
        else:
            out += prepend + token
            prepend = " "
    return re.sub(r" {2,}", " ", out).strip()


def _english_detokenizer():
    try:
        from sacremoses import MosesDetokenizer

        detok = MosesDetokenizer(lang="en")
        return lambda text: detok.detokenize(text.split(" "))
    except Exception:
        return moses_detokenize_en


# ---- the processor ------------------------------------------------------------------------------

class SimpleIndicProcessor:
    """Drop-in for IndicTransToolkit's IndicProcessor (preprocess_batch/postprocess_batch).

    Placeholder maps are kept in order: every preprocess_batch call must be followed
    by a postprocess_batch call for the same sentences (as with the toolkit).
    """

    def __init__(self, inference: bool = True):
        self.inference = inference
        self._maps: list[dict[str, str]] = []
        self._detok_en = _english_detokenizer()

    def reset(self) -> None:
        """Forget placeholder maps of a batch that failed before postprocessing."""
        self._maps.clear()

    def _preprocess(self, sent: str, src_lang: str, tgt_lang: str | None, is_target: bool) -> str:
        iso = FLORES_TO_ISO.get(src_lang, "hi")
        script = src_lang.split("_", 1)[-1]
        if iso == "en":
            raise NotImplementedError("English source text needs IndicTransToolkit (not installed)")
        if script != "Deva":
            raise NotImplementedError(f"{src_lang} needs IndicTransToolkit (not installed)")
        sent = punc_norm(sent)
        sent = sent.translate(DIGITS)
        if self.inference:
            sent, mapping = wrap_with_placeholders(sent)
            self._maps.append(mapping)
        processed = " ".join(trivial_tokenize(normalize_indic(sent.strip(), iso))).strip()
        return processed if is_target else f"{src_lang} {tgt_lang} {processed}"

    def preprocess_batch(self, batch: list[str], src_lang: str, tgt_lang: str | None = None,
                         is_target: bool = False, visualize: bool = False) -> list[str]:
        return [self._preprocess(s, src_lang, tgt_lang, is_target) for s in batch]

    def _postprocess(self, sent: str, lang: str, mapping: dict[str, str]) -> str:
        if isinstance(sent, (tuple, list)):
            sent = sent[0]
        sent = restore_placeholders(sent, mapping)
        if lang == "eng_Latn":
            return self._detok_en(sent)
        return trivial_detokenize_indic(html.unescape(sent))

    def postprocess_batch(self, sents: list[str], lang: str = "hin_Deva", visualize: bool = False,
                          num_return_sequences: int = 1) -> list[str]:
        n_inputs = len(sents) // max(1, num_return_sequences)
        maps, self._maps = self._maps[:n_inputs], self._maps[n_inputs:]
        maps += [{}] * (n_inputs - len(maps))
        out = [self._postprocess(s, lang, maps[i // max(1, num_return_sequences)])
               for i, s in enumerate(sents)]
        self._maps.clear()  # the toolkit also empties its queue here
        return out


def make_indic_processor() -> tuple[object, str]:
    """IndicTransToolkit's processor if it imports, else the built-in one.

    Returns (processor, "IndicTransToolkit" | "built-in").
    """
    if os.environ.get("PDFT_INDIC_PROCESSOR", "").lower() not in ("builtin", "built-in"):
        try:
            try:
                from IndicTransToolkit.processor import IndicProcessor  # 1.x
            except ImportError:
                from IndicTransToolkit import IndicProcessor  # other releases
            return IndicProcessor(inference=True), "IndicTransToolkit"
        except Exception as e:  # not installed, or its compiled extension won't load
            log.info("IndicTransToolkit not usable (%s); using the built-in processor", e)
    return SimpleIndicProcessor(inference=True), "built-in"
