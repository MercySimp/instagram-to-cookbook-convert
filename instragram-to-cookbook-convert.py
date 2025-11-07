import instaloader
import qrcode
from bs4 import BeautifulSoup  # kept for future extensions
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, Table, TableStyle,
    ListFlowable, ListItem, HRFlowable, KeepTogether, Flowable
)
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import inch
import tempfile
import os
import re
from math import ceil
from PIL import Image as PILImg, ImageOps, ImageDraw
import requests
 
# -------- CONFIG --------
REEL_URLS = [
    "https://www.instagram.com/reel/DPZTgBfDWpN/",
    "https://www.instagram.com/reel/DQRmTXVDoHb/",
    "https://www.instagram.com/reel/DQLEII9jwqI/",
    "https://www.instagram.com/reel/DQCC15ZEdtV/",
    "https://www.instagram.com/reel/DQW8K2vkTWN/",
    "https://www.instagram.com/reel/DQS1WlckQHy/",
    "https://www.instagram.com/reel/DPxiMUJDseR/",
    "https://www.instagram.com/reel/DQVuvpsjt__/",
    "https://www.instagram.com/reel/DNwBn2i5AHN/",
    "https://www.instagram.com/reel/DPPiHzxD852/",
    "https://www.instagram.com/reel/DPwtBSSks8Q/",
    "https://www.instagram.com/reel/DQju39SjjyH/",
    "https://www.instagram.com/reel/DQfpG1ZDJqD/",
    "https://www.instagram.com/reel/DK6eaZrPmCv/",
    "https://www.instagram.com/reel/DQftlSoEd0C/",
    "https://www.instagram.com/reel/DQUsoEGEViE/",
    "https://www.instagram.com/reel/DQciyXIEx0f/",
    "https://www.instagram.com/reel/DQnLeDvEmtG/",
    "https://www.instagram.com/reel/DQQQOtHkcG4/",
    "https://www.instagram.com/reel/DQsZplakeQ5/"
    ]
OUTPUT_PDF = "instagram-cookbook.pdf"
SESSION_USER = "your_instagram_username"  # for private reels access
# ------------------------

# Set True to print parsed/cleaned caption output and skip PDF build.
# Useful to verify hashtags/mentions are removed.
DEBUG_LAYOUT = False

# When True, run a diagnostics pass that measures per-recipe image and
# right-column heights and prints a compact report (does not build PDF).
DEBUG_DIAGNOSTICS = False

# Size constraints for native-size placement
MAX_W = 4.9 * inch
MAX_H = 4.7 * inch

def shortcode_from_url(url: str):
    try:
        parts = [p for p in url.split("/") if p]
        for i, seg in enumerate(parts):
            if seg in ("reel", "p"):
                if i + 1 < len(parts):
                    return parts[i + 1]
        return parts[-1]
    except Exception:
        return None

IMG_COL_W = 2.8 * inch
IMG_ASPECT = 1  # height/width; for 4:3 use 0.75, for 3:2 use 0.66
TEXT_COL_W = 3.6 * inch    # text/ingredients column width
GUTTER = 0.2 * inch

