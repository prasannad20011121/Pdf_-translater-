"""Text rules: abbreviation zero, number comparison, loops, glossary, quality, splitting."""

from __future__ import annotations

import pytest

from app.pipeline.normalize import normalize_text
from app.pipeline.protect import numbers_in, protect, restore
from app.pipeline.quality import assess
from app.pipeline.segment import LONG_SENTENCE, MAX_PIECE, split_sentences
from app.pipeline.validate import AMBER, RED, _has_loop, check, glossary_hits

# ---- the abbreviation zero: रु0, ह0/-, आर0 के0, क्र0सं0 (finding 5) -----------------------


@pytest.mark.parametrize("raw, expected", [
    ("रु0 5,00,000/-", "रु॰ 5,00,000/-"),
    ("रु० 10,000/-", "रु॰ 10,000/-"),
    ("ह0/- (आर0 के0 सिंह)", "ह॰/- (आर॰ के॰ सिंह)"),
    ("क्र0सं0 नाम पद", "क्र॰सं॰ नाम पद"),
    ("पत्रांक सं0-123/2026", "पत्रांक सं॰-123/2026"),
    ("2020ई0", "2020ई॰"),
    ("वर्ष2020", "वर्ष2020"),        # a real number glued to a word stays
    ("रु0.50", "रु0.50"),            # a decimal starting with zero stays
    ("कुल 10 पद", "कुल 10 पद"),
])
def test_abbreviation_zero_becomes_abbreviation_sign(raw, expected):
    assert normalize_text(raw) == expected


def test_abbreviation_zero_is_not_a_number():
    src = normalize_text("अग्रधन राशि रु0 5,00,000/- जमा करना होगा।")
    p = protect(src)
    assert [(i.key, i.original) for i in p.items] == [("N1", "5,00,000/-")]
    assert check(src, "Earnest money of Rs. 5,00,000/- must be deposited.").issues == {}
    # The reference number keeps its digits only: "123/2026", not "0-123/2026".
    p = protect(normalize_text("पत्रांक सं0-123/2026"))
    assert [i.original for i in p.items] == ["123/2026"]
    r = restore("Letter No. ⟦N1⟧", p.items)
    assert r.text == "Letter No. 123/2026"
    signed = normalize_text("ह0/- (आर0 के0 सिंह) सचिव")
    assert check(signed, "Sd/- (R. K. Singh) Secretary").issues == {}


def test_abbreviation_sign_is_well_formed_hindi():
    assert assess(normalize_text("रु0 क्र0सं0 डॉ॰ आर0 के0 सिंह")).score == 1.0


# ---- numbers (finding 46) --------------------------------------------------------------------

@pytest.mark.parametrize("source, output", [
    ("वित्तीय वर्ष 2025-26 के लिए", "for financial year 2025–26"),
    ("वित्तीय वर्ष 2025-26 के लिए", "for financial year 2025-2026"),
    ("प्रथम तल पर", "on the 1st floor"),
    ("दो प्रतियों में", "in 2 copies"),
    ("कंडिका 5,6 एवं 7", "paragraphs 5, 6 and 7"),
    ("दिनांक 10-15 मार्च 2026", "From 10 to 15 March 2026"),
    ("दिनांक 12.03.2026 को", "on 12 March 2026"),
    ("दिनांक 12.03.2026 को", "on 12/03/2026"),
    ("राशि 5,00,000/-", "amount Rs. 500,000/-"),
    ("राशि 11,800/-", "amount 11800"),
    ("सूची 10,20,30", "list 10, 20, 30"),
])
def test_faithful_numbers_are_not_red(source, output):
    assert "numbers" not in check(source, output).issues


@pytest.mark.parametrize("source, output", [
    ("कंडिका 5,6 एवं 7", "paragraphs 56 and 7"),          # glued: was a false GREEN
    ("दिनांक 12.03.2026 को", "on 12 May 2026"),
    ("दिनांक 12.03.2026 को", "on 2.03.2026"),
    ("ज्ञापांक-1234/2026", "Memo No. 234/2026"),
    ("राशि 5,00,000/-", "amount Rs. 50,00,000/-"),
])
def test_changed_or_lost_numbers_are_red(source, output):
    assert check(source, output).issues.get("numbers") == RED


