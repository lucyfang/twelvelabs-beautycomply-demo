"""
app.py — BeautyComply: Ad Compliance & Brand Safety
TwelveLabs Solutions Engineer Demo · February 2026

Run:
    pip install streamlit requests
    streamlit run app.py
"""

import json
import time

import requests
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BeautyComply — Compliance Review",
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
  iframe { display:block; margin:0 !important; }
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

# Visual-specific Marengo search queries — used for policies where the violation
# is visually detectable. Queries describe what to SEE, not what was said.
POLICY_SEARCH_QUERIES = {
    "hate_harassment":         "hate speech harassment discriminatory slur derogatory language mocking",
    "profanity_explicit":      "profanity swearing explicit language cursing offensive words",
    "drugs_illegal":           "drug use smoking vaping illegal activity substance paraphernalia",
    "unsafe_product_usage":    "unsafe product application near eye unsanitary technique dirty tools waterline",
    "medical_cosmetic_claims": "before after skin comparison split screen side by side transformation",
}

# For visual policies, use Marengo search to find the exact frame — more accurate
# than Pegasus timestamp_sec which can drift to spoken evidence instead of the visual.
# For audio-dominant policies (hate, profanity), Pegasus timestamp is sufficient.
VISUAL_POLICIES = {"unsafe_product_usage", "medical_cosmetic_claims"}

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
    """Create a new index with both Pegasus (analyze) and Marengo (search).

    Field names per v1.3 docs:
      index_name  (not "name")
      model_name  (not "name")
      model_options (not "options")
    """
    payload = {
        "index_name": name,
        "models": [
            {"model_name": "pegasus1.2", "model_options": ["visual", "audio"]},
            {"model_name": "marengo3.0", "model_options": ["visual", "audio"]},
        ],
        "addons": ["thumbnail"],  # enables thumbnail_urls in HLS metadata
    }
    r = requests.post(f"{BASE_URL}/indexes", headers=auth_headers(api_key), json=payload)
    if not r.ok:
        try:
            detail = r.json()
        except Exception:
            detail = r.text[:400]
        raise RuntimeError(
            f"create_index failed ({r.status_code}): {detail}\n\n"
            f"Common causes:\n"
            f"  • Index name already exists — try a different name in the sidebar\n"
            f"  • Invalid API key\n"
            f"  • model name/options rejected — check TwelveLabs dashboard for available models"
        )
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


def get_video_meta(api_key: str, index_id: str, video_id: str) -> dict:
    """
    Fetch video metadata from GET /indexes/{index_id}/videos/{video_id}.
    Returns dict with keys:
      url           (str|None)  — HLS playback URL
      is_vertical   (bool)      — True if content is portrait orientation
      thumbnail_url (str|None)  — first thumbnail for preview

    Vertical detection: container height > width only.
    Pillarbox detection was removed — it caused false positives that rendered
    horizontal videos in portrait mode with black bars.
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

    is_vertical = h > w
    return {"url": url, "is_vertical": is_vertical, "thumbnail_url": thumb_url}


def analyze_video(api_key: str, video_id: str, prompt: str) -> str:
    """
    Call TwelveLabs Analyze API (Pegasus). Returns concatenated text output.
    Note: renamed from /generate to /analyze in API v1.3 (June 4, 2025).
    Response is always NDJSON streaming — use parse_stream(), never r.json().
    """
    # TwelveLabs hard limit is 8,000 chars. Base policy prompt is ~5,628 chars,
    # leaving ~2,372 chars for brand + product + brief combined.
    # Guard fires 200 chars before the limit so the API never sees an oversized prompt.
    MAX_PROMPT_CHARS = 8000
    BASE_PROMPT_CHARS = 5638   # length of prompt with empty brand/product/brief
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
                 query: str, page_limit: int = 3,
                 threshold: str = "medium",
                 search_options: list[str] | None = None) -> list[dict]:
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

    search_options defaults to ["visual", "transcription"]. Pass ["transcription"]
    to search spoken words only (for audio policy evidence quotes).
    """
    if search_options is None:
        search_options = ["visual", "transcription"]
    multipart = [
        ("index_id",   (None, index_id)),
        ("query_text", (None, query)),
        ("threshold",  (None, threshold)),
        ("page_limit", (None, str(page_limit))),
        ("filter",     (None, json.dumps({"id": [video_id]}))),
    ]
    for opt in search_options:
        multipart.append(("search_options", (None, opt)))
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
You are a strict compliance reviewer for beauty/cosmetics creator ads.
Apply strict liability — default to FLAG. Only visible or audible evidence counts; world knowledge is not a defence.