def make_top_block(img_path, styles, title, summary_bits, blurb, ing_groups):
    # Left: image (scaled to column width)
    img_h = IMG_COL_W * IMG_ASPECT
    # Create Image flowable and explicitly restrict its size so the Table
    # row height cannot force the image to stretch beyond the desired
    # dimensions (this prevents LayoutError where a cell becomes larger
    # than the page frame).
    # Compute image size using PIL to avoid unit mismatch between pixels and
    # ReportLab points. Scale the image so it never exceeds the column width
    # (IMG_COL_W) or the allowed max height (MAX_H). We always set drawWidth
    # and drawHeight to concrete values so Table layout can't enlarge the cell.
    try:
        with PILImg.open(img_path) as pil:
            w_px, h_px = pil.size
    except Exception:
        # Fallback: use ReportLab's Image metrics if PIL fails
        img_tmp = Image(img_path)
        w_px = getattr(img_tmp, 'imageWidth', IMG_COL_W)
        h_px = getattr(img_tmp, 'imageHeight', IMG_COL_W * IMG_ASPECT)

    # compute scale (points ~= pixels for typical images at 72dpi)
    scale = min(1.0, float(IMG_COL_W) / float(w_px), float(MAX_H) / float(h_px))

    img = Image(img_path)
    img.drawWidth = float(w_px) * scale
    img.drawHeight = float(h_px) * scale
    img.hAlign = "LEFT"
    # Ensure the image can never be taller than the available page frame
    try:
        page_avail_h = A4[1] - (60 + 60)
        frame_w = A4[0] - (50 + 50)
        # Reserve a small safety margin
        max_allowed_h = min(MAX_H, page_avail_h * 0.95)
        max_allowed_w = frame_w * 0.95
        cur_w = float(getattr(img, 'drawWidth', getattr(img, 'imageWidth', IMG_COL_W)))
        cur_h = float(getattr(img, 'drawHeight', getattr(img, 'imageHeight', IMG_COL_W * IMG_ASPECT)))
        # Compute a combined scale so neither dimension exceeds the allowed maxima
        s_w = max_allowed_w / cur_w if cur_w > 0 else 1.0
        s_h = max_allowed_h / cur_h if cur_h > 0 else 1.0
        s = min(1.0, s_w, s_h)
        if s < 1.0:
            img.drawWidth = cur_w * s
            img.drawHeight = cur_h * s
    except Exception:
        pass

    # Right: title + divider + summary + blurb + ingredients
    right_flow = []
    right_flow.append(Paragraph(title, styles["RecipeTitle"]))
    right_flow.append(HRFlowable(color=colors.HexColor("#eeeeee"), thickness=1, width="100%", spaceBefore=4, spaceAfter=6))

    if summary_bits:
        right_flow.append(Paragraph(" • ".join(summary_bits), styles["SmallText"]))
    if summary_bits :
        right_flow.append(Spacer(1, 0.03*inch))

    # Ingredients header
    right_flow.append(Paragraph("Ingredients", styles["HeaderSection"]))

    multi_groups = len(ing_groups) > 1
    for grp, items in ing_groups.items():
        if multi_groups:
            right_flow.append(Paragraph(grp, styles["ListHeader"]))
        if len(items) > 10:
            # compact two-column list within the right column
            n = len(items)
            half = (n + 1) // 2
            col1, col2 = items[:half], items[half:]
            while len(col2) < len(col1): col2.append("")
            rows = [[Paragraph(a, styles["RecipeText"]), Paragraph(b, styles["RecipeText"])] for a,b in zip(col1, col2)]
            tbl = Table(rows, colWidths=[(TEXT_COL_W-12)/2, (TEXT_COL_W-12)/2])
            tbl.setStyle(TableStyle([
                ('VALIGN',(0,0),(-1,-1),'TOP'),
                ('LEFTPADDING',(0,0),(-1,-1),4),
                ('RIGHTPADDING',(0,0),(-1,-1),4),
            ]))
            right_flow.append(tbl)
        else:
            right_flow.append(ListFlowable(
                [ListItem(Paragraph(it, styles["RecipeText"])) for it in items],
                bulletType="bullet", leftIndent=12
            ))

    right = right_flow
    # Decide whether to layout side-by-side or stacked. Prefer side-by-side
    # when the combined visual height fits the page frame; otherwise try to
    # keep the image side-by-side by placing only a top portion of the right
    # column next to the image and spilling the remainder below the table.
    total_ings = sum(len(v) for v in ing_groups.values()) if ing_groups else 0
    long_text = len(blurb or "") > 600

    try:
        page_avail_h = A4[1] - (60 + 60)

        # Measure each right flowable's wrapped height
        right_measures = []  # list of (flow, w, h)
        total_right_h = 0.0
        for flow in right_flow:
            try:
                w, h = flow.wrap(TEXT_COL_W, page_avail_h)
            except Exception:
                h = 14 * max(1, (len(getattr(flow, 'text', '') or '').splitlines()))
                w = TEXT_COL_W
            right_measures.append((flow, w, h))
            total_right_h += h

        img_h_points = float(getattr(img, 'drawHeight', getattr(img, 'imageHeight', IMG_COL_W * IMG_ASPECT)))

        # If everything fits, keep side-by-side
        if max(img_h_points, total_right_h) <= page_avail_h and not long_text and total_ings <= 8:
            pass  # keep the full side-by-side table below
        else:
            # Try to take a top slice of the right flows that fits alongside the image
            prefix_h = 0.0
            k = 0
            for (flow, w, h) in right_measures:
                if prefix_h + h > page_avail_h:
                    break
                prefix_h += h
                k += 1

            # If we managed to take at least one flow and the row height will fit, use split table
            if k > 0 and max(img_h_points, prefix_h) <= page_avail_h:
                right_top = [fm[0] for fm in right_measures[:k]]
                right_bottom = [fm[0] for fm in right_measures[k:]]
                t = Table([[img, right_top]], colWidths=[IMG_COL_W, TEXT_COL_W], hAlign="LEFT")
                t.setStyle(TableStyle([
                    ("VALIGN", (0,0), (-1,-1), "TOP"),
                    ("LEFTPADDING", (0,0), (-1,-1), 0),
                    ("RIGHTPADDING", (0,0), (-1,-1), 0),
                    ("TOPPADDING", (0,0), (-1,-1), 0),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 0),
                ]))
                # Return table followed by remaining right-bottom flowables
                stacked_result = [t]
                if right_bottom:
                    stacked_result.append(Spacer(1, 0.08*inch))
                    stacked_result.extend(right_bottom)
                return stacked_result

            # Fallback: if splitting couldn't produce a fitting row, use conservative stacking
            if total_ings > 8 or long_text or max(img_h_points, total_right_h) > page_avail_h:
                stacked = [img, Spacer(1, 0.06*inch)] + right
                return stacked
    except Exception:
        # On error, fall back to previous heuristic
        if total_ings > 8 or long_text:
            stacked = [img, Spacer(1, 0.06*inch)] + right
            return stacked

    # Build side-by-side table
    t = Table([[img, right]], colWidths=[IMG_COL_W, TEXT_COL_W], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ("INNERGRID", (0,0), (-1,-1), 0, colors.white),
        ("BOX", (0,0), (-1,-1), 0, colors.white),
    ]))
    return t

def add_image_native_size(path):
    img_flow = Image(path)
    iw, ih = img_flow.imageWidth, img_flow.imageHeight
    scale = min(1.0, MAX_W / iw, MAX_H / ih)
    if scale < 1.0:
        img_flow.drawWidth = iw * scale
        img_flow.drawHeight = ih * scale
    img_flow.hAlign = "CENTER"
    return img_flow

def crop_and_effects(image_path, radius_ratio=0.07):
    # Rounded corners only (no black box)
    with PILImg.open(image_path) as img:
        img = img.convert("RGBA")
        w, h = img.size
        radius = int(min(w, h) * radius_ratio)
        mask = PILImg.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, w, h), radius=radius, fill=255)
        img.putalpha(mask)
        out = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        img.save(out.name)
        return out.name

def clean_title(title, max_length=60):
    clean = re.sub(r"^[^:]+ on Instagram:\s*", "", title or "")
    clean = clean.strip("\"'“”")
    if len(clean) <= max_length:
        return clean if clean else "Untitled Recipe"
    i = clean.rfind(" ", 0, max_length)
    first_line = clean[:i] + "…" if i > 0 else clean[:max_length] + "…"
    return first_line

