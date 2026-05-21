import os
import re
import unicodedata

import fitz
from tqdm import tqdm

from .settings import DOWNLOAD_DIR


def _normalize_text(text: str) -> str:
    """Normalize extracted PDF text to collapse invisible / unusual whitespace.

    Handles:
    - Non-breaking spaces (\xa0, \u00a0, \u202f, \u2007)
    - Zero-width chars (\u200b, \ufeff)
    - Fancy Unicode dashes (em-dash \u2014, en-dash \u2013, figure-dash \u2012,
      horizontal-bar \u2015) → plain hyphen
    - Consecutive whitespace collapsed to single space (per line)
    """
    # Replace known non-breaking / unusual space chars with regular space
    for ch in ('\xa0', '\u202f', '\u2007', '\u200b', '\ufeff'):
        text = text.replace(ch, ' ')
    # Normalize Unicode dashes to plain hyphen-minus
    for ch in ('\u2014', '\u2013', '\u2012', '\u2015'):
        text = text.replace(ch, '-')
    return text


def find_nth(haystack: str, needle: str, n: int) -> int:
    start = haystack.find(needle)
    while start >= 0 and n > 1:
        start = haystack.find(needle, start + len(needle))
        n -= 1
    return start


def get_start_ind(tpa_data, tpa_ind):
    ind1 = tpa_data.rfind(".", 0, tpa_ind)
    # ind2 = tpa_data.rfind('\n', 0, tpa_ind)
    if ind1 != -1:
        return ind1 + 1
    else:
        return 0


def get_end_ind(tpa_data):
    ind1 = tpa_data.find(".")
    # ind2 = tpa_data.find('\n')
    return ind1


# ---------------------------------------------------------------------------
# Permissive "Rgt tfc" / "Right traffic" detector.
# Covers:
#   "Rgt tfc", "Rgt\ntfc", "Rgt.\ntfc", "Right tfc", "Right traffic",
#   any combo of whitespace / newlines / non-breaking spaces between words.
# ---------------------------------------------------------------------------
_RGT_TFC_RE = re.compile(
    r"(?:Rgt|Right)"
    r"[\s\xa0.,:;]*"
    r"(?:tfc|traffic)",
    re.IGNORECASE,
)

# Regex to find RWY headers – tolerates \r\n, tabs, and leading whitespace
# that PyMuPDF sometimes injects.
_RWY_HEADER_RE = re.compile(r"(?:^|[\r\n]+)\s*RWY\s", re.MULTILINE)

# Section boundaries that terminate a RWY block
_SECTION_BOUNDARIES_RE = re.compile(
    r"(?:^|[\r\n]+)\s*(?:RUNWAY|SERVICE|AIRPORT\s+REMARKS|COMMUNICATIONS)",
    re.MULTILINE | re.IGNORECASE,
)


def get_rgt(arpt_data):
    """Extract right-traffic indicators per runway from airport text block."""
    arpt_data = _normalize_text(arpt_data)
    rgt = {}

    rwy_matches = list(_RWY_HEADER_RE.finditer(arpt_data))
    for i, m in enumerate(rwy_matches):
        rwy_start = m.start()

        # Determine end of this RWY block
        if i + 1 < len(rwy_matches):
            rwy_end = rwy_matches[i + 1].start()
        else:
            rwy_end = len(arpt_data)
            # Clamp to next section header if found
            sec_m = _SECTION_BOUNDARIES_RE.search(arpt_data, rwy_start + 4)
            if sec_m and sec_m.start() < rwy_end:
                rwy_end = sec_m.start()

        rwy_string = arpt_data[rwy_start:rwy_end]

        # Extract runway ID between "RWY " and ":"
        colon_ind = rwy_string.find(':')
        if colon_ind == -1:
            continue
        # "RWY" is found via regex; grab text after it
        rwy_label_start = rwy_string.upper().find('RWY')
        if rwy_label_start == -1:
            continue
        rwy = rwy_string[rwy_label_start + 3:colon_ind].strip()
        if not rwy:
            continue

        tfc = 'R' if _RGT_TFC_RE.search(rwy_string) else ''
        if rwy not in rgt:
            rgt[rwy] = {'Rgt': tfc}

    return rgt


# Whitespace class that covers spaces, tabs, newlines, non-breaking spaces, etc.
_WS = r"[\s\xa0]"

# Separator between "TPA" and the value: any mix of dashes, colons, spaces, newlines.
_TPA_SEP = r"[\s\xa0\-:]*"