CAMPAIGN CONTEXT
Brand:   {brand}
Product: {product}
Brief:   {brief}

POLICIES

P1 HATE/HARASSMENT
FAIL: slurs or dehumanizing language (race, gender, sexuality, disability, nationality); hate symbols; fat-shaming; colorism framing lighter skin as improvement.
WARN: edgy humor interpretable as demeaning; skin-tone superiority; self-directed body negativity (e.g. "my skin is disgusting").
PASS: inclusive or neutral language.

P2 PROFANITY
FAIL: strong profanity (f/s/c-word, any language/code-switching); slurs; explicit sexual language.
WARN: mild profanity ("damn","hell","ass","crap","bitch"); bleeped profanity; suggestive language.
PASS: clean language throughout.

P3 DRUGS/ILLEGAL
FAIL: drug use depicted/glorified; paraphernalia visible; smoking or vaping shown; illegal activity; creator visibly intoxicated.
WARN: alcohol prominently on camera; prescription skincare (tretinoin, Accutane) framed as part of routine; casual past-use references.
PASS: no substances or illegal activity.

P4 UNSAFE PRODUCT USAGE
WATERLINE: Flag ONLY if actively applying eyeliner/kajal/kohl/gel liner to inner eyelid on screen, OR verbally recommends it (unless "ophthalmologist tested"). Mascara on lashes = PASS. Creator wearing eyeliner on waterline without applying/recommending = PASS. Foundation/concealer/blush/serum/primer cannot reach waterline — never flag.
VERBAL EVIDENCE: if spoken, must start with Said: + exact quote. Never describe a verbal recommendation as physical application.
FAIL: active waterline application on screen; verbal waterline recommendation; product on broken skin; ingested/inhaled; dangerous combos (high-AHA+retinol, undiluted essential oils); double-dipping; dirty tools; tester on face.
WARN: sloppy technique; unclean tools; inadvisable combo without caveat.
PASS: mascara on lashes; eyeliner worn but not applied/recommended; eyeshadow on lid.

P5 MEDICAL/COSMETIC CLAIMS
SILENT VISUAL CLAIMS: Before/after = drug claim only if underlying skin improved (acne cleared, pores/texture/tone/wrinkles changed). Before/after showing cosmetic product effect (foundation coverage, lip colour, blush) = PASS — that is product demo.
THIRD-PARTY CLAIMS: "My dermatologist said X" = unsubstantiated authority claim even when quoted.
FTC DISCLOSURE: Must be spoken or large on-screen text at video START.
FAIL: treats/cures/heals claims; structural claims (collagen, pores, wrinkles); "clinically proven/dermatologist approved/#1" without source; third-party authority; before/after skin improvement; FTC disclosure absent or late.
WARN: "helps repair skin"; "clinically tested" no outcome; before/after no lighting disclaimer; disclosure after 30s.
PASS: appearance-only ("looks smoother","feels hydrated"); FTC at start.

CAMPAIGN RELEVANCE
Evaluate against Brand, Product, and Brief above.
HARD RULE: different product = off_brief, score 0. No exceptions — no category overlap, no partial credit.
HARD RULE: non-beauty/cosmetics video = off_brief, score 0.
FAIL (off_brief): different product or non-beauty. Score 0–39.
WARN (borderline): correct product present but not focus; 20–50% screen time. Score 40–64.
PASS (on_brief): correct product >50%; named/demoed; tone fits brief. Score 65–100.

EVIDENCE RULE: Spoken violation → Said: "exact words". Visual violation → static observation ("Eyeliner visibly on waterline" not "Applies eyeliner"). Never describe a spoken violation as physical, or vice versa.