def parse_typography(s):
    s = re.sub(r"\b1/2\b", "½", s or "")
    s = re.sub(r"\b1/4\b", "¼", s)
    s = re.sub(r"\b3/4\b", "¾", s)
    s = re.sub(r"(\d)\s*-\s*(\d)", r"\1–\2", s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip(" .")

# ---- Improved macros/servings/sections parsing ----
MACRO_PATTERN = re.compile(
    r"(?:Macros.*?(?:Per\s+Serving|Per\s+Serve)?[^\n]*?)"
    r"(?:(\d+)\s*Calories)?[^\n]*?"
    r"(?:\|\s*)?(?:(\d+)\s*g?\s*Protein)?[^\n]*?"
    r"(?:\|\s*)?(?:(\d+)\s*g?\s*Carbs?)?[^\n]*?"
    r"(?:\|\s*)?(?:(\d+)\s*g?\s*Fat)?",
    flags=re.IGNORECASE
)

SERVINGS_PATTERN = re.compile(
    r"(?:Makes?\s*(\d+)|Serves?\s*(\d+)|Per\s*Serving\s*\(\s*(\d+)\s*Total\))",
    re.IGNORECASE
)

SECTION_HEADERS = []

def clean_hashtags(text):
    text = re.sub(r"(#[A-Za-z0-9_]+)", "", text or "")
    return re.sub(r"\n\.+\s*$", "", text.strip(), flags=re.MULTILINE)

def extract_servings_and_macros(text):
    text = text or ""

    # Find a nearby "Macros" context line (same paragraph)
    # Grab up to the next blank line to keep the numbers
    macros_block = ""
    m = re.search(r"(?is)(Macros[^\n]*?)(?:\n|$)(.*?)(?:\n\s*\n|$)", text)
    if m:
        # Combine header and next line just in case values are split
        macros_block = (m.group(1) + " " + (m.group(2) or "")).strip()
    else:
        # Fallback: search the whole text
        macros_block = text

    # Value-first, order-agnostic captures (allow optional 'g' and case variants)
    cal = None
    pro = None
    carb = None
    fat = None

    m_cal = re.search(r"(\d+)\s*Calories?", macros_block, re.IGNORECASE)
    if m_cal: cal = int(m_cal.group(1))

    m_pro = re.search(r"(\d+)\s*g?\s*Proteins?", macros_block, re.IGNORECASE) or \
            re.search(r"Protein\s*[:\-]?\s*(\d+)\s*g?", macros_block, re.IGNORECASE)
    if m_pro: pro = int(m_pro.group(1))

    m_carb = re.search(r"(\d+)\s*g?\s*Carbs?", macros_block, re.IGNORECASE) or \
             re.search(r"Carbs?\s*[:\-]?\s*(\d+)\s*g?", macros_block, re.IGNORECASE)
    if m_carb: carb = int(m_carb.group(1))

    m_fat = re.search(r"(\d+)\s*g?\s*Fat", macros_block, re.IGNORECASE) or \
            re.search(r"Fat\s*[:\-]?\s*(\d+)\s*g?", macros_block, re.IGNORECASE)
    if m_fat: fat = int(m_fat.group(1))

    # Servings tolerant variants, including "Ingredients (Makes 5)"
    servings = None
    m_serv = SERVINGS_PATTERN.search(text)
    if not m_serv:
        m_serv = re.search(r"Ingredients?\s*\(\s*Makes?\s*(\d+)\s*\)", text, re.IGNORECASE)
    if m_serv:
        for g in m_serv.groups():
            if g and g.isdigit():
                servings = int(g)
                break

    return servings, {"cal": cal, "protein": pro, "carbs": carb, "fat": fat}

def split_sections_strict(caption):
    text = clean_hashtags(caption or "")

    blurb = ""
    head_split = re.split(r"\n\s*\n", text, maxsplit=1)
    if len(head_split) == 2 and len(head_split[0]) < 220:
        blurb = head_split[0].strip()
        text = head_split[1].strip()

    servings, macros = extract_servings_and_macros(text)
    text = MACRO_PATTERN.sub("", text) if 'MACRO_PATTERN' in globals() else text
    text = SERVINGS_PATTERN.sub("", text)

    ing_block, instr_block = split_ingredients_and_instructions(text)

    # Detect subsections in ingredients
    sections = {}
    found_sub = False
    for label, pat in SECTION_HEADERS:
        m = re.search(pat + r"\s*:?", ing_block)
        if m:
            found_sub = True
    if found_sub:
        # slice by subsections
        order = []
        for label, pat in SECTION_HEADERS:
            m = re.search(pat + r"\s*:?", ing_block)
            if m:
                order.append((label, m.start()))
        order.sort(key=lambda x: x[1])
        for idx, (label, start) in enumerate(order):
            end = order[idx+1][1] if idx+1 < len(order) else len(ing_block)
            sections[label] = ing_block[start:end]
    else:
        sections["Ingredients"] = ing_block

    ingredient_groups = {k: parse_ingredient_lines(v) for k, v in sections.items()}
    instruction_steps = parse_numbered_steps(instr_block)
    # If no numbered steps were found but we still have an instructions block,
    # try to heuristically split it by common cooking action verbs so we get
    # a reasonable list of steps for rendering.
    if not instruction_steps and instr_block:
        instruction_steps = split_instructions_by_actions(instr_block)

    # Optional notes line at end
    notes = ""
    notes_match = re.search(r"(?i)\bNotes?\b\s*:?\s*(.+)$", text, re.DOTALL)
    if notes_match:
        notes = parse_typography(notes_match.group(1))

    return {
        "blurb": blurb,
        "servings": servings,
        "macros": macros,
        "ingredients": ingredient_groups,
        "instructions": instruction_steps,
        "notes": notes
    }


def split_ingredients_and_instructions(text):
    """
    Return (ingredients_block, instructions_block)
    - Recognizes 'Ingredients' and 'Instructions/Directions/Steps' headers
    - If instructions header missing, uses first line that starts with a number+dot
      as the beginning of instructions.
    """
    t = clean_hashtags(text) or ""
    # Normalize bullets and whitespace
    t = t.replace("\r", "")

    # Special-case: "You'll need:" (allow straight or curly apostrophe) where
    # the header may include ingredients on the same line. If found, return
    # only the text after that header as the ingredients block.
    # Allow an optional chef emoji prefix (👩‍🍳) before the header
    m_you = re.search(r"(?im)^\s*(?:👩‍🍳\s*)?You(?:'|’)?ll need\s*:?\s*(.*)$", t, flags=re.M)
    if m_you:
        prefix = (m_you.group(1) or "").strip()
        rest = t[m_you.end():]
        # Look for an instructions header following the "You'll need" block
        m_instr2 = re.search(r"(?im)^\s*(Instructions?|Directions?|Steps?|To\s+make|Method)\s*:?\s*$", rest, flags=re.M)
        if m_instr2:
            ing_block = (prefix + "\n" + rest[:m_instr2.start()]).strip()
            instr_block = rest[m_instr2.end():].strip()
        else:
            ing_block = (prefix + "\n" + rest).strip()
            instr_block = ""
        return ing_block, instr_block

    # Find the 'Ingredients' header
    # Match headings like "👩‍🍳 INGREDIENTS" or plain "Ingredients"
    m_ing = re.search(r"(?im)^\s*(?:👩‍🍳\s*)?Ingredients?\s*:?\s*$", t, flags=re.M)
    start = m_ing.end() if m_ing else 0
    after_ing = t[start:].strip()

    # Try to find explicit instructions header (include 'To make')
    # Recognize '👩‍🍳 DIRECTIONS', 'Directions', 'To make', etc.
    m_instr = re.search(r"(?im)^\s*(?:👩‍🍳\s*)?(Instructions?|Directions?|Steps?|To\s+make|Method)\s*:?\s*$", after_ing, flags=re.M)
    if m_instr:
        ing_block = after_ing[:m_instr.start()].strip()
        instr_block = after_ing[m_instr.end():].strip()
        return ing_block, instr_block

    # Fallback: detect first numbered step line as start of instructions
    m_num = re.search(r"(?m)^\s*\d+\.\s+", after_ing)
    if m_num:
        ing_block = after_ing[:m_num.start()].strip()
        instr_block = after_ing[m_num.start():].strip()
        return ing_block, instr_block

    # Fallback: if we see bullet-like cooking verbs, split on first 'Cook|Bake|Shred|Mix|Add|Serve'
    m_verb = re.search(r"(?im)^\s*(Cook|Bake|Shred|Stir|Mix|Add|Serve|Lower|Cover)\b.*", after_ing, flags=re.M)
    if m_verb:
        ing_block = after_ing[:m_verb.start()].strip()
        instr_block = after_ing[m_verb.start():].strip()
        return ing_block, instr_block

    # No detection, treat all as ingredients
    return after_ing, ""

def parse_ingredient_lines(block):
    lines = []
    for raw in re.split(r"\n+", block):
        s = raw.strip()
        if not s:
            continue
        # Stop if this is a section header mistakenly in the block
        # Accept headings like "👩‍🍳 DIRECTIONS" as well
        if re.match(r"(?i)^(?:👩‍🍳\s*)?(Instructions?|Directions?|Steps?)\s*:?\s*$", s):
            break
        # Remove leading bullets/dashes
        s = re.sub(r"^[•\-\–\*]\s*", "", s)
        lines.append(parse_typography(s))
    return lines

def parse_numbered_steps(block):
    block = (block or "").strip()
    if not block:
        return []
    # First, split when steps are on separate lines starting with 1., 2., etc.
    lines = re.findall(r"(?m)^\s*\d+\.\s+.*", block)
    if lines and len(lines) > 1:
        return [parse_typography(re.sub(r"^\s*\d+\.\s+", "", ln).strip()) for ln in lines]

    # If not found, split inline '1. ... 2. ...' within one paragraph
    chunks = re.split(r"\s(?=\d+\.\s)", block)  # keep numbers by splitting before them
    steps = []
    buf = ""
    for ch in chunks:
        if re.match(r"^\d+\.\s", ch):
            if buf:
                steps.append(buf.strip())
            buf = re.sub(r"^\d+\.\s", "", ch)
        else:
            buf += " " + ch
    if buf.strip():
        steps.append(buf.strip())

    # As a final fallback, split on bullets
    if len(steps) <= 1:
        steps = [parse_typography(x) for x in re.split(r"(?:\n[•\-\–]\s+|\s•\s+)", block) if x.strip()]

    # If we still have a single (long) step but the block contains multiple
    # sentence boundaries, try to split by action verbs / sentences to get
    # more granular steps (fixes cases where the author didn't number steps).
    if len(steps) <= 1 and re.search(r"[\.\!\?]\s+", block):
        # Defer to the action-based splitter which will also fall back to
        # sentence splitting when appropriate.
        return split_instructions_by_actions(block)

    return [parse_typography(s) for s in steps if s]


def split_instructions_by_actions(block):
    """Split a free-form instructions block into steps by common cooking actions.

    Heuristic: split on newlines first; if that yields a single long paragraph,
    split on locations where an action verb starts a sentence/phrase (e.g.
    "Cook", "Bake", "Mix", "Add", ...). Returns a list of cleaned steps.
    """
    if not block:
        return []

    verbs = [
        'Cook', 'Bake', 'Shred', 'Stir', 'Mix', 'Add', 'Serve', 'Lower', 'Cover',
        'Heat', 'Preheat', 'Sear', 'Fry', 'Roast', 'Simmer', 'Whisk', 'Combine',
        'Fold', 'Blend', 'Divide', 'Chop', 'Slice', 'Dice', 'Boil', 'Reduce',
        'Drain', 'Bake', 'Broil', 'Toast', 'Marinate'
    ]
    verb_pat = r"(?:" + r"|".join(re.escape(v) for v in verbs) + r")\b"

    # First split by explicit newlines and discard tiny lines
    lines = [ln.strip() for ln in re.split(r"\n+", block) if ln.strip()]
    if len(lines) > 1:
        # Clean up lines: remove leading bullets and numbers
        cleaned = []
        for ln in lines:
            ln2 = re.sub(r"^[•\-\–\*\s]*\d+\.?\s*", "", ln).strip()
            if ln2:
                cleaned.append(parse_typography(ln2))
        return cleaned

    # Single paragraph: split by verb-start lookahead (start of string, after
    # sentence end, or after newline). This captures sequences like
    # "1. Cook... 2. Mix..." without numbers, or sentences that start with verbs.
    split_re = re.compile(r"(?im)(?<=^|[\.\!\?]\s|\n)(?=(%s))" % verb_pat)
    parts = [p.strip() for p in split_re.split(block) if p and p.strip()]

    # The split produces interleaved verb tokens and text; recombine where needed
    steps = []
    i = 0
    while i < len(parts):
        if re.match(r"(?i)^%s" % verb_pat, parts[i]):
            # verb token at parts[i], text at parts[i+1] if present
            verb = parts[i].strip()
            text = parts[i+1].strip() if i+1 < len(parts) else ""
            step = (verb + " " + text).strip()
            steps.append(parse_typography(step))
            i += 2
        else:
            steps.append(parse_typography(parts[i]))
            i += 1

    # As a final fallback, split on sentence boundaries
    if not steps:
        sents = re.split(r"(?<=[\.\!\?])\s+", block)
        steps = [parse_typography(s.strip()) for s in sents if s.strip()]

    # If we still only have a single long step, try a simpler sentence split
    # which often breaks up run-on instruction paragraphs (helps cases like
    # recipe 16 where many sentences were joined into one paragraph).
    if len(steps) <= 1:
        sents = re.split(r"(?<=[\.\!\?])\s+", block)
        sents_clean = [parse_typography(s.strip()) for s in sents if s.strip()]
        if len(sents_clean) > 1:
            return sents_clean

    return steps


# ---- end improved parsing ----

def two_column_ingredients(items, style):
    n = len(items)
    half = ceil(n/2)
    col1, col2 = items[:half], items[half:]
    while len(col2) < len(col1):
        col2.append("")
    rows = [[Paragraph(c1, style), Paragraph(c2, style)] for c1, c2 in zip(col1, col2)]
    table = Table(rows, colWidths=[2.15*inch, 2.15*inch])
    table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ("LEFTPADDING", (0,0), (-1,-1), 6)]))
    return table