def test_extra_numbers_are_amber_not_red():
    r = check("निविदा की अंतिम तिथि बढ़ाई गई है।", "The last date of the tender has been extended by 30 days.")
    assert r.usable and r.issues == {"extra_numbers": AMBER}


def test_numbers_in_splits_dates_and_ignores_grouping():
    assert numbers_in("5,00,000 और १२.०३.२०२६") == numbers_in("500000 on 12/03/2026")
    assert numbers_in("1,23,45,678") == {"12345678": 1}
    assert numbers_in("11,800") == numbers_in("11800")
    assert numbers_in("5,6") == {"5": 1, "6": 1}
    assert numbers_in("2025-26") == numbers_in("2025–2026") == {"2025": 1, "2026": 1}


# ---- loops (findings 16 and 20) ----------------------------------------------------------------

def test_distribution_list_is_not_a_loop():
    src = ("प्रतिलिपि: 1. सचिव, वित्त विभाग, बिहार सरकार, पटना 2. सचिव, पथ निर्माण विभाग, बिहार सरकार, "
           "पटना 3. सचिव, ग्रामीण विकास विभाग, बिहार सरकार, पटना को सूचनार्थ प्रेषित।")
    out = ("Copy: 1. Secretary, Finance Department, Government of Bihar, Patna 2. Secretary, Road "
           "Construction Department, Government of Bihar, Patna 3. Secretary, Rural Development "
           "Department, Government of Bihar, Patna for information.")
    assert check(src, out).usable


def test_repeated_amounts_are_not_a_loop():
    src = "लॉट 1 के लिए रु. 1,00,000/-, लॉट 2 के लिए रु. 1,00,000/- तथा लॉट 3 के लिए रु. 1,00,000/- जमा करें।"
    out = "Deposit Rs. 1,00,000/- for lot 1, Rs. 1,00,000/- for lot 2 and Rs. 1,00,000/- for lot 3."
    assert check(src, out).usable


@pytest.mark.parametrize("output", [
    "the the the the the",
    "of the tender of the tender of the tender",
    "the date the date the date the date the date the date 25.03.2026",
    "Notice is hereby given that the bid is open and the bid is open and the bid is open and the bid is open",
])
def test_real_loops_are_caught(output):
    assert _has_loop(output, "निविदा सूचना")


def test_scattered_repetition_counts_only_when_output_is_too_long():
    out = "Government of Bihar Patna A, Government of Bihar Patna B, Government of Bihar Patna C"
    assert not _has_loop(out, "बिहार सरकार पटना क, बिहार सरकार पटना ख, बिहार सरकार पटना ग")
    assert _has_loop(out, "बिहार सरकार के सभी विभाग")   # output is 3.7x the source


def test_repeated_numbers_from_the_source_are_not_a_loop():
    assert not _has_loop("0 0 0 0 0", "0 0 0 0 0")
    assert _has_loop("0 0 0 0 0", "शून्य")


# ---- glossary (finding 48) ------------------------------------------------------------------------

def test_glossary_term_before_a_danda_matches():
    assert glossary_hits("इस संबंध में जारी किया गया शुद्धि पत्र।", [("शुद्धि पत्र", "Corrigendum")])
    r = check("इस संबंध में जारी किया गया शुद्धि पत्र।", "The addendum issued in this regard.",
              glossary=[("शुद्धि पत्र", "Corrigendum")])
    assert r.issues.get("glossary") == AMBER


def test_glossary_term_with_precomposed_nukta_matches():
    term = "स\u095cक निर्माण विभाग"     # ड़ typed as one code point
    text = normalize_text("सड़क निर्माण विभाग द्वारा स्वीकृत")
    assert glossary_hits(text, [(term, "Road Construction Department")])


def test_glossary_term_typed_with_abbreviation_zero_matches():
    text = normalize_text("क्र0सं0 नाम पद")
    assert glossary_hits(text, [("क्र0सं0", "Sl. No.")])


def test_glossary_allows_plural_endings_but_not_other_words():
    assert glossary_hits("सभी निविदाओं में", [("निविदा", "tender")])
    assert glossary_hits("सभी विभागों को", [("विभाग", "department")])
    assert not glossary_hits("निविदादाता", [("निविदा", "tender")])


# ---- quality (finding 23) -----------------------------------------------------------------------

ENGLISH_PAGE = " ".join(["The bidder shall submit the proposal before the due date."] * 30)