TIMESTAMP RULE: timestamp_sec = exact second the violation occurs or is spoken. Not nearby. E.g. before/after shown at 0:31 → 31. "disgusting" spoken at 0:06 → 6.

OUTPUT — valid JSON only, no markdown. Keep string values concise (under 20 words each).
{{
  "description": "<2-5 sentences: observable setting, actions, verbatim quotes — do not infer from brief>",
  "verdict": "<APPROVE|REVIEW|BLOCK>",
  "verdict_reasoning": "<1-2 sentences>",
  "campaign_relevance": {{"status":"<on_brief|borderline|off_brief>","score":<0-100>,"reasoning":"<one sentence>"}},
  "policies": {{
    "hate_harassment":         {{"status":"<pass|warn|fail>","confidence":"<high|medium|low>","violations":[{{"timestamp_sec":<int|null>,"evidence":"<verbatim quote or visual description>"}}],"reasoning":"<one sentence>"}},
    "profanity_explicit":      {{"status":"<pass|warn|fail>","confidence":"<high|medium|low>","violations":[{{"timestamp_sec":<int|null>,"evidence":"<verbatim quote or visual description>"}}],"reasoning":"<one sentence>"}},
    "drugs_illegal":           {{"status":"<pass|warn|fail>","confidence":"<high|medium|low>","violations":[{{"timestamp_sec":<int|null>,"evidence":"<verbatim quote or visual description>"}}],"reasoning":"<one sentence>"}},
    "unsafe_product_usage":    {{"status":"<pass|warn|fail>","confidence":"<high|medium|low>","violations":[{{"timestamp_sec":<int|null>,"evidence":"<verbatim quote or visual description>"}}],"reasoning":"<one sentence>"}},
    "medical_cosmetic_claims": {{"status":"<pass|warn|fail>","confidence":"<high|medium|low>","violations":[{{"timestamp_sec":<int|null>,"evidence":"<verbatim quote or visual description>"}}],"reasoning":"<one sentence>"}}
  }}
}}

List ALL distinct violations in the violations array — one entry per moment. If pass, use violations:[].
CONFIDENCE: high=unambiguous; medium=some ambiguity; low=uncertain(triggers REVIEW).
VERDICT: BLOCK=any fail or off_brief; REVIEW=any warn/borderline/low-confidence; APPROVE=all pass+on_brief+medium+.
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
        return enforce_campaign_relevance(json.loads(cleaned), product)
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
        return enforce_campaign_relevance(json.loads(fixed), product)
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse failed: {e}", "raw": raw}



# ── Campaign relevance enforcement ───────────────────────────────────────────

_CR_STOP_WORDS = {
    "collection", "line", "series", "new", "the", "and", "by",
    "for", "with", "ultra", "super", "pro", "plus", "edition",
}

# Mutually exclusive cosmetic product categories. If the brief specifies a product
# in one group and the video description features a product in another, it's a mismatch.
PRODUCT_TYPE_GROUPS = [
    {"foundation", "concealer", "coverage", "base makeup"},
    {"serum", "essence", "ampoule", "booster"},
    {"moisturizer", "moisturiser", "cream", "lotion", "balm"},
    {"lipstick", "lip gloss", "lip liner", "lip stain", "lip"},
    {"mascara", "eyeliner", "eyeshadow", "eye shadow", "eyebrow"},
    {"blush", "bronzer", "contour", "highlighter", "setting powder"},
    {"cleanser", "toner", "exfoliant", "scrub", "face wash"},
    {"sunscreen", "spf", "sunblock"},
    {"primer", "setting spray", "fixer"},
]


def _extract_product_keywords(product: str) -> set[str]:
    """Meaningful keywords from a product name — strips generic stop words.
    "Radiance Serum Collection" → {"radiance", "serum"}
    """
    return {w for w in product.lower().split() if w not in _CR_STOP_WORDS and len(w) > 2}


def _find_product_group(keywords: set[str]) -> int | None:
    """Return PRODUCT_TYPE_GROUPS index matching keywords, or None."""
    for i, group in enumerate(PRODUCT_TYPE_GROUPS):
        if any(k in keywords or any(k in kw for kw in keywords) for k in group):
            return i
    return None