def generate_qr_code(url):
    qr_img = qrcode.make(url)
    qr_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    qr_img.save(qr_temp.name)
    return qr_temp.name

def parse_icons(text):
    servings, time = "", ""
    servings_match = re.search(r"(serves|portions?)\s*:?[\s]*([0-9]+)", text or "", re.IGNORECASE)
    time_match = re.search(r"([0-9]+)[\s]*(minutes?|mins?|hr|hours?)", text or "", re.IGNORECASE)
    if servings_match:
        servings = servings_match.group(2)
    if time_match:
        time = time_match.group(0)
    return servings, time

def _download_image(url, headers=None, timeout=20):
    r = requests.get(url, headers=headers or {"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    r.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    with open(tmp.name, "wb") as f:
        f.write(r.content)
    return tmp.name

def fetch_reel_data_with_instaloader(url, loader):
    url = (url or "").strip()
    if not url:
        return None
    code = shortcode_from_url(url)
    if not code:
        print(f"⚠️ Could not parse shortcode from URL: {url}")
        return None
    try:
        post = instaloader.Post.from_shortcode(loader.context, code)
        raw_title = getattr(post, "title", None) or (post.caption or "")
        title = clean_title((raw_title.split("\n")[0] if raw_title else "") or "Untitled Recipe")
        caption = post.caption or ""
        thumb_url = post.url
        thumb_tmp_path = _download_image(thumb_url)
        refined_thumb_path = crop_and_effects(thumb_tmp_path)
        try:
            os.remove(thumb_tmp_path)
        except Exception:
            pass
        return {
            "title": title,
            "caption": caption.strip(),
            "url": url,
            "thumbnail": refined_thumb_path
        }
    except Exception as e:
        print(f"⚠️ Failed to fetch {url}: {e}")
        return None

def create_pdf(recipes):
    page_width, page_height = LETTER

    if DEBUG_LAYOUT:
        for idx, recipe in enumerate(recipes, 1):
            parsed = split_sections_strict(recipe.get('caption', ''))
            print(f"\n--- Recipe {idx}: {recipe.get('title')} ---")
            print("Ingredients groups:")
            for g, items in parsed.get('ingredients', {}).items():
                print(f"  [{g}]")
                for it in items:
                    print(f"    - {it}")
            print("Instructions:")
            for i, s in enumerate(parsed.get('instructions', []), 1):
                print(f"  {i}. {s}")
        print("\nDEBUG_LAYOUT enabled — skipping PDF build.")
        return

    if DEBUG_DIAGNOSTICS:
        # Run a measurement-only pass and print compact diagnostics per recipe
        page_width, page_height = LETTER
        frame_w = page_width - (0.75*inch + 0.75*inch)
        frame_h = page_height - (0.75*inch + 0.75*inch)
        left_col_w = 3.7*inch
        cell_pad_left = 18
        cell_pad_right = 18
        col2_outer_w = frame_w - left_col_w
        right_col_inner_w = col2_outer_w - (cell_pad_left + cell_pad_right)
        page_avail_h = page_height - (0.75*inch + 0.75*inch)

        def _diag_image_dims(path, max_width=3.7*inch, max_height=6.0*inch):
            if not path or not os.path.exists(path):
                return (max_width * 0.5, max_height * 0.5)
            try:
                with PILImg.open(path) as im:
                    w, h = im.size
                    target_w = int(max_width)
                    target_h = int(max_height)
                    scale = min(target_w / w, target_h / h, 1.0)
                    new_w = int(w * scale)
                    new_h = int(h * scale)
                    # treat pixels as points (image saved at 72dpi)
                    return float(new_w), float(new_h)
            except Exception:
                return (max_width, max_height)

        for idx, recipe in enumerate(recipes, 1):
            caption = recipe.get('caption', '')
            parsed = split_sections_strict(caption)

            # build a representative right_col similar to the main flow
            right_col = []
            right_col.append(Paragraph(recipe.get('title', ''), getSampleStyleSheet()['Title']))
            # ingredients
            right_col.append(Paragraph('Ingredients', getSampleStyleSheet()['Normal']))
            ingredient_groups = parsed.get('ingredients', {'Ingredients': []})
            multi_groups = len(ingredient_groups) > 1
            for grp, items in ingredient_groups.items():
                if multi_groups:
                    right_col.append(Paragraph(grp, getSampleStyleSheet()['Normal']))
                if items:
                    if len(items) > 10:
                        right_col.append(two_column_ingredients(items, getSampleStyleSheet()['Normal']))
                    else:
                        for it in items:
                            right_col.append(Paragraph(it, getSampleStyleSheet()['Normal']))
            right_col.append(Paragraph('Instructions', getSampleStyleSheet()['Normal']))
            for i, step in enumerate(parsed.get('instructions', []), 1):
                right_col.append(Paragraph(f"{i}. {step}", getSampleStyleSheet()['Normal']))

            # Image metrics (diagnostic approximation using PIL)
            img_w, img_h = _diag_image_dims(recipe.get('thumbnail'))

            # measure right column
            right_measures = []
            total_right_h = 0.0
            for flow in right_col:
                try:
                    w, h = flow.wrap(right_col_inner_w, page_avail_h)
                except Exception:
                    h = 14 * max(1, (len(getattr(flow, 'text', '') or '').splitlines()))
                    w = right_col_inner_w
                right_measures.append((flow, w, h))
                total_right_h += h

            max_single_h = max((h for (_f, _w, h) in right_measures), default=0.0)

            table_vertical_padding = 16 + 16
            safety_margin = 6
            allowed_row_h = page_avail_h - table_vertical_padding - safety_margin

            # conservative re-measure
            extra_margin = 8
            conservative_w = max(1.0, right_col_inner_w - extra_margin)
            conservative_total = 0.0
            for f in right_col:
                try:
                    _w, _h = f.wrap(conservative_w, page_avail_h)
                except Exception:
                    _h = 14 * max(1, (len(getattr(f, 'text', '') or '').splitlines()))
                conservative_total += _h

            # compute top-slice k
            prefix_h = 0.0
            k = 0
            for (_flow, _w, h) in right_measures:
                if prefix_h + h > allowed_row_h:
                    break
                prefix_h += h
                k += 1

            conservative_top = 0.0
            if k > 0:
                for f in [fm[0] for fm in right_measures[:k]]:
                    try:
                        _w, _h = f.wrap(conservative_w, page_avail_h)
                    except Exception:
                        _h = 14 * max(1, (len(getattr(f, 'text', '') or '').splitlines()))
                    conservative_top += _h

            # decide
            if max(img_h, conservative_total) <= allowed_row_h and max_single_h <= allowed_row_h:
                decision = 'full-side-by-side'
            elif k > 0 and max(img_h, conservative_top) <= allowed_row_h:
                decision = f'top-slice(k={k})'
            else:
                decision = 'stack'

            # print compact diagnostics
            print(f"[{idx}] {recipe.get('title','Untitled')}")
            print(f"    img={img_w:.1f}x{img_h:.1f} pts | right_total={total_right_h:.1f} pts | max_single={max_single_h:.1f} pts | allowed_row_h={allowed_row_h:.1f} pts")
            print(f"    conservative_total={conservative_total:.1f} pts | k={k} | conservative_top={conservative_top:.1f} pts | decision={decision}")

        print("\nDEBUG_DIAGNOSTICS complete — no PDF built.")
        return

    doc = SimpleDocTemplate(
        OUTPUT_PDF,
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleWarm", fontName="Helvetica-Bold",
                              fontSize=18, textColor=colors.HexColor("#4B2E05"),
                              leading=26, spaceAfter=10))
    styles.add(ParagraphStyle(name="Section", fontName="Helvetica-Bold",
                              fontSize=11, textColor=colors.HexColor("#7A4F14"),
                              spaceBefore=6, spaceAfter=4))
    styles.add(ParagraphStyle(name="BodyWarm", fontName="Helvetica",
                              fontSize=10, textColor=colors.HexColor("#3B2B1C"),
                              leading=14))
    styles.add(ParagraphStyle(name="NumberedWarm", fontName="Helvetica",
                              fontSize=10, textColor=colors.HexColor("#3B2B1C"),
                              leading=15, leftIndent=12))

    def background(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#FDF8F0"))
        canvas.rect(0, 0, page_width, page_height, fill=True, stroke=False)
        canvas.restoreState()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.HexColor("#8B6B3A"))
        canvas.drawRightString(page_width - inch, 0.5 * inch, f"Page {doc.page}")
        canvas.restoreState()

    def safe_image(path, max_width=3.7*inch, max_height=6.0*inch):
        """Return a ReportLab Image flowable scaled to fit within PDF frame,
        by actually resizing the image file before ReportLab loads it."""
        if not path or not os.path.exists(path):
            return Spacer(max_width, max_height * 0.5)

        try:
            with PILImg.open(path) as im:
                w, h = im.size
                aspect = h / float(w)

                # Convert target size from points (1 inch = 72 pt)
                # to pixels, assuming 72 dpi output so 1 pt = 1 px
                target_w = int(max_width)
                target_h = int(max_height)

                # scale to fit inside the box
                scale = min(target_w / w, target_h / h, 1.0)
                new_w = int(w * scale)
                new_h = int(h * scale)

                # physically resize the image
                im_resized = im.resize((new_w, new_h))
                tmp_path = "/tmp/resized_" + os.path.basename(path)
                # Save with 72 dpi so ReportLab interprets pixels as points
                try:
                    im_resized.save(tmp_path, dpi=(72, 72))
                except Exception:
                    im_resized.save(tmp_path)

            # Now create an Image flowable without forcing pixel sizes; ask
            # ReportLab to restrict it to the requested max dimensions so
            # drawWidth/drawHeight are set in points.
            img = Image(tmp_path)
            try:
                img._restrictSize(max_width, max_height)
            except Exception:
                # Fallback: set explicit sizes based on our resize
                img.drawWidth = min(new_w, int(max_width))
                img.drawHeight = min(new_h, int(max_height))
            img.hAlign = "CENTER"
            return img

        except Exception as e:
            print(f"⚠️ Skipping bad image {path}: {e}")
            return Spacer(max_width, max_height * 0.5)

    story = []

    # Small helper flowable that reports a fixed wrap size and draws the
    # image at that exact size. Using this prevents ReportLab/Table from
    # later re-interpreting pixel/DPI metadata and accidentally resizing
    # the image during table layout (which caused the LayoutError).
    class FixedImage(Flowable):
        def __init__(self, path, width, height, hAlign="CENTER"):
            super().__init__()
            self.path = path
            self._w = float(width)
            self._h = float(height)
            self.hAlign = hAlign
            try:
                self.reader = ImageReader(path) if path else None
            except Exception:
                self.reader = None

        def wrap(self, availWidth, availHeight):
            return self._w, self._h

        def draw(self):
            if not self.reader:
                return
            # draw at origin; callers control alignment via Table cell paddings
            self.canv.drawImage(self.reader, 0, 0, width=self._w, height=self._h,
                                preserveAspectRatio=True, anchor='sw')


    for recipe in recipes:
        # we'll create and size the thumbnail after computing column widths
        img = None

        # Build the right column with title + ingredients + QR. Do NOT add
        # instructions here — instructions will be appended below the
        # image+ingredients block across the full page width.
        right_col = []
        right_col.append(Paragraph(recipe["title"], styles["TitleWarm"]))
        right_col.append(Spacer(1, 6))
        right_col.append(HRFlowable(width="100%", color=colors.HexColor("#E0C9A6"), thickness=1))
        right_col.append(Spacer(1, 10))

        # Ingredients (use improved parser that strips hashtags)
        caption = recipe.get("caption", "")
        parsed = split_sections_strict(caption)

        right_col.append(Paragraph("Ingredients", styles["Section"]))
        ingredient_groups = parsed.get("ingredients", {"Ingredients": []})
        multi_groups = len(ingredient_groups) > 1
        for grp, items in ingredient_groups.items():
            if multi_groups:
                # group header
                right_col.append(Paragraph(grp, styles["Section"]))
            if items:
                if len(items) > 10:
                    right_col.append(two_column_ingredients(items, styles["BodyWarm"]))
                else:
                    for it in items:
                        right_col.append(Paragraph(it, styles["BodyWarm"]))
        right_col.append(Spacer(1, 10))

        # QR bottom-right
        qr_path = generate_qr_code(recipe["url"])
        qr_img = safe_image(qr_path, 1.1*inch, 1.1*inch)
        qr_img.hAlign = "RIGHT"
        right_col.append(Spacer(1, 10))
        right_col.append(qr_img)

        # Capture instructions separately so we can render them full-width
        instructions = parsed.get("instructions", [])
        instr_flow = []
        if instructions:
            instr_flow.append(Spacer(1, 6))
            instr_flow.append(Paragraph("Instructions", styles["Section"]))
            for i, step in enumerate(instructions, 1):
                instr_flow.append(Paragraph(f"{i}. {step}", styles["NumberedWarm"]))

        # layout: try to keep image side-by-side. If the right column is too
        # tall, take a top slice that fits next to the image and spill the
        # remainder below the table; otherwise stack image above content.
        frame_w = page_width - (0.75*inch + 0.75*inch)
        # paddings used in the table style
        cell_pad_left = 9
        cell_pad_right = 9
        # make the thumbnail smaller so text wraps sooner and fits side-by-side
        left_col_w = 3.0*inch
        col2_outer_w = frame_w - left_col_w
        # inner width available to flowables inside the right column
        right_col_inner_w = col2_outer_w - (cell_pad_left + cell_pad_right)
        page_avail_h = page_height - (0.75*inch + 0.75*inch)

        # create the thumbnail using the actual left column width so it
        # doesn't dominate the page. Limit its height to ~60% of page
        # available height so it can sit beside ingredients.
        try:
            img = safe_image(recipe.get("thumbnail"), max_width=left_col_w, max_height=page_avail_h * 0.6)
            # extra safety: cap using left_col_w and page_avail_h
            cur_w = float(getattr(img, 'drawWidth', getattr(img, 'imageWidth', left_col_w)))
            cur_h = float(getattr(img, 'drawHeight', getattr(img, 'imageHeight', page_avail_h * 0.6)))
            max_w = min(left_col_w, frame_w * 0.95)
            max_h = min(page_avail_h * 0.6, page_avail_h * 0.95)
            s_w = max_w / cur_w if cur_w > 0 else 1.0
            s_h = max_h / cur_h if cur_h > 0 else 1.0
            s = min(1.0, s_w, s_h)
            if s < 1.0:
                img.drawWidth = cur_w * s
                img.drawHeight = cur_h * s
        except Exception:
            img = safe_image(recipe.get("thumbnail"))
        try:
            img._restrictSize(left_col_w, page_avail_h * 0.95)
        except Exception:
            pass
        img.hAlign = "CENTER"

        # measure right column flowables
        right_measures = []
        total_right_h = 0.0
        for flow in right_col:
            try:
                # use the inner content width (subtracting left/right paddings)
                w, h = flow.wrap(right_col_inner_w, page_avail_h)
            except Exception:
                h = 14 * max(1, (len(getattr(flow, 'text', '') or '').splitlines()))
                w = right_col_inner_w
            right_measures.append((flow, w, h))
            total_right_h += h

        # If any single flowable is already taller than the allowed row height
        # then side-by-side will never work for this recipe; prefer stacking.
        max_single_h = max((h for (_f, _w, h) in right_measures), default=0.0)

        img_h = float(getattr(img, 'drawHeight', getattr(img, 'imageHeight', 6.0*inch)))
        # Account for table paddings when deciding if a single table row
        # containing the image and the right column will fit on the page.
        # Our table style uses TOPPADDING/BOTTOMPADDING = 16 each (see below),
        # so subtract those paddings (and a tiny safety margin) from the
        # available page height when comparing.
        table_vertical_padding = 16 + 16
        # increase safety margin to avoid near-miss LayoutErrors seen in the wild
        safety_margin = 14
        allowed_row_h = page_avail_h - table_vertical_padding - safety_margin

        # If the image itself is still taller than the allowed row height,
        # scale it down proportionally now so the table row can never exceed
        # the page frame (this is the critical guard against LayoutError).
        try:
            if img_h > max(1.0, allowed_row_h):
                scale_img = float(allowed_row_h) / float(img_h)
                img.drawWidth = float(getattr(img, 'drawWidth', getattr(img, 'imageWidth', 3.7*inch))) * scale_img
                img.drawHeight = float(getattr(img, 'drawHeight', getattr(img, 'imageHeight', 6.0*inch))) * scale_img
                img_h = float(getattr(img, 'drawHeight', getattr(img, 'imageHeight', 6.0*inch)))
        except Exception:
            pass

        if max(img_h, total_right_h) <= allowed_row_h and max_single_h <= allowed_row_h:
            # fits entirely side-by-side
            # Use FixedImage wrapper so the table uses the exact wrap size
            # we computed for the image (avoids later layout resizing).
            cell_img = FixedImage(getattr(img, 'filename', None), getattr(img, 'drawWidth', getattr(img, 'imageWidth', 3.7*inch)), getattr(img, 'drawHeight', getattr(img, 'imageHeight', 6.0*inch)))
            # Do a conservative re-measure of the right-column height using a
            # slightly narrower width than the true inner width to account for
            # any subtle table/layout differences. If the conservative
            # measurement still fits, we append the table; otherwise fall
            # through to the split/stack logic below.
            extra_margin = 12
            conservative_w = max(1.0, right_col_inner_w - extra_margin)
            conservative_total = 0.0
            for f in right_col:
                try:
                    _w, _h = f.wrap(conservative_w, page_avail_h)
                except Exception:
                    _h = 14 * max(1, (len(getattr(f, 'text', '') or '').splitlines()))
                conservative_total += _h

            t = Table([[cell_img, right_col]],
                      colWidths=[left_col_w, col2_outer_w],
                      style=[
                          ("VALIGN", (0, 0), (-1, -1), "TOP"),
                          ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF9F3")),
                          ("LEFTPADDING", (0, 0), (-1, -1), 18),
                          ("RIGHTPADDING", (0, 0), (-1, -1), 18),
                          ("TOPPADDING", (0, 0), (-1, -1), 16),
                          ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
                      ])
            # Only append the table if our conservative measurement predicts it fits
            # require a modest safety factor on conservative_total to avoid
            # underestimation causing Table row overflow during actual layout
            safety_factor = 0.95
            if max(img_h, conservative_total) <= allowed_row_h * safety_factor:
                story.append(t)
                story.append(Spacer(1, 0.4 * inch))
                # append full-width instructions below the image+ingredients block
                if instr_flow:
                    story.extend(instr_flow)
                    story.append(Spacer(1, 0.4 * inch))
            else:
                # don't append the oversized table; fall through to splitting
                # logic below which will attempt a top-slice or stacking
                pass
        else:
            # try to take a top slice that fits next to the image
            prefix_h = 0.0
            k = 0
            for (flow, w, h) in right_measures:
                # make the same allowance for table paddings when building
                # a prefix that will sit next to the image
                if prefix_h + h > allowed_row_h:
                    break
                prefix_h += h
                k += 1

            if k > 0 and max(img_h, prefix_h) <= allowed_row_h:
                right_top = [fm[0] for fm in right_measures[:k]]
                right_bottom = [fm[0] for fm in right_measures[k:]]
                cell_img = FixedImage(getattr(img, 'filename', None), getattr(img, 'drawWidth', getattr(img, 'imageWidth', 3.7*inch)), getattr(img, 'drawHeight', getattr(img, 'imageHeight', 6.0*inch)))
                # conservative re-measure for the top slice as well
                extra_margin = 12
                conservative_w = max(1.0, right_col_inner_w - extra_margin)
                conservative_top = 0.0
                for f in right_top:
                    try:
                        _w, _h = f.wrap(conservative_w, page_avail_h)
                    except Exception:
                        _h = 14 * max(1, (len(getattr(f, 'text', '') or '').splitlines()))
                    conservative_top += _h

                t = Table([[cell_img, right_top]],
                          colWidths=[left_col_w, col2_outer_w],
                          style=[
                              ("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF9F3")),
                              ("LEFTPADDING", (0, 0), (-1, -1), 18),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 18),
                              ("TOPPADDING", (0, 0), (-1, -1), 16),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
                          ])
                # Only append the top-slice table if our conservative
                # measurement predicts it fits side-by-side.
                safety_factor = 0.95
                if max(img_h, conservative_top) <= allowed_row_h * safety_factor:
                    story.append(t)
                    story.append(Spacer(1, 0.08*inch))
                    story.extend(right_bottom)
                    story.append(Spacer(1, 0.4 * inch))
                    # append instructions below the block
                    if instr_flow:
                        story.extend(instr_flow)
                        story.append(Spacer(1, 0.4 * inch))
                else:
                    # Fall back to stacking when the conservative check fails
                    story.append(FixedImage(getattr(img, 'filename', None), getattr(img, 'drawWidth', getattr(img, 'imageWidth', 3.7*inch)), getattr(img, 'drawHeight', getattr(img, 'imageHeight', 6.0*inch))))
                    story.append(Spacer(1, 0.06*inch))
                    story.extend(right_col)
                    story.append(Spacer(1, 0.4 * inch))
                    if instr_flow:
                        story.extend(instr_flow)
                        story.append(Spacer(1, 0.4 * inch))
            else:
                # fallback: stack image above the full right column
                # For stacked layout we can append the original Image flowable
                # (already sized), but wrap it in FixedImage too to be safe.
                story.append(FixedImage(getattr(img, 'filename', None), getattr(img, 'drawWidth', getattr(img, 'imageWidth', 3.7*inch)), getattr(img, 'drawHeight', getattr(img, 'imageHeight', 6.0*inch))))
                story.append(Spacer(1, 0.06*inch))
                story.extend(right_col)
                story.append(Spacer(1, 0.4 * inch))
                if instr_flow:
                    story.extend(instr_flow)
                    story.append(Spacer(1, 0.4 * inch))

    doc.build(
        story,
        onFirstPage=lambda c, d: (background(c, d), footer(c, d)),
        onLaterPages=lambda c, d: (background(c, d), footer(c, d)),
    )
    print(f"✅ Cookbook saved as {OUTPUT_PDF}")

def main():
    L = instaloader.Instaloader(download_videos=False, download_comments=False, save_metadata=False)
    try:
        L.load_session_from_file(SESSION_USER)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"⚠️ Could not load session: {e}")

    recipes = []
    for url in REEL_URLS:
        data = fetch_reel_data_with_instaloader(url, L)
        if data:
            recipes.append(data)

    if recipes:
        create_pdf(recipes)
    else:
        print("No valid reels found.")

if __name__ == "__main__":
    main()
