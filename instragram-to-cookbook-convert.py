import instaloader
import qrcode
from bs4 import BeautifulSoup  # kept for future extensions
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, Table, TableStyle,
    ListFlowable, ListItem, HRFlowable, KeepTogether
)
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
    "https://www.instagram.com/p/DQkSEWPEiwb/",
    "https://www.instagram.com/reel/DQfpG1ZDJqD/",
]
OUTPUT_PDF = "instagram-cookbook.pdf"
SESSION_USER = "your_instagram_username"  # for private reels access
# ------------------------

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
    t = text or ""
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
        m_instr2 = re.search(r"(?im)^\s*(Instructions?|Directions?|Steps?|To\s+make)\s*:?\s*$", rest, flags=re.M)
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
    m_instr = re.search(r"(?im)^\s*(?:👩‍🍳\s*)?(Instructions?|Directions?|Steps?|To\s+make)\s*:?\s*$", after_ing, flags=re.M)
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

    return [parse_typography(s) for s in steps if s]


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
    doc = SimpleDocTemplate(
        OUTPUT_PDF, pagesize=A4,
        rightMargin=50, leftMargin=50, topMargin=60, bottomMargin=60
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="RecipeTitle", fontSize=16, leading=22, alignment=1,
        fontName="Helvetica-Bold", textColor=colors.HexColor("#253358"), spaceAfter=10
    ))
    styles.add(ParagraphStyle(
        name="SmallText", fontSize=11, leading=12, fontName="Helvetica",
        textColor=colors.HexColor("#444444"), spaceAfter=2
    ))
    styles.add(ParagraphStyle(
        name="HeaderSection", fontSize=14, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#16537e"), spaceAfter=8
    ))
    styles.add(ParagraphStyle(
        name="RecipeText", fontSize=11, leading=15, alignment=4,
        fontName="Helvetica", textColor=colors.HexColor("#333333"), spaceAfter=4
    ))
    styles.add(ParagraphStyle(
        name="MacroText", fontSize=11, leftIndent=10,
        textColor=colors.HexColor("#268762"), spaceBefore=2, spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        name="NoteText", fontSize=11, leftIndent=10,
        textColor=colors.HexColor("#888822"), spaceBefore=2, spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        name="ListHeader", fontSize=12, leading=14, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#16537e"), spaceBefore=6, spaceAfter=2
    ))

    story = []
    temp_files = []

    for i, recipe in enumerate(recipes):
        # Optional time/servings parsed from general text
        servings_hint, time_hint = parse_icons(recipe["caption"])
        # Structured parse
        parsed = split_sections_strict(recipe["caption"])
        # Build summary line bits
        summary_bits = []
        if parsed["servings"]:
            summary_bits.append(f"Serves {parsed['servings']}")
        m = parsed["macros"]
        macro_bits = []
        if m["cal"] is not None: macro_bits.append(f"{m['cal']} Calories")
        if m["protein"] is not None: macro_bits.append(f"{m['protein']}g Protein")
        if m["carbs"] is not None: macro_bits.append(f"{m['carbs']}g Carbs")
        if m["fat"] is not None: macro_bits.append(f"{m['fat']}g Fat")
        if macro_bits:
            summary_bits.append(" | ".join(macro_bits))

        # Top block with image on left and ingredients on right
        top_block = make_top_block(
            recipe["thumbnail"],
            styles,
            clean_title(recipe["title"]),
            summary_bits,
            parsed["blurb"],
            parsed["ingredients"]
        )
        # make_top_block may return either a single Flowable (Table) or
        # a list of Flowables (stacked layout). Handle both.
        if isinstance(top_block, list):
            story.extend(top_block)
        else:
            story.append(top_block)
        story.append(Spacer(1, 0.15*inch))

        # Full-width Instructions
        if parsed["instructions"]:
            story.append(Paragraph("Instructions", styles["HeaderSection"]))
            story.append(ListFlowable(
                [ListItem(Paragraph(step, styles["RecipeText"])) for step in parsed["instructions"]],
                bulletType="1", leftIndent=14
            ))
            story.append(Spacer(1, 0.12*inch))

        # Notes
        if parsed["notes"]:
            story.append(Paragraph("Notes", styles["HeaderSection"]))
            story.append(Paragraph(parsed["notes"], styles["RecipeText"]))
            story.append(Spacer(1, 0.08*inch))

        # QR footer
        qr_path = generate_qr_code(recipe["url"])
        temp_files.append(qr_path)
        qr_img = Image(qr_path, width=1.0*inch, height=1.0*inch)
        qr_table = Table([[Paragraph("Scan for Reel", styles["SmallText"]), qr_img]],
                        colWidths=[1.4*inch, 1.0*inch], hAlign="RIGHT")
        qr_table.setStyle(TableStyle([
            ("ALIGN",(1,0),(1,0),"RIGHT"),
            ("VALIGN",(0,0),(-1,-1),"MIDDLE")
        ]))
        story.append(qr_table)

        if i < len(recipes) - 1:
            story.append(PageBreak())

    doc.build(story)

    # Cleanup
    for recipe in recipes:
        thumb = recipe.get("thumbnail")
        if thumb and os.path.exists(thumb):
            try:
                os.remove(thumb)
            except Exception as e:
                print(f"⚠️ Could not delete thumbnail {thumb}: {e}")
    for path in temp_files:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                print(f"⚠️ Could not delete QR file {path}: {e}")
    print(f"✅ Cleaner cookbook saved as {OUTPUT_PDF}")

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