def enforce_campaign_relevance(result: dict, product: str) -> dict:
    """
    Post-processing guard for the campaign relevance HARD RULE.

    Pegasus repeatedly scores product-mismatched videos on_brief — sometimes
    hedging ("despite wrong product") but often just confidently wrong with no
    signal words at all. Pure reasoning-string matching is insufficient.

    Three layers (applied in order):
      Layer 1 — Reasoning signals: catches "despite the mismatch" style responses.
      Layer 2 — Description cross-check: brief product type vs. what the video
                description actually mentions. E.g. "Radiance Serum" brief +
                "foundation bottle" in description → force off_brief.
      Layer 3 — Score band ceilings: borderline ≤ 64, on_brief ≥ 65.
    """
    relevance = result.get("campaign_relevance", {})
    if not relevance:
        return result

    status      = relevance.get("status", "")
    score       = relevance.get("score", 0)
    reasoning   = (relevance.get("reasoning", "") or "").lower()
    description = (result.get("description", "") or "").lower()

    # Already correctly flagged — nothing to do
    if status == "off_brief":
        return result

    def _force_off_brief(reason: str):
        result["campaign_relevance"]["status"]    = "off_brief"
        result["campaign_relevance"]["score"]     = 0
        result["campaign_relevance"]["reasoning"] = reason
        if result.get("verdict") != "BLOCK":
            result["verdict"] = "BLOCK"
            result["verdict_reasoning"] = (
                "Campaign relevance: off brief — " + reason.rstrip(".")
                + ". " + (result.get("verdict_reasoning") or "")
            ).strip()

    # ── Layer 1: reasoning signal words ────────────────────────────────────────
    RATIONALIZATION_SIGNALS = {
        "despite", "although", "even though", "however", "nevertheless",
        "notwithstanding", "regardless", "while it", "though it",
    }
    MISMATCH_SIGNALS = {
        "mismatch", "different product", "wrong product", "not the product",
        "does not feature", "doesn't feature", "not about", "primarily about",
        "incorrect product", "unrelated product",
    }
    has_rationalization = any(s in reasoning for s in RATIONALIZATION_SIGNALS)
    has_mismatch        = any(s in reasoning for s in MISMATCH_SIGNALS)

    if has_mismatch and has_rationalization:
        _force_off_brief("Mismatch + rationalization detected in model reasoning.")
        return result

    # ── Layer 2: description-based product type cross-check ────────────────────
    brief_keywords   = _extract_product_keywords(product)
    brief_group      = _find_product_group(brief_keywords)

    if brief_group is not None:
        for i, group in enumerate(PRODUCT_TYPE_GROUPS):
            if i == brief_group:
                continue
            conflicting_terms = [term for term in group if term in description]
            brief_terms_in_desc = [kw for kw in brief_keywords if kw in description]
            if conflicting_terms and not brief_terms_in_desc:
                _force_off_brief(
                    f"The video features a {conflicting_terms[0]} product, "
                    f"not the {product} specified in the brief."
                )
                return result

    # ── Layer 3: score band ceilings ───────────────────────────────────────────
    if status == "borderline" and score > 64:
        result["campaign_relevance"]["score"] = 64
    if status == "on_brief" and score < 65:
        result["campaign_relevance"]["score"] = 65

    return result



def fetch_timestamped_evidence(api_key: str, index_id: str, video_id: str,
                                result: dict) -> dict[str, list[dict]]:
    """
    Returns {policy_key: [{"evidence": str, "clip": {"start": int, "end": int} | None}]}
    One entry per violation, evidence and its resolved clip kept together.
    """
    by_policy   = {}
    policies    = result.get("policies", {})
    CLIP_WINDOW = 10
    SKIP        = {"none detected", "none", "n/a", ""}

    def marengo_clip(query: str) -> dict | None:
        try:
            hits = search_clips(
                api_key, index_id, video_id, query,
                page_limit=1, threshold="medium",
                search_options=["visual", "transcription"],
            )
            for c in hits:
                if c.get("start_time") is not None or c.get("start") is not None:
                    return {
                        "start": int(c.get("start_time", c.get("start", 0))),
                        "end":   int(c.get("end_time",   c.get("end",   0))),
                    }
        except Exception:
            pass
        return None

    for key in POLICY_CATEGORIES:
        policy = policies.get(key, {})
        if policy.get("status") not in ("warn", "fail"):
            continue

        violations = policy.get("violations") or []
        if not violations:
            ev = (policy.get("evidence") or "").strip()
            ts = policy.get("timestamp_sec")
            violations = [{"evidence": ev, "timestamp_sec": ts}]

        paired = []
        for v in violations:
            evidence = (v.get("evidence") or "").strip()
            clip = None
            if evidence.lower() not in SKIP:
                clip = marengo_clip(evidence)
            if clip is None:
                ts = v.get("timestamp_sec")
                if ts is not None:
                    try:
                        t = int(ts)
                        clip = {"start": t, "end": t + CLIP_WINDOW}
                    except (TypeError, ValueError):
                        pass
            paired.append({"evidence": evidence, "clip": clip})

        by_policy[key] = paired

    return by_policy