def get_tpa(arpt_data, data):
    """Extract TPA (Traffic Pattern Altitude) for each runway.

    Strategy (applied in priority order — first match wins per runway):
      1. Per-runway: "TPA - Rwy 10L/28R 1500"
      2. General:    "TPA - 1000" (applies to all runways without a per-rwy value)
      3. Fallback:   "traffic pattern ... <altitude>"
      4. Last resort: "TPA" followed by a 3+ digit number within 80 chars
    """
    arpt_data = _normalize_text(arpt_data)

    for key in data:
        data[key]['TPA'] = ''

    # --- 1. Per-runway TPA ------------------------------------------------
    #  "TPA - Rwy 10L/28R 1500", "TPA: Rwy 28R, 1000(ft)"
    rwy_tpa_pattern = re.compile(
        r"TPA" + _TPA_SEP + r"Rwy[\s\xa0]+"
        r"([\w\d\-/]+)[\s\xa0,]+"
        r"(\d{3,})",
        re.IGNORECASE | re.DOTALL,
    )
    matches = rwy_tpa_pattern.findall(arpt_data)
    if matches:
        for rwy_match, tpa_val in matches:
            for key in data:
                if key in rwy_match or rwy_match in key:
                    data[key]['TPA'] = tpa_val

    # --- 2. General TPA: "TPA - 1000" (not followed by Rwy) ---------------
    gen_tpa_pattern = re.compile(
        r"TPA" + _TPA_SEP + r"(\d{3,})"
        r"(?![\s\xa0]*Rwy)",
        re.IGNORECASE,
    )
    gen_matches = gen_tpa_pattern.findall(arpt_data)
    if gen_matches:
        tpa_val = gen_matches[0]
        for key in data:
            if not data[key]['TPA']:
                data[key]['TPA'] = tpa_val

    # --- 3. "TPA-See Remarks" short-circuit --------------------------------
    #    Patterns 1 & 2 won't match a number after "See Remarks", so
    #    we fall through to pattern 4 automatically.

    # --- 4. Fallback: "traffic pattern ... <altitude>" ---------------------
    tp_pattern = re.compile(
        r"traffic[\s\xa0]+pattern[\s\xa0]+.*?(\d{3,})",
        re.IGNORECASE | re.DOTALL,
    )
    tp_match = tp_pattern.search(arpt_data)
    if tp_match:
        tpa_val = tp_match.group(1)
        for key in data:
            if not data[key]['TPA']:
                data[key]['TPA'] = tpa_val

    # --- 5. Last resort: "TPA" + number within 80 chars (line-scoped) ------
    #    Uses {0,80} instead of .* to avoid grabbing unrelated numbers
    #    from distant parts of the document.
    last_resort = re.compile(
        r"TPA[\s\xa0\-:]*"
        r".{0,80}?"
        r"(\d{3,})",
        re.IGNORECASE,
    )
    lr_match = last_resort.search(arpt_data)
    if lr_match:
        tpa_val = lr_match.group(1)
        for key in data:
            if not data[key]['TPA']:
                data[key]['TPA'] = tpa_val

    return data


def process_arpt_data(arpt_data):
    """Parse an airport text block for RWY right-traffic and TPA data."""
    data = get_rgt(arpt_data)
    if not data:
        return data
    get_tpa(arpt_data, data)
    return data


def process_pdfs(pdfs, arpt_id):
    arpt_ind = "(" + arpt_id + ")"
    for pdf in pdfs:
        with fitz.open(os.path.join(DOWNLOAD_DIR, pdf)) as doc:
            flag = False
            text = ""
            for page in doc:
                text += page.get_text()
                if not flag:
                    arpt_start = text.find(arpt_ind)
                if arpt_start != -1:
                    arpt_end = find_nth(text[arpt_start:], "UTC", 2)
                    if arpt_end != -1 or flag:
                        arpt_data = text[arpt_start:arpt_end]
                        return process_arpt_data(arpt_data)
                    else:
                        flag = True
                else:
                    text = ""

    return [[""], [""]]


def extracting_pdf_info(pdfs, arpts_list):
    """
    Extract airport data from PDF files.
    Converts arpts_list to set for O(1) lookup instead of O(n) list search.
    """
    print("extracting pdf data ...")
    arpts_dict = {}
    # Convert list to set for O(1) lookup performance
    arpts_set = set(arpts_list) if not isinstance(arpts_list, set) else arpts_list
    
    for pdf in tqdm(pdfs):
        skip = 0
        with fitz.open(os.path.join(DOWNLOAD_DIR, pdf)) as doc:
            text = ""
            for page in tqdm(doc):
                if skip < 30:
                    skip += 1
                    continue
                text = page.get_text()
                brace_ind = 0
                while brace_ind != -1:
                    arpt_data = False
                    brace_ind = text.find("(", brace_ind)
                    if brace_ind != -1:
                        # Bounds check to avoid IndexError near end of page text
                        remaining = len(text) - brace_ind
                        if remaining > 5 and text[brace_ind + 4] == ")":
                            arpt_id = text[(brace_ind + 1) : (brace_ind + 4)]
                            if arpt_id in arpts_set:
                                arpt_data = get_arpt_data(text[(brace_ind + 1) :])
                        elif remaining > 6 and text[brace_ind + 5] == ")":
                            arpt_id = text[(brace_ind + 1) : (brace_ind + 5)]
                            if arpt_id in arpts_set:
                                arpt_data = get_arpt_data(text[(brace_ind + 1) :])
                        if arpt_data:
                            arpt_data = text[brace_ind:arpt_data]
                            if "UTC" in arpt_data:
                                arpts_dict[arpt_id] = process_arpt_data(arpt_data)
                        brace_ind += 5
    return arpts_dict


def get_arpt_data(text):
    ind = find_nth(text, "UTC", 2)
    return ind  # text[:ind]