@pytest.mark.parametrize("header", ["निविदा सूचना/Tender Notice", "अनुलग्नक–1 (Annexure-1)", "बेल्ट्रॉन/BELTRON"])
def test_bilingual_header_does_not_sink_an_english_page(header):
    assert assess(f"{header} {ENGLISH_PAGE}").score >= 0.95


@pytest.mark.parametrize("word", ["ﬁnancial", "Café", "Ø"])
def test_accented_latin_is_not_garbage(word):
    assert assess(f"{ENGLISH_PAGE} {word}").score == 1.0


@pytest.mark.parametrize("token", [
    "सूचना/Tender", "GeM-पोर्टल", "e-निविदा", "धारा-4(1)", "243(क)", "पत्रांक–123", "विषय—निविदा",
    "₹5,000/-का", "10%ब्याज", "•निविदा", "डॉ॰", "सूचना\u200c", "दिनांक १२.०३.२०२६",
])
def test_mixed_tokens_are_well_formed(token):
    assert assess(token).score == 1.0


def test_broken_text_still_scores_low():
    broken = "बə हार सरकार, सूचना Śावैध ɚ कʡ वə भाग। \\ापांक-1234/2026, दɘ नांक 12.03.2026।"
    assert assess(broken).score < 0.6
    # A short page of broken words is low too, even with fewer than 10 Hindi words.
    assert assess("बə हार Śावैध दɘ नांक").score < 0.6


# ---- sentence splitting (findings 22 and 25) -----------------------------------------------------

@pytest.mark.parametrize("text", [
    "यह पत्र श्री आर. के. सिंह, सचिव द्वारा जारी किया गया है।",
    "राशि रु. 5,00,000 जमा करें।",
    "डा. राजेश कुमार आए।",
    "जे.पी. सिंह, भा.प्र.से. सचिव आए।",
    "कु. पूजा, पं. शर्मा एवं श्रीमती ए. देवी उपस्थित थे।",
    "प्रतिलिपि: 1. सचिव, पटना 10. सचिव, गया को प्रेषित।",
])
def test_initials_abbreviations_and_list_numbers_stay_in_the_sentence(text):
    assert split_sentences(text) == [text]


def test_sentence_ends_are_still_split():
    assert split_sentences("Rs. 500 देय है. अंतिम.") == ["Rs. 500 देय है.", "अंतिम."]
    assert split_sentences("Visit www.bihar.gov.in. Then apply.") == ["Visit www.bihar.gov.in.", "Then apply."]


def test_long_comma_clause_is_split_into_short_pieces():
    docs = ["कंपनी का पंजीकरण प्रमाण पत्र", "पिछले तीन वर्षों का अंकेक्षित तुलन पत्र", "जीएसटी पंजीकरण प्रमाण पत्र",
            "पैन कार्ड की स्वहस्ताक्षरित प्रति", "आयकर विवरणी की प्रति", "अनुभव प्रमाण पत्र", "कार्यादेश की प्रतियां",
            "बैंक द्वारा जारी सॉल्वेंसी प्रमाण पत्र", "शपथ पत्र कि फर्म काली सूची में नहीं है", "प्राधिकार पत्र"]
    clause = ("निविदादाता को निम्नलिखित दस्तावेज संलग्न करने होंगे, " + ", ".join(docs * 3)
              + " अनिवार्य रूप से संलग्न करना होगा, अन्यथा निविदा अस्वीकृत कर दी जाएगी।")
    assert len(clause) > LONG_SENTENCE
    parts = split_sentences(clause)
    assert len(parts) > 1
    assert all(len(p) <= MAX_PIECE for p in parts)
    assert " ".join(parts) == clause            # nothing lost or reordered
    assert parts[-1].endswith("अन्यथा निविदा अस्वीकृत कर दी जाएगी।")


def test_long_text_without_any_punctuation_is_split_between_words():
    text = " ".join(["निविदा"] * 120)
    parts = split_sentences(text)
    assert all(len(p) <= MAX_PIECE for p in parts) and " ".join(parts) == text


def test_numbers_are_not_cut_at_commas():
    text = "कंडिका " + ", ".join(str(i) for i in range(1, 200)) + " देखें।"
    for part in split_sentences(text):
        assert not part.startswith(","), part
    assert numbers_in(" ".join(split_sentences(text))) == numbers_in(text)