# ── UI helpers ────────────────────────────────────────────────────────────────

def fmt_time(s: float) -> str:
    m, sec = divmod(int(s), 60)
    return f"{m}:{sec:02d}"


def render_verdict_badge(verdict: str):
    st.markdown(
        f'<span class="verdict-badge verdict-{verdict}">{verdict}</span>',
        unsafe_allow_html=True,
    )


def render_policy_row(key: str, policy: dict, paired: list[dict]):
    """
    paired: [{"evidence": str, "clip": {"start": int, "end": int} | None}]
    """
    label      = POLICY_LABELS.get(key, key)
    status     = policy.get("status", "pass")
    confidence = policy.get("confidence", "high")
    reasoning  = (policy.get("reasoning", "") or "")
    for marker in ("Original reasoning:", "Original score:"):
        idx = reasoning.find(marker)
        if idx != -1:
            reasoning = reasoning[:idx].rstrip(". ")
    icon      = STATUS_ICON.get(status, "")
    conf_icon = CONF_ICON.get(confidence, "")

    # Normalise: if caller passed old flat clip list, wrap it
    if paired and isinstance(paired[0], dict) and "start" in paired[0]:
        paired = [{"evidence": policy.get("evidence", ""), "clip": c} for c in paired]

    # Also pull violations from policy if paired is empty (pass case)
    if not paired:
        violations = policy.get("violations") or []
        paired = [{"evidence": v.get("evidence", ""), "clip": None} for v in violations]

    with st.expander(f"{icon} **{label}** — `{status.upper()}`  {conf_icon} confidence: `{confidence}`", expanded=status in ("warn", "fail")):
        col_left, col_right = st.columns([1, 2])

        with col_left:
            css = {"pass": "policy-pass", "warn": "policy-warn", "fail": "policy-fail"}.get(status, "")
            st.markdown(f"**Status:** <span class='{css}'>{status.upper()}</span>", unsafe_allow_html=True)
            st.markdown(f"**Confidence:** <span class='conf-{confidence}'>{confidence}</span>", unsafe_allow_html=True)

        with col_right:
            shown_any = False
            for p in paired:
                ev_text = (p.get("evidence") or "").replace("[AUTO] ", "").strip()
                if not ev_text or ev_text.lower() in ("none detected", "none", "n/a", ""):
                    continue
                clip    = p.get("clip")
                clip_ts = clip["start"] if clip else None
                ts_badge = f' <span class="timestamp-chip">⏱ {fmt_time(clip_ts)}</span>' if clip_ts is not None else ""
                st.markdown(
                    f'<div class="evidence-block">📌 <strong>Evidence:</strong>{ts_badge} {ev_text}</div>',
                    unsafe_allow_html=True,
                )
                shown_any = True
            if not shown_any and status == "pass":
                st.markdown('<div class="evidence-block">✅ No violations detected</div>', unsafe_allow_html=True)
            if reasoning:
                st.markdown(f'<div class="reasoning-block">💬 {reasoning}</div>', unsafe_allow_html=True)

        clips_with_ts = [p["clip"] for p in paired if p.get("clip") and p["clip"].get("start") is not None]
        if clips_with_ts:
            starts = [fmt_time(int(c["start"])) + "–" + fmt_time(int(c.get("end", c["start"]))) for c in clips_with_ts]
            chips  = "  ".join(f'<span class="timestamp-chip">⏱ {s}</span>' for s in starts)
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
    relevance = result.get("campaign_relevance", {})
    policies  = result.get("policies", {})

    def _clean_reasoning(text: str) -> str:
        """Strip [AUTO-OVERRIDE] prefix and 'Original ...' trailer from displayed text."""
        if not text:
            return text
        text = text.replace("[AUTO-OVERRIDE] ", "").replace("[AUTO] ", "")
        # Trim anything from "Original score:" or "Original reasoning:" onward
        for marker in ("Original score:", "Original reasoning:"):
            idx = text.find(marker)
            if idx != -1:
                text = text[:idx].rstrip(". ")
        return text.strip()


    # Derive verdict reasoning from actual data — Pegasus text is often imprecise
    def _derive_verdict_reasoning(verdict: str, relevance: dict, policies: dict) -> str:
        rel_status = relevance.get("status", "on_brief")
        fails  = [POLICY_LABELS[k].split(" / ")[0] for k in POLICY_CATEGORIES if policies.get(k, {}).get("status") == "fail"]
        warns  = [POLICY_LABELS[k].split(" / ")[0] for k in POLICY_CATEGORIES if policies.get(k, {}).get("status") == "warn"]
        parts  = []
        if rel_status == "off_brief":
            parts.append("Video is off-brief")
        elif rel_status == "borderline":
            parts.append("Video is borderline on-brief")
        if fails:
            parts.append(f"Policy failures: {', '.join(fails)}")
        if warns:
            parts.append(f"Policy warnings: {', '.join(warns)}")
        if not parts:
            return "All policies pass and video is on-brief." if verdict == "APPROVE" else ""
        return ". ".join(parts) + "."

    # ── Verdict + Campaign Relevance
    col_v, col_r = st.columns([1, 2])
    with col_v:
        st.markdown("### Verdict")
        render_verdict_badge(verdict)
        derived_reasoning = _derive_verdict_reasoning(verdict, relevance, policies)
        if derived_reasoning:
            st.caption(derived_reasoning)

    with col_r:
        st.markdown("### Campaign Relevance")
        rel_status = relevance.get("status", "unknown")
        rel_score  = relevance.get("score", 0)
        rel_reason = _clean_reasoning(relevance.get("reasoning", ""))
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

    # Collect timestamps from Pegasus timestamp_sec fields.
    # Clips are built directly from Pegasus — no Marengo search — so timestamps
    # reflect exactly where Pegasus observed the violation, not a semantic approximation.
    ts_set = set()
    all_clips_flat = []
    for pol_key, paired_list in clips.items():
        for p in paired_list:
            clip = p.get("clip")
            if clip and clip.get("start") is not None:
                ev = p.get("evidence", "")
                ts_set.add(int(clip["start"]))
                all_clips_flat.append((POLICY_LABELS.get(pol_key, pol_key), int(clip["start"]), int(clip.get("end", clip["start"])), ev))
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

    vid_col, clips_col = st.columns([3, 2])

    with vid_col:
        if video_source is None:
            st.warning("No video source available for playback.")
        else:
            seek_to = st.session_state.get("seek_to", 0)
            is_hls = isinstance(video_source, str) and video_source.endswith(".m3u8")
            if is_hls:
                is_vertical = st.session_state.get("video_is_vertical", False)
                height = 560 if is_vertical else 360
                hls_html = f"""<!DOCTYPE html><!-- v={st.session_state.get("seek_version", 0)} --><html><body style="margin:0">
<video id="v" controls style="width:100%;height:{height}px;display:block" playsinline></video>
<script src="https://cdn.jsdelivr.net/npm/hls.js@1.4.12/dist/hls.min.js"></script>
<script>
  var src="{video_source}", t={seek_to};
  var v=document.getElementById("v");
  function nativeLoad(){{v.src=src;v.addEventListener("loadedmetadata",function(){{v.currentTime=t;}});}}
  if(Hls.isSupported()){{
    var h=new Hls();
    h.loadSource(src);
    h.attachMedia(v);
    h.on(Hls.Events.MANIFEST_PARSED,function(){{v.currentTime=t;}});
    h.on(Hls.Events.ERROR,function(e,d){{if(d.fatal){{h.destroy();nativeLoad();}}}});
    setTimeout(function(){{if(v.readyState===0){{h.destroy();nativeLoad();}}}},5000);
  }}else{{nativeLoad();}}
</script></body></html>"""
                st.components.v1.html(hls_html, height=height + 4, scrolling=False)
            elif seek_to:
                st.video(video_source, start_time=seek_to)
            else:
                st.video(video_source)

    with clips_col:
        if all_clips_flat:
            st.markdown("**Jump to flagged clip:**")
            # Deduplicate by start time, preserve labels
            seen = {}
            for label, start, end, evidence in all_clips_flat:
                if start not in seen:
                    seen[start] = (label, end, evidence)
            for start in sorted(seen):
                label, end, evidence = seen[start]
                short_label = label.split(" / ")[0]
                st.markdown('<div class="clip-btn">', unsafe_allow_html=True)
                if st.button(
                    f"⏱ {fmt_time(start)}–{fmt_time(end)}  {short_label}",
                    key=f"sideclip_{start}",
                    use_container_width=True,
                ):
                    st.session_state["seek_to"] = start
                    st.session_state["seek_version"] = st.session_state.get("seek_version", 0) + 1
                    st.rerun()
                if evidence and evidence.lower() not in ("none detected", "none", "n/a", ""):
                    st.caption(evidence[:120] + ("…" if len(evidence) > 120 else ""))
                st.markdown('</div>', unsafe_allow_html=True)
        elif all_timestamps:
            st.markdown("**Jump to flagged moment:**")
            for ts in all_timestamps:
                st.markdown('<div class="clip-btn">', unsafe_allow_html=True)
                if st.button(fmt_time(ts), key=f"sidets_{ts}", use_container_width=True):
                    st.session_state["seek_to"] = ts
                    st.session_state["seek_version"] = st.session_state.get("seek_version", 0) + 1
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

    # Verdict consistency check — warn if verdict implies violations but all policies show pass
    policy_statuses = [policies.get(k, {}).get("status", "pass") for k in POLICY_CATEGORIES]
    rel_status = result.get("campaign_relevance", {}).get("status", "on_brief")
    has_flagged_policy = any(s in ("warn", "fail") for s in policy_statuses)
    if verdict in ("BLOCK", "REVIEW") and not has_flagged_policy and rel_status == "on_brief":
        st.warning(
            "⚠️ Verdict mismatch: the overall verdict is " + verdict +
            " but no individual policy violations were returned. "
            "This usually means Pegasus truncated its output — check Raw JSON below.",
            icon=None,
        )

    st.divider()


    # Raw JSON — auto-expanded on verdict mismatch
    mismatch = verdict in ("BLOCK", "REVIEW") and not has_flagged_policy and rel_status == "on_brief"
    with st.expander("🔩 Raw JSON output", expanded=mismatch):
        st.json({"compliance_result": result, "timestamped_clips": clips})


# ── Sidebar ───────────────────────────────────────────────────────────────────

def sidebar() -> dict:
    with st.sidebar:
        st.markdown("# 🐎 BeautyComply")
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
            index_name = st.text_input("New index name", value="beautycomply-demo")

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

def _render_deck():
    """Embed the Gamma pitch deck."""
    st.markdown(
        """
        <style>
        .deck-wrap {
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 4px 32px rgba(0,0,0,0.45);
            margin: 12px 0 0 0;
        }
        </style>
        <div class="deck-wrap">
        """,
        unsafe_allow_html=True,
    )
    st.components.v1.iframe(
        "https://gamma.app/embed/dwzhtgki7g22uc6",
        height=640,
        scrolling=False,
    )
    st.markdown("</div>", unsafe_allow_html=True)



def main():
    cfg = sidebar()

    tab_review, tab_deck = st.tabs(["📋  Ad Review", "📊  Pitch Deck"])

    with tab_deck:
        _render_deck()

    with tab_review:
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

                    # Step 5 — Timestamps (from Pegasus result)
                    st.write("Extracting violation timestamps from Pegasus analysis…")
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