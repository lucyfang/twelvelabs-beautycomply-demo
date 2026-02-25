"""
app.py — AdSafe: Ad Compliance & Brand Safety
TwelveLabs Solutions Engineer Demo · February 2026

Run:
    pip install streamlit requests pillow
    streamlit run app.py
"""

import json
import time
from typing import Optional

import requests
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AdSafe — Compliance Review",
    page_icon="🐎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Fraunces:opsz,wght@9..144,300;9..144,600&display=swap');

  html, body, [class*="css"] { font-family: 'DM Mono', monospace; }
  h1, h2, h3 { font-family: 'Fraunces', serif; letter-spacing: -0.02em; }

  .verdict-APPROVE {
    background: #C8FF00; color: #0A0A0A;
    border: none;
    box-shadow: 0 0 18px 4px rgba(200,255,0,0.45), 0 2px 8px rgba(0,0,0,0.4);
  }
  .verdict-REVIEW {
    background: #FFB800; color: #0A0A0A;
    border: none;
    box-shadow: 0 0 18px 4px rgba(255,184,0,0.45), 0 2px 8px rgba(0,0,0,0.4);
  }
  .verdict-BLOCK {
    background: #FF4444; color: #FFFFFF;
    border: none;
    box-shadow: 0 0 18px 4px rgba(255,68,68,0.5), 0 2px 8px rgba(0,0,0,0.4);
  }

  .verdict-badge {
    display: inline-block; padding: 10px 28px; border-radius: 3px;
    font-size: 1.6rem; font-weight: 700; letter-spacing: 0.15em;
    font-family: 'DM Mono', monospace; text-transform: uppercase;
  }
  .policy-pass { color:#C8FF00; font-weight:600; }
  .policy-warn { color:#FFB800; font-weight:600; }
  .policy-fail { color:#FF4444; font-weight:600; }
  .conf-high   { color:#888880; }
  .conf-medium { color:#FFB800; }
  .conf-low    { color:#FF4444; }

  .timestamp-chip {
    display:inline-block; background:#1E1E1E; color:#C8FF00;
    border: 1px solid #2A2A2A; border-radius:2px;
    padding:2px 8px; font-size:0.75rem;
    margin-right:4px; margin-bottom:4px;
  }
  .evidence-block {
    background:#141414; border-left:3px solid #C8FF00;
    padding:10px 14px; border-radius:0 4px 4px 0;
    margin-top:6px; font-size:0.85rem; color:#F0F0EB;
  }
  .reasoning-block {
    background:#141414; border-left:3px solid #2A2A2A;
    padding:8px 14px; border-radius:0 4px 4px 0;
    margin-top:6px; font-size:0.82rem; color:#888880; font-style:italic;
  }
  /* All buttons — purple */
  .stButton>button {
    background: #6366f1 !important; color: white !important;
    border: none !important; border-radius: 4px !important;
    font-family: 'DM Mono', monospace !important;
    font-size: 0.82rem !important; width: 100% !important;
  }
  .stButton>button:hover { background: #4f46e5 !important; }
</style>
""", unsafe_allow_html=True)


# ── Constants ─────────────────────────────────────────────────────────────────
BASE_URL = "https://api.twelvelabs.io/v1.3"

POLICY_CATEGORIES = [
    "hate_harassment",
    "profanity_explicit",
    "drugs_illegal",
    "unsafe_product_usage",
    "medical_cosmetic_claims",
]

POLICY_LABELS = {
    "hate_harassment":         "Hate / Harassment",
    "profanity_explicit":      "Profanity / Explicit Language",
    "drugs_illegal":           "Drugs / Illegal Behavior",
    "unsafe_product_usage":    "Unsafe / Misleading Product Usage",
    "medical_cosmetic_claims": "Medical or Cosmetic Claims",
}

# Semantic search queries per policy — used to fetch timestamped evidence clips
POLICY_SEARCH_QUERIES = {
    "hate_harassment":         "hate speech harassment discriminatory slur derogatory language mocking",
    "profanity_explicit":      "profanity swearing explicit language cursing offensive words",
    "drugs_illegal":           "drug use smoking vaping illegal activity substance paraphernalia",
    "unsafe_product_usage":    "unsafe product application near eye unsanitary technique dangerous misuse",
    "medical_cosmetic_claims": "clinically proven treats cures dermatologist approved heals skin condition",
}

STATUS_ICON = {"pass": "✅", "warn": "⚠️", "fail": "🚫"}
CONF_ICON   = {"high": "🟢", "medium": "🟡", "low": "🔴"}


# ── TwelveLabs API layer ──────────────────────────────────────────────────────

def auth_headers(api_key: str) -> dict:
    """JSON auth headers — for endpoints that accept application/json."""
    return {"x-api-key": api_key, "Content-Type": "application/json"}


def parse_stream(response_text: str) -> str:
    """
    TwelveLabs /analyze always responds with NDJSON streaming.
    Each line is a JSON event with event_type in:
      stream_start | text_generation | stream_end

    Concatenate all text_generation chunks in order to reconstruct
    the full model output. Never use r.json() or dict.update() here —
    both silently discard all but the last chunk.
    """
    chunks = []
    for line in response_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event_type") == "text_generation":
            chunks.append(event.get("text", ""))
    return "".join(chunks)


def create_index(api_key: str, name: str) -> str:
    """Create a new index with both Pegasus (analyze) and Marengo (search)."""
    payload = {
        "name": name,
        "models": [
            {"name": "pegasus1.2", "options": ["visual", "audio"]},
            {"name": "marengo3.0", "options": ["visual", "audio"]},
        ],
    }
    r = requests.post(f"{BASE_URL}/indexes", headers=auth_headers(api_key), json=payload)
    r.raise_for_status()
    data = r.json()
    return data.get("_id") or data.get("id")


def upload_video_url(api_key: str, index_id: str, video_url: str) -> str:
    """
    Upload a video by public URL.
    Field names: video_url (not url), index_id — confirmed in TwelveLabs v1.3 docs.
    Must use files= to force multipart/form-data. data= sends urlencoded which is rejected.
    Non-file fields are passed as (None, value) tuples inside files= list.
    """
    r = requests.post(
        f"{BASE_URL}/tasks",
        headers={"x-api-key": api_key},
        files=[
            ("index_id",   (None, index_id)),
            ("video_url",  (None, video_url)),
            ("language",   (None, "en")),
        ],
    )
    if not r.ok:
        raise RuntimeError(f"Upload failed ({r.status_code}): {r.text}")
    data = r.json()
    return data.get("_id") or data.get("id")


def upload_video_file(api_key: str, index_id: str, file_bytes: bytes, filename: str) -> str:
    """
    Upload a local video file.
    video_file sent as file attachment; index_id as regular form field.
    Both go in the same multipart request using files= + data=.
    Max size: 2 GB per TwelveLabs docs.
    """
    r = requests.post(
        f"{BASE_URL}/tasks",
        headers={"x-api-key": api_key},
        files={"video_file": (filename, file_bytes, "video/mp4")},
        data={"index_id": index_id, "language": "en"},
    )
    if not r.ok:
        raise RuntimeError(f"Upload failed ({r.status_code}): {r.text}")
    data = r.json()
    return data.get("_id") or data.get("id")


def poll_task(api_key: str, task_id: str, timeout: int = 360) -> str:
    """Poll until indexing task is ready. Returns video_id."""
    start = time.time()
    while time.time() - start < timeout:
        r = requests.get(f"{BASE_URL}/tasks/{task_id}", headers=auth_headers(api_key))
        r.raise_for_status()
        data = r.json()
        status = data.get("status")
        if status == "ready":
            return data.get("video_id")
        if status in ("failed", "error"):
            raise RuntimeError(f"Indexing failed: {data}")
        time.sleep(5)
    raise TimeoutError("Video indexing timed out after 6 minutes.")


def _pillarbox_png(data: bytes, w: int, h: int) -> bool:
    """Sample PNG pixel columns to detect black bars on the sides."""
    import zlib
    color_type = data[25]
    bit_depth  = data[24]
    if color_type not in (2, 6) or bit_depth != 8:
        return False
    channels = 4 if color_type == 6 else 3
    idat = b''
    pos  = 8
    while pos < len(data) - 12:
        length     = int.from_bytes(data[pos:pos+4], 'big')
        chunk_type = data[pos+4:pos+8]
        if chunk_type == b'IDAT':
            idat += data[pos+8:pos+8+length]
        elif chunk_type == b'IEND':
            break
        pos += 12 + length
    raw    = zlib.decompress(idat)
    stride = 1 + w * channels
    rows   = [int(h * f) for f in (0.25, 0.4, 0.5, 0.6, 0.75)]
    bar_w  = max(1, int(w * 0.08))

    def avg(row_idx, x0, n):
        base = row_idx * stride + 1
        return sum(
            sum(raw[base + x*channels : base + x*channels + 3]) / 3
            for x in range(x0, x0 + n)
        ) / n

    left_b   = sum(avg(r, 0, bar_w) for r in rows) / len(rows)
    right_b  = sum(avg(r, w - bar_w, bar_w) for r in rows) / len(rows)
    center_b = sum(avg(r, w//2 - bar_w//2, bar_w) for r in rows) / len(rows)
    return left_b < 30 and right_b < 30 and center_b > 60


def _detect_pillarbox(thumbnail_url: str, api_key: str = "") -> bool:
    """
    Download the video thumbnail and detect whether a horizontal-container
    video actually contains vertical (9:16) content surrounded by black bars.

    Uses Pillow (PIL) for reliable JPEG + PNG pixel sampling — Pillow is a
    lightweight, widely-available package included in requirements.txt.
    Falls back to the stdlib PNG-only path if Pillow is not installed.
    Fails silently in all error cases — caller treats result as not pillarboxed.

    Detection logic: sample left 8%, center, and right 8% column strips across
    5 evenly-spaced rows. If both side strips average near-black (brightness <30)
    while the center is significantly brighter (>60), content is pillarboxed.
    """
    try:
        import urllib.request, io
        headers = {"User-Agent": "Mozilla/5.0"}
        if api_key:
            headers["x-api-key"] = api_key
        req = urllib.request.Request(thumbnail_url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            img_bytes = resp.read()

        try:
            from PIL import Image
            img  = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            w, h = img.size
            bar_w   = max(1, int(w * 0.08))
            rows    = [int(h * f) for f in (0.25, 0.4, 0.5, 0.6, 0.75)]
            center_x = w // 2 - bar_w // 2

            def strip_brightness(x0, y_list):
                total = 0
                for y in y_list:
                    for x in range(x0, x0 + bar_w):
                        r, g, b = img.getpixel((x, y))
                        total += (r + g + b) / 3
                return total / (bar_w * len(y_list))

            left_b   = strip_brightness(0, rows)
            right_b  = strip_brightness(w - bar_w, rows)
            center_b = strip_brightness(center_x, rows)
            return left_b < 30 and right_b < 30 and center_b > 60

        except ImportError:
            # Pillow not installed — fall back to PNG-only stdlib path
            import struct
            if img_bytes[:8] == b'\x89PNG\r\n\x1a\n':
                pw = struct.unpack('>I', img_bytes[16:20])[0]
                ph = struct.unpack('>I', img_bytes[20:24])[0]
                return _pillarbox_png(img_bytes, pw, ph)
            return False

    except Exception:
        return False


def get_video_meta(api_key: str, index_id: str, video_id: str) -> dict:
    """
    Fetch video metadata from GET /indexes/{index_id}/videos/{video_id}.
    Returns dict with keys:
      url           (str|None)  — HLS playback URL
      is_vertical   (bool)      — True if content is portrait orientation
      thumbnail_url (str|None)  — first thumbnail for preview

    Vertical detection:
      1. If container height > width → definitively vertical.
      2. If container is 16:9 (horizontal) but aspect ratio is close to 16:9,
         attempt pillarbox detection via thumbnail to catch vertical-in-horizontal.
         Falls back to False if thumbnail unavailable.
    """
    r = requests.get(
        f"{BASE_URL}/indexes/{index_id}/videos/{video_id}",
        headers=auth_headers(api_key),
    )
    if not r.ok:
        return {"url": None, "is_vertical": False, "thumbnail_url": None}
    data      = r.json()
    hls       = data.get("hls") or {}
    url       = hls.get("video_url")
    thumbs    = hls.get("thumbnail_urls") or []
    thumb_url = thumbs[0] if thumbs else None
    meta      = data.get("system_metadata") or {}
    w, h      = meta.get("width", 1), meta.get("height", 1)

    # Primary check: container is portrait
    if h > w:
        return {"url": url, "is_vertical": True, "thumbnail_url": thumb_url}

    # Secondary check: 16:9 container — could be pillarboxed vertical content
    aspect = w / h if h else 1
    if 1.7 <= aspect <= 1.85 and thumb_url:
        is_pillarboxed = _detect_pillarbox(thumb_url, api_key)
        return {"url": url, "is_vertical": is_pillarboxed, "thumbnail_url": thumb_url}

    return {"url": url, "is_vertical": False, "thumbnail_url": thumb_url}


def analyze_video(api_key: str, video_id: str, prompt: str) -> str:
    """
    Call TwelveLabs Analyze API (Pegasus). Returns concatenated text output.
    Note: renamed from /generate to /analyze in API v1.3 (June 4, 2025).
    Response is always NDJSON streaming — use parse_stream(), never r.json().
    """
    # TwelveLabs hard limit is 8,000 chars. Our base policy prompt is ~6,485 chars,
    # leaving ~1,315 chars for brand + product + brief combined.
    # Guard fires 200 chars before the limit so the API never sees an oversized prompt.
    MAX_PROMPT_CHARS = 7800
    BASE_PROMPT_CHARS = 6485   # length of prompt with empty brand/product/brief
    CONTEXT_BUDGET    = MAX_PROMPT_CHARS - BASE_PROMPT_CHARS
    if len(prompt) > MAX_PROMPT_CHARS:
        context_used = len(prompt) - BASE_PROMPT_CHARS
        over_by      = len(prompt) - MAX_PROMPT_CHARS
        raise ValueError(
            f"Campaign context is too long — please shorten your Campaign Description "
            f"in the sidebar by at least {over_by:,} characters.\n\n"
            f"How the limit works:\n"
            f"  The TwelveLabs Analyze API accepts a maximum of 8,000 characters per prompt.\n"
            f"  The compliance policy rules occupy ~{BASE_PROMPT_CHARS:,} of those characters,\n"
            f"  leaving {CONTEXT_BUDGET:,} characters for your brand, product, and brief combined.\n\n"
            f"  Total prompt limit:               {MAX_PROMPT_CHARS:,} chars\n"
            f"  Policy rules (fixed):            ~{BASE_PROMPT_CHARS:,} chars\n"
            f"  Budget for campaign context:      {CONTEXT_BUDGET:,} chars\n"
            f"  Currently using:                  {context_used:,} chars\n"
            f"  Over by:                          {over_by:,} chars"
        )

    r = requests.post(
        f"{BASE_URL}/analyze",
        headers=auth_headers(api_key),
        json={"video_id": video_id, "prompt": prompt},
    )
    if not r.ok:
        raise RuntimeError(
            f"Analyze API failed ({r.status_code}): {r.text[:600]}"
        )
    return parse_stream(r.text)


def search_clips(api_key: str, index_id: str, video_id: str,
                 query: str, page_limit: int = 3) -> list[dict]:
    """
    Semantic search for timestamped clips matching a query.

    Key v1.3 / Marengo 3.0 changes applied here:
      - Endpoint requires multipart/form-data (not JSON) → use files= not json=
      - Array fields (search_options) must be repeated as separate form entries,
        not JSON-stringified (e.g. two ("search_options", (None, "visual")) tuples)
      - "audio" no longer includes speech → use "transcription" for spoken words
      - "score" and "confidence" fields removed → use "rank" for ordering
      - Threshold "medium" enforces a genuine similarity floor (avoids returning
        irrelevant clips just because they're the closest available)
    """
    multipart = [
        ("index_id",       (None, index_id)),
        ("query_text",     (None, query)),
        ("search_options", (None, "visual")),
        ("search_options", (None, "transcription")),
        ("threshold",      (None, "medium")),
        ("page_limit",     (None, str(page_limit))),
        ("filter",         (None, json.dumps({"id": [video_id]}))),
    ]
    r = requests.post(
        f"{BASE_URL}/search",
        headers={"x-api-key": api_key},
        files=multipart,
    )
    r.raise_for_status()
    return r.json().get("data", [])


# ── Compliance engine ─────────────────────────────────────────────────────────

def build_compliance_prompt(brand: str, product: str, brief: str) -> str:
    """
    Full policy prompt grounded in:
      - GARM Brand Safety Floor + Suitability Framework (2022)
      - FTC Endorsement Guides (revised July 2023, 16 CFR Part 255)
      - FDA FD&C Act cosmetic/drug claim distinction (21 U.S.C. §321)

    High-severity threshold: any detectable infringement = minimum WARN.
    """
    return f"""
You are a strict compliance reviewer for a social media ad platform evaluating
creator beauty/cosmetics videos before paid promotion.

REVIEWER MINDSET: Apply strict liability, not reasonable-viewer judgment. Default
to FLAG not PASS. Do not use world knowledge to infer safety or acceptability —
only evidence visible or audible in the video counts. "Everyone does it" is never
a defence. A false positive costs one review; a false negative costs brand
reputation and legal exposure.

CAMPAIGN CONTEXT
Brand:   {brand}
Product: {product}
Brief:   {brief}

POLICIES

P1 HATE/HARASSMENT (GARM Cat.6)
FAIL: slurs or dehumanizing language targeting race, ethnicity, religion, gender,
sexual orientation, disability, or nationality (spoken, on-screen, or in background);
mocking/stereotyping a group; hate movement symbols; derogatory body commentary
(fat-shaming, colorism, ageism); language framing lighter/brighter skin as the goal
or improvement (colorism as product benefit).
WARN: edgy humor interpretable as demeaning; comparative language implying one skin
tone/type is superior; exclusionary framing; self-directed derogatory language about
own appearance normalizing negative body image (e.g. "my skin is so disgusting").
PASS: inclusive or neutral language; no demeaning content of any kind.

P2 PROFANITY (GARM Cat.3)
FAIL: strong profanity (f/s/c-word or equivalent in ANY language including
code-switching); slurs as profanity; sexually explicit language; graphic violence.
WARN: mild profanity ("damn","hell","ass","crap","bitch","bastard") even casually;
bleeped/censored profanity (audible intent flagged); suggestive language.
PASS: all language clean and appropriate for general audiences.

P3 DRUGS/ILLEGAL (GARM Cat.4)
FAIL: illegal drug use depicted, glorified, or referenced positively; drug
paraphernalia visible; tobacco/cigarette smoking shown approvingly; vaping or
e-cigarettes in any context; illegal activity depicted or normalized; creator
visibly intoxicated during demo.
WARN: alcohol prominently consumed on camera; prescription skincare (tretinoin,
Accutane, antibiotics) mentioned alongside product in a way that frames product
as part of a prescription regimen; casual references to past substance use.
PASS: no substances, paraphernalia, or illegal activity visible or referenced.

P4 UNSAFE PRODUCT USAGE (FDA cosmetic safety)
CRITICAL — WATERLINE: Any product applied to waterline/inner eyelid is FAIL unless
on-screen text explicitly states "ophthalmologist tested for waterline use". Do not
infer safety from product category or common usage.
FAIL: waterline/ocular application; product on broken skin; ingested/inhaled;
dangerous combos (high-AHA + retinol; undiluted essential oils); double-dipping any
tool after skin contact; visibly dirty tools; tester products on face; expired product.
WARN: sloppy technique; tools appear unclean but double-dipping unconfirmed; adjacent
to (not on) waterline; inadvisable combo without caveat.
PASS: safe application per intended use; no eye-area contact; no unsanitary technique.

P5 MEDICAL/COSMETIC CLAIMS (FDA FD&C §201; FTC 16 CFR Part 255)
CRITICAL — SILENT VISUAL CLAIMS: Before/after montage implying structural results
is a drug claim even with no words spoken. Flag it.
CRITICAL — THIRD-PARTY CLAIMS: "My dermatologist said X" is an unsubstantiated
authority claim even when quoted. FTC rules apply regardless of attribution.
FAIL: disease treatment claims (treats/cures/heals acne, eczema, rosacea, etc.);
structural/physiological claims (regenerates cells, stimulates collagen, shrinks
pores, removes wrinkles, eliminates cellulite); hedged superlatives ("might be the
most hydrating" — hedging does not remove the superlative); unsubstantiated claims
("clinically proven" without study, "dermatologist approved" without basis, "#1"
without source); third-party authority claims; before/after visual drug claims;
FTC disclosure missing or not at START of video (spoken or large on-screen text).
WARN: borderline structure-function ("helps repair skin"); "clinically tested"
without outcome; before/after without lighting disclaimer; disclosure present but
after 30s or small text.
PASS: appearance-only claims ("looks smoother", "feels hydrated", "reduces
appearance of"); paid/gifted disclosed clearly at start; no structural claims.

CAMPAIGN RELEVANCE
Evaluate strictly against Brand, Product, and Brief above.
HARD RULE: If the video has nothing to do with beauty, cosmetics, or skincare at all
(e.g. sports, gaming, entertainment, news, cooking, travel), score it 0 and mark
off_brief immediately — do not attempt to find partial relevance.
FAIL (off_brief): product/brand never mentioned or shown; primarily about a different
product or a completely different category; <20% content features this product. Score 0–39.
WARN (borderline): product mentioned but not the focus; 20–50% features this product.
Score 40–64.
PASS (on_brief): product is the clear subject of >50% of content; creator
demonstrates or discusses it by name; tone matches brief. Score 65–100.

OUTPUT — return ONLY valid JSON, no markdown, no preamble:
{{
  "description": "<2-4 sentences describing ONLY what you directly observe and hear in the video — do NOT reference the campaign brief, brand name, or product name unless the creator actually says/shows them. Describe the actual scene: setting, what the creator does, what they apply, what they say verbatim>",
  "verdict": "<APPROVE|REVIEW|BLOCK>",
  "verdict_reasoning": "<1-2 sentences>",
  "campaign_relevance": {{
    "status": "<on_brief|borderline|off_brief>",
    "score": <0-100>,
    "reasoning": "<one sentence>"
  }},
  "policies": {{
    "hate_harassment":         {{"status":"<pass|warn|fail>","confidence":"<high|medium|low>","timestamp_sec":<int|null>,"evidence":"<quote or none detected>","reasoning":"<one sentence>"}},
    "profanity_explicit":      {{"status":"<pass|warn|fail>","confidence":"<high|medium|low>","timestamp_sec":<int|null>,"evidence":"<quote or none detected>","reasoning":"<one sentence>"}},
    "drugs_illegal":           {{"status":"<pass|warn|fail>","confidence":"<high|medium|low>","timestamp_sec":<int|null>,"evidence":"<quote or none detected>","reasoning":"<one sentence>"}},
    "unsafe_product_usage":    {{"status":"<pass|warn|fail>","confidence":"<high|medium|low>","timestamp_sec":<int|null>,"evidence":"<quote or none detected>","reasoning":"<one sentence>"}},
    "medical_cosmetic_claims": {{"status":"<pass|warn|fail>","confidence":"<high|medium|low>","timestamp_sec":<int|null>,"evidence":"<quote or none detected>","reasoning":"<one sentence>"}}
  }}
}}

VERDICT RULES (strict order):
BLOCK   — ANY policy=fail OR campaign_relevance=off_brief
REVIEW  — ANY policy=warn OR campaign_relevance=borderline OR ANY confidence=low
APPROVE — ALL policies=pass AND on_brief AND all confidence>=medium

Return only valid JSON.
""".strip()


def run_compliance_check(api_key: str, video_id: str,
                          brand: str, product: str, brief: str) -> dict:
    """Call Analyze API and parse the structured JSON compliance result."""
    prompt = build_compliance_prompt(brand, product, brief)
    raw = analyze_video(api_key, video_id, prompt)

    # Strip markdown fences the model occasionally adds despite instructions
    cleaned = raw.strip()
    for prefix in ["```json", "```"]:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    cleaned = cleaned.removesuffix("```").strip()

    # First try: parse as-is
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Second try: Pegasus sometimes truncates mid-JSON, leaving unclosed braces/brackets.
    # Count open vs closed braces and append the missing closers.
    try:
        fixed = cleaned
        open_braces   = fixed.count("{") - fixed.count("}")
        open_brackets = fixed.count("[") - fixed.count("]")
        # Close any open string by checking if we're mid-value (odd number of unescaped quotes)
        # Simple heuristic: if last non-whitespace char isn't a closer, trim to last complete value
        fixed = fixed.rstrip()
        # If it ends mid-string or mid-value, trim back to last clean delimiter
        while fixed and fixed[-1] not in ('}', ']', '"', '0123456789'):
            fixed = fixed[:-1]
        # If ends with an incomplete key-value (trailing comma or colon), strip it
        fixed = fixed.rstrip(',').rstrip(':').rstrip()
        # Re-count after trimming
        open_braces   = fixed.count("{") - fixed.count("}")
        open_brackets = fixed.count("[") - fixed.count("]")
        fixed += "]" * open_brackets + "}" * open_braces
        return json.loads(fixed)
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse failed: {e}", "raw": raw}


def fetch_timestamped_evidence(api_key: str, index_id: str, video_id: str,
                                result: dict) -> dict[str, list[dict]]:
    """
    For each flagged policy (warn or fail), run a targeted semantic search
    to retrieve timestamped clip evidence. Returns empty list per policy
    if no clips meet the similarity threshold — this is expected and correct
    behavior; the Analyze verdict is still authoritative.
    """
    clips_by_policy = {}
    policies = result.get("policies", {})

    for key in POLICY_CATEGORIES:
        policy = policies.get(key, {})
        if policy.get("status") in ("warn", "fail"):
            # Prefer the specific evidence text Pegasus already identified — much more
            # targeted than a generic keyword bag, gives Marengo a precise quote to locate.
            # Fall back to the generic query only if evidence is empty or generic.
            evidence = policy.get("evidence", "")
            if evidence and evidence.lower() not in ("none detected", "none", "n/a", ""):
                query = evidence[:300]   # Marengo 3.0 supports up to 500 tokens; 300 chars is safe
            else:
                query = POLICY_SEARCH_QUERIES.get(key, key.replace("_", " "))
            try:
                clips = search_clips(api_key, index_id, video_id, query)
                clips_by_policy[key] = clips
            except Exception:
                clips_by_policy[key] = []   # don't let search failure break the verdict

    return clips_by_policy


# ── UI helpers ────────────────────────────────────────────────────────────────

def fmt_time(s: float) -> str:
    m, sec = divmod(int(s), 60)
    return f"{m}:{sec:02d}"


def render_verdict_badge(verdict: str):
    st.markdown(
        f'<span class="verdict-badge verdict-{verdict}">{verdict}</span>',
        unsafe_allow_html=True,
    )


def render_policy_row(key: str, policy: dict, clips: list[dict]):
    label      = POLICY_LABELS.get(key, key)
    status     = policy.get("status", "pass")
    confidence = policy.get("confidence", "high")
    evidence   = policy.get("evidence", "none detected")
    reasoning  = policy.get("reasoning", "")
    icon       = STATUS_ICON.get(status, "")
    conf_icon  = CONF_ICON.get(confidence, "")

    with st.expander(f"{icon} **{label}** — `{status.upper()}`  {conf_icon} confidence: `{confidence}`"):
        col_left, col_right = st.columns([1, 2])

        with col_left:
            css = {"pass": "policy-pass", "warn": "policy-warn", "fail": "policy-fail"}.get(status, "")
            st.markdown(f"**Status:** <span class='{css}'>{status.upper()}</span>", unsafe_allow_html=True)
            st.markdown(f"**Confidence:** <span class='conf-{confidence}'>{confidence}</span>", unsafe_allow_html=True)

        with col_right:
            if evidence and evidence != "none detected":
                ts = policy.get("timestamp_sec")
                ts_badge = f' <span class="timestamp-chip">⏱ {fmt_time(ts)}</span>' if ts is not None else ""
                st.markdown(
                    f'<div class="evidence-block">📌 <strong>Evidence:</strong>{ts_badge} {evidence}</div>',
                    unsafe_allow_html=True,
                )
            if reasoning:
                st.markdown(
                    f'<div class="reasoning-block">💬 {reasoning}</div>',
                    unsafe_allow_html=True,
                )

        if clips:
            starts = [fmt_time(int(c["start"])) + "–" + fmt_time(int(c.get("end", c["start"])))
                      for c in clips if c.get("start") is not None]
            chips  = "  ".join(
                f'<span class="timestamp-chip">⏱ {s}</span>' for s in starts
            )
            st.markdown(chips, unsafe_allow_html=True)
            st.caption("↑ click Jump buttons next to the player to seek")
        elif status in ("warn", "fail"):
            st.caption("No clips above similarity threshold — Analyze verdict is still authoritative.")


def render_results(result: dict, clips: dict, video_url: str):
    if "error" in result:
        st.error(f"Compliance check error: {result['error']}")
        st.code(result.get("raw", ""), language="text")
        return

    verdict   = result.get("verdict", "REVIEW")
    desc      = result.get("description", "")
    reasoning = result.get("verdict_reasoning", "")
    relevance = result.get("campaign_relevance", {})

    # ── Verdict + Campaign Relevance
    col_v, col_r = st.columns([1, 2])
    with col_v:
        st.markdown("### Verdict")
        render_verdict_badge(verdict)
        if reasoning:
            st.caption(reasoning)

    with col_r:
        st.markdown("### Campaign Relevance")
        rel_status = relevance.get("status", "unknown")
        rel_score  = relevance.get("score", 0)
        rel_reason = relevance.get("reasoning", "")
        color = {"on_brief": "#C8FF00", "off_brief": "#FF4444", "borderline": "#FFB800"}.get(rel_status, "#888880")
        st.markdown(
            f"<span style='color:{color};font-size:1.1rem;font-weight:600'>"
            f"{rel_status.replace('_', ' ').upper()}</span>",
            unsafe_allow_html=True,
        )
        st.progress(rel_score / 100)
        st.caption(f"Score: {rel_score}/100 — {rel_reason}")

    st.divider()

    # ── Video summary
    st.markdown("### Video Summary")
    st.info(desc)

    st.divider()

    # ── Video player with timestamp jump
    st.markdown("### Video")

    # Collect timestamps from two sources:
    # 1. Marengo search clips (precise, from semantic search)
    # 2. Pegasus timestamp_sec fields (direct from analysis — may be coarser but always present)
    ts_set = set()
    all_clips_flat = []   # (policy_label, start, end) for side panel
    for pol_key, clip_list in clips.items():
        for c in clip_list:
            if c.get("start") is not None:
                ts_set.add(int(c["start"]))
                all_clips_flat.append((POLICY_LABELS.get(pol_key, pol_key), int(c["start"]), int(c.get("end", c["start"]))))
    policies_data = result.get("policies", {})
    for pol_key, policy in policies_data.items():
        if policy.get("status") in ("warn", "fail"):
            ts = policy.get("timestamp_sec")
            if ts is not None:
                try:
                    ts_set.add(int(ts))
                except (TypeError, ValueError):
                    pass
    all_timestamps = sorted(ts_set)

    # video_url is None for local file uploads — fall back to stored bytes
    video_source = video_url or st.session_state.get("video_bytes")
    supports_seek = video_url is not None

    is_vertical = st.session_state.get("video_is_vertical", False)

    # Layout: player column + clip panel column
    # Vertical: narrow player [1], clips [2]  Horizontal: player [3], clips [2]
    player_ratio = [1, 2] if is_vertical else [3, 2]
    vid_col, clips_col = st.columns(player_ratio)

    with vid_col:
        if video_source is None:
            st.warning("No video source available for playback.")
        else:
            seek_to = st.session_state.get("seek_to", 0)
            if supports_seek and isinstance(video_source, str) and video_source.endswith(".m3u8"):
                # HLS stream — st.video can't seek HLS; use HLS.js in an iframe
                height = 340 if is_vertical else 310
                hls_html = f"""
<!DOCTYPE html><html><body style="margin:0;background:#000">
<video id="v" controls style="width:100%;height:{height}px;display:block" playsinline></video>
<script src="https://cdn.jsdelivr.net/npm/hls.js@1.4.12/dist/hls.min.js"></script>
<script>
  var src="{video_source}", t={seek_to};
  var v=document.getElementById("v");
  if(Hls.isSupported()){{
    var hls=new Hls();
    hls.loadSource(src);
    hls.attachMedia(v);
    hls.on(Hls.Events.MANIFEST_PARSED,function(){{v.currentTime=t;v.play();}});
  }}else if(v.canPlayType("application/vnd.apple.mpegurl")){{
    v.src=src; v.addEventListener("loadedmetadata",function(){{v.currentTime=t;v.play();}});
  }}
</script></body></html>"""
                st.components.v1.html(hls_html, height=height + 10)
            elif supports_seek:
                st.video(video_source, start_time=seek_to)
            else:
                if all_timestamps:
                    ts_str = "  ".join(fmt_time(t) for t in all_timestamps)
                    st.caption(f"⏱ Flagged moments: {ts_str} — seek manually")
                st.video(video_source)

    with clips_col:
        if all_clips_flat and supports_seek:
            st.markdown("**Jump to flagged clip:**")
            # Deduplicate by start time, preserve labels
            seen = {}
            for label, start, end in all_clips_flat:
                if start not in seen:
                    seen[start] = (label, end)
            for start in sorted(seen):
                label, end = seen[start]
                short_label = label.split(" / ")[0]
                st.markdown('<div class="clip-btn">', unsafe_allow_html=True)
                if st.button(
                    f"⏱ {fmt_time(start)}–{fmt_time(end)}  {short_label}",
                    key=f"sideclip_{start}",
                    use_container_width=True,
                ):
                    st.session_state["seek_to"] = start
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
        elif all_timestamps and supports_seek:
            # Pegasus timestamps only — no Marengo clips; show as simple buttons
            st.markdown("**Jump to flagged moment:**")
            for ts in all_timestamps:
                st.markdown('<div class="clip-btn">', unsafe_allow_html=True)
                if st.button(fmt_time(ts), key=f"sidets_{ts}", use_container_width=True):
                    st.session_state["seek_to"] = ts
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.caption("No flagged timestamps.")

    st.divider()

    # ── Policy scorecard
    st.markdown("### Policy Scorecard")
    policies = result.get("policies", {})

    # Summary bar — quick visual of all policy statuses
    cols = st.columns(len(POLICY_CATEGORIES))
    for i, key in enumerate(POLICY_CATEGORIES):
        policy = policies.get(key, {})
        status = policy.get("status", "pass")
        icon   = STATUS_ICON.get(status, "")
        with cols[i]:
            short_label = POLICY_LABELS[key].split(" / ")[0]
            st.markdown(f"<div style='text-align:center;font-size:1.4rem'>{icon}</div>", unsafe_allow_html=True)
            st.caption(f"<div style='text-align:center'>{short_label}</div>", unsafe_allow_html=True)

    st.markdown("")

    # Detailed expandable rows — only show flagged policies expanded by default
    for key in POLICY_CATEGORIES:
        policy = policies.get(key, {"status": "pass", "confidence": "high",
                                     "evidence": "none detected", "reasoning": ""})
        render_policy_row(key, policy, clips.get(key, []))

    st.divider()

    # Raw JSON — for technical credibility during the demo
    with st.expander("🔩 Raw JSON output"):
        st.json({"compliance_result": result, "timestamped_clips": clips})


# ── Sidebar ───────────────────────────────────────────────────────────────────

def sidebar() -> dict:
    with st.sidebar:
        st.markdown("# 🐎 AdSafe")
        st.caption("Ad Compliance & Brand Safety · Powered by TwelveLabs")
        st.divider()

        api_key = st.text_input(
            "TwelveLabs API Key", type="password",
            help="Get yours at platform.twelvelabs.io",
        )

        st.markdown("#### Campaign Brief")
        brand   = st.text_input("Brand name", value="GlowLux Cosmetics")
        product = st.text_input("Product / line", value="Radiance Serum Collection")
        brief   = st.text_area(
            "Campaign description",
            value=(
                "Beauty tutorials and GRWM content showcasing the new Radiance Serum line. "
                "Creator should demonstrate product application and highlight skincare benefits."
            ),
            height=110,
        )

        st.divider()
        st.markdown("#### Index")
        st.text_input(
            "Index ID",
            placeholder="699df534c10245a32100fbd3",
            help="Required for all modes. Leave blank only when creating a new index.",
            key="sidebar_index_id",
        )
        index_id_input = st.session_state.get("sidebar_index_id", "")
        create_new = st.checkbox(
            "Create new index instead",
            value=False,
            help="Check this to create a fresh index (ignores the Index ID above)",
        )
        index_name = ""
        if create_new:
            index_name = st.text_input("New index name", value="adsafe-demo")

        st.divider()
        st.caption("v1.3 API · Pegasus 1.2 + Marengo 3.0")

    return {
        "api_key":        api_key,
        "brand":          brand,
        "product":        product,
        "brief":          brief,
        "index_id_input": index_id_input,
        "create_new":     create_new,
        "index_name":     index_name,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    cfg = sidebar()

    st.markdown("# Ad Compliance Review")
    st.caption(
        "Submit a creator video to evaluate it for brand safety, "
        "policy compliance, and campaign relevance."
    )

    # ── Video input — URL, local file, or existing video ID
    upload_mode = st.radio(
        "Video source",
        ["Public URL", "Upload from desktop", "Existing video ID"],
        horizontal=True,
        help="Use 'Existing video ID' to skip upload entirely and re-analyze an already-indexed video",
    )

    video_url         = None
    uploaded_file     = None
    existing_video_id = None

    if upload_mode == "Public URL":
        video_url = st.text_input(
            "Creator video URL",
            placeholder="https://your-bucket.storage.googleapis.com/creator_video.mp4",
        )
    elif upload_mode == "Upload from desktop":
        uploaded_file = st.file_uploader(
            "Upload video file",
            type=["mp4", "mov", "avi", "webm", "mkv"],
            help="Max 2 GB per TwelveLabs limits",
        )
    else:
        st.text_input(
            "Video ID",
            placeholder="699df5702e1589888561be86",
            help="Paste any video_id from your index — no upload needed",
            key="input_video_id",
        )
        existing_video_id = st.session_state.get("input_video_id", "")
        st.caption("Index is taken from the sidebar. Video ID is shown there after any run, or find it in the TwelveLabs dashboard.")

    analyze_btn = st.button("🔍 Analyze Video")

    if analyze_btn:
        if not cfg["api_key"]:
            st.error("Please enter your TwelveLabs API key in the sidebar.")
            st.stop()
        if upload_mode == "Public URL" and not video_url:
            st.error("Please enter a video URL.")
            st.stop()
        if upload_mode == "Upload from desktop" and not uploaded_file:
            st.error("Please upload a video file.")
            st.stop()
        if upload_mode == "Existing video ID":
            if not existing_video_id:
                st.error("Please enter a video ID.")
                st.stop()
            if not cfg["index_id_input"]:
                st.error("Please enter the Index ID in the sidebar.")
                st.stop()

        with st.status("Running compliance analysis…", expanded=True) as status_box:
            try:
                if upload_mode == "Existing video ID":
                    # Skip all upload/indexing — jump straight to analysis
                    video_id  = existing_video_id.strip()
                    index_id  = cfg["index_id_input"].strip()
                    st.write(f"✅ Using existing video `{video_id}` in index `{index_id}`")
                    st.write("Fetching video playback URL…")
                    vmeta = get_video_meta(cfg["api_key"], index_id, video_id)
                    playback_url = vmeta["url"]
                    st.session_state["video_is_vertical"] = vmeta["is_vertical"]
                    if playback_url:
                        st.write("✅ Playback URL retrieved")
                    else:
                        st.write("ℹ️ No HLS stream available — player will be hidden")
                else:
                    # Step 1 — Index
                    if not cfg["create_new"] and cfg["index_id_input"]:
                        index_id = cfg["index_id_input"]
                        st.write(f"Using existing index `{index_id}`")
                    else:
                        st.write(f"Creating index `{cfg['index_name']}`…")
                        index_id = create_index(cfg["api_key"], cfg["index_name"])
                        st.write(f"✅ Index created: `{index_id}`")
                        st.session_state["index_id"] = index_id

                    # Step 2 — Upload
                    st.write("Uploading video for indexing…")
                    if upload_mode == "Public URL":
                        task_id = upload_video_url(cfg["api_key"], index_id, video_url)
                        playback_url = video_url
                    else:
                        file_bytes = uploaded_file.read()
                        task_id = upload_video_file(
                            cfg["api_key"], index_id, file_bytes, uploaded_file.name
                        )
                        st.session_state["video_bytes"] = file_bytes
                        st.session_state["video_name"]  = uploaded_file.name
                        playback_url = None
                    st.write(f"✅ Upload task: `{task_id}`")

                    # Step 3 — Poll until indexed
                    st.write("Indexing video (typically ~10–20s for a short ad)…")
                    video_id = poll_task(cfg["api_key"], task_id)
                    st.write(f"✅ Indexed: `{video_id}`")
                    # Try to get HLS URL as a better playback source than raw URL
                    vmeta = get_video_meta(cfg["api_key"], index_id, video_id)
                    st.session_state["video_is_vertical"] = vmeta["is_vertical"]
                    if vmeta["url"]:
                        playback_url = vmeta["url"]

                # Step 4 — Analyze (Pegasus)
                st.write("Running Pegasus compliance analysis…")
                result = run_compliance_check(
                    cfg["api_key"], video_id,
                    cfg["brand"], cfg["product"], cfg["brief"],
                )

                # Step 5 — Evidence (Marengo)
                st.write("Fetching timestamped evidence via Marengo search…")
                clips = fetch_timestamped_evidence(
                    cfg["api_key"], index_id, video_id, result
                )

                status_box.update(label="✅ Analysis complete", state="complete")

                st.session_state["result"]       = result
                st.session_state["clips"]        = clips
                st.session_state["video_url"]    = playback_url   # URL or None for file uploads
                st.session_state["index_id"]     = index_id
                st.session_state["video_id"]     = video_id

            except Exception as e:
                status_box.update(label="❌ Error", state="error")
                st.exception(e)
                st.stop()

    # ── Show index/video IDs for easy reuse
    if "index_id" in st.session_state:
        with st.sidebar:
            st.divider()
            st.markdown("#### Last run")
            st.code(st.session_state["index_id"], language=None)
            if "video_id" in st.session_state:
                st.caption(f"video_id: `{st.session_state['video_id']}`")

    # ── Render results
    if "result" in st.session_state:
        render_results(
            st.session_state["result"],
            st.session_state["clips"],
            st.session_state["video_url"],
        )


if __name__ == "__main__":
    main()