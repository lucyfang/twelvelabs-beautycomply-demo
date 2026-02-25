"""
test_twelvelabs.py
------------------
Validates all TwelveLabs API calls in sequence before Streamlit integration.

Usage:
    python test_twelvelabs.py

Set your API key and video URL at the top of the file, or via environment variables:
    export TWELVELABS_API_KEY=your_key
    export TEST_VIDEO_URL=https://...
"""

import os
import sys
import json
import time
import requests

# ── Config — edit these or set as env vars ────────────────────────────────────
API_KEY   = os.environ.get("TWELVELABS_API_KEY", "YOUR_API_KEY_HERE")
VIDEO_URL = os.environ.get("TEST_VIDEO_URL",
    # A short, publicly accessible MP4 — swap for a real beauty/creator video
    "https://storage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4"
)

BASE_URL     = "https://api.twelvelabs.io/v1.3"
INDEX_NAME   = "adsafe-test-v2"  # bumped to force new index with both pegasus1.2 + marengo3.0
POLL_TIMEOUT = 300  # seconds


# ── Helpers ───────────────────────────────────────────────────────────────────

def headers():
    return {"x-api-key": API_KEY, "Content-Type": "application/json"}


def ok(label: str):
    print(f"  ✅  {label}")


def fail(label: str, detail: str = ""):
    print(f"  ❌  {label}")
    if detail:
        print(f"      {detail}")
    sys.exit(1)


def section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def parse_twelvelabs_stream(response_text: str) -> str:
    """
    TwelveLabs /analyze always responds with NDJSON streaming, even for
    synchronous calls. The response is a sequence of newline-delimited JSON
    objects, each with an "event_type" field:

        {"event_type": "stream_start", "metadata": {...}}
        {"event_type": "text_generation", "text": "{\n  \"description\":"}
        {"event_type": "text_generation", "text": " \"The video shows..."}
        ...
        {"event_type": "stream_end", "usage": {...}}

    We must concatenate ALL "text_generation" chunks in order to reconstruct
    the full model output. Using r.json() or dict.update() only keeps the
    last chunk's "text" value — the bug that caused the earlier failure.
    """
    chunks = []
    for line in response_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # skip malformed lines
        if event.get("event_type") == "text_generation":
            chunks.append(event.get("text", ""))
    return "".join(chunks)


# ── Step 0: Auth check ────────────────────────────────────────────────────────

def test_auth():
    section("STEP 0 — Auth check")
    if API_KEY == "YOUR_API_KEY_HERE":
        fail("API key not set", "Edit API_KEY at the top of the file or set TWELVELABS_API_KEY env var.")

    r = requests.get(f"{BASE_URL}/indexes", headers=headers())
    if r.status_code == 401:
        fail("Auth failed", f"HTTP 401 — check your API key.\n      Response: {r.text}")
    elif r.status_code != 200:
        fail(f"Unexpected status {r.status_code}", r.text[:300])

    indexes = r.json().get("data", [])
    ok(f"Authenticated. Found {len(indexes)} existing index(es).")
    for idx in indexes:
        print(f"       - {idx['_id']}  ({idx.get('name', 'unnamed')})")
    return indexes


# ── Step 1: Create index ──────────────────────────────────────────────────────

def test_create_index(existing_indexes: list) -> str:
    section("STEP 1 — Create (or reuse) index")

    for idx in existing_indexes:
        if idx.get("name") == INDEX_NAME:
            index_id = idx["_id"]
            ok(f"Reusing existing index '{INDEX_NAME}': {index_id}")
            return index_id

    payload = {
        "name": INDEX_NAME,
        # Pegasus 1.2 powers the Analyze API (compliance reasoning)
        # Marengo 3.0 powers the Search API (timestamped evidence retrieval)
        "models": [
            {"name": "pegasus1.2", "options": ["visual", "audio"]},
            {"name": "marengo3.0", "options": ["visual", "audio"]},
        ],
    }
    r = requests.post(f"{BASE_URL}/indexes", headers=headers(), json=payload)

    if r.status_code not in (200, 201):
        fail(f"Create index failed (HTTP {r.status_code})", r.text[:400])

    data = r.json()
    index_id = data.get("_id") or data.get("id")
    if not index_id:
        fail("Create index returned no ID", f"Full response: {json.dumps(data, indent=2)}")

    ok(f"Index created: {index_id}")
    return index_id


# ── Step 2: Upload video ──────────────────────────────────────────────────────

def test_upload_video(index_id: str) -> str:
    section("STEP 2 — Upload video by URL")
    print(f"  URL: {VIDEO_URL}")

    # Tasks endpoint requires multipart/form-data, not JSON
    r = requests.post(
        f"{BASE_URL}/tasks",
        headers={"x-api-key": API_KEY},  # let requests set Content-Type with boundary
        data={"index_id": index_id, "url": VIDEO_URL, "language": "en"},
    )

    if r.status_code not in (200, 201):
        fail(f"Upload failed (HTTP {r.status_code})", r.text[:400])

    data = r.json()
    task_id = data.get("_id") or data.get("id")
    if not task_id:
        fail("Upload returned no task ID", f"Full response: {json.dumps(data, indent=2)}")

    ok(f"Upload task created: {task_id}")
    return task_id


# ── Step 3: Poll until indexed ────────────────────────────────────────────────

def test_poll_task(task_id: str) -> str:
    section("STEP 3 — Poll indexing task until ready")
    print(f"  Task ID: {task_id}")
    print(f"  Polling every 5s (timeout: {POLL_TIMEOUT}s)...")

    start = time.time()
    last_status = None

    while time.time() - start < POLL_TIMEOUT:
        r = requests.get(f"{BASE_URL}/tasks/{task_id}", headers=headers())
        if r.status_code != 200:
            fail(f"Poll failed (HTTP {r.status_code})", r.text[:300])

        data = r.json()
        status = data.get("status")

        if status != last_status:
            print(f"  [{int(time.time() - start):>3}s]  status = {status}")
            last_status = status

        if status == "ready":
            video_id = data.get("video_id")
            if not video_id:
                fail("Task ready but no video_id in response", json.dumps(data, indent=2))
            ok(f"Indexed! video_id = {video_id}")
            return video_id

        if status in ("failed", "error"):
            fail(f"Indexing failed with status '{status}'", json.dumps(data, indent=2))

        time.sleep(5)

    fail(f"Timed out after {POLL_TIMEOUT}s — task never reached 'ready'")


# ── Step 4: Analyze API (renamed from Generate API on June 4, 2025) ───────────

def test_analyze_simple(video_id: str):
    section("STEP 4a — Analyze API (simple prompt)")

    r = requests.post(
        f"{BASE_URL}/analyze",
        headers=headers(),
        json={"video_id": video_id, "prompt": "Describe this video in one sentence."},
    )

    print(f"  HTTP status: {r.status_code}")
    print(f"  Raw response (first 400 chars):\n  {r.text[:400]}\n")

    if r.status_code == 404:
        fail(
            "404 — endpoint may differ from expected.",
            f"The Generate API was renamed /analyze in v1.3 (June 4, 2025).\n"
            f"      URL tried: {BASE_URL}/analyze\n      Body: {r.text[:300]}"
        )
    elif r.status_code != 200:
        fail(f"Analyze failed (HTTP {r.status_code})", r.text[:400])

    text = parse_twelvelabs_stream(r.text)
    if not text:
        fail("No text_generation chunks found in stream.", f"Full body: {r.text[:400]}")

    ok("Analyze API works — stream parsed successfully.")
    print(f"\n  >>> {text[:300]}\n")
    return text


def test_analyze_json(video_id: str, index_id: str):
    section("STEP 4b — Analyze API (structured JSON compliance prompt)")

    prompt = (
        "You are a compliance reviewer for a social media ad platform.\n"
        "Analyze this video and return ONLY a valid JSON object with this structure "
        "— no markdown fences, no preamble, no trailing text:\n"
        "{\n"
        '  "description": "<2-3 sentence summary of what happens>",\n'
        '  "verdict": "<APPROVE | REVIEW | BLOCK>",\n'
        '  "campaign_relevance": {\n'
        '    "status": "<on_brief | off_brief | borderline>",\n'
        '    "score": <0-100>\n'
        "  },\n"
        '  "policies": {\n'
        '    "hate_harassment":         {"status": "<pass|warn|fail>", "evidence": "<quote or none detected>"},\n'
        '    "profanity_explicit":      {"status": "<pass|warn|fail>", "evidence": "<quote or none detected>"},\n'
        '    "drugs_illegal":           {"status": "<pass|warn|fail>", "evidence": "<quote or none detected>"},\n'
        '    "unsafe_product_usage":    {"status": "<pass|warn|fail>", "evidence": "<quote or none detected>"},\n'
        '    "medical_cosmetic_claims": {"status": "<pass|warn|fail>", "evidence": "<quote or none detected>"}\n'
        "  }\n"
        "}\n"
        "Verdict rule: APPROVE if all policies pass, REVIEW if any warn, BLOCK if any fail.\n"
        "Return only valid JSON."
    )

    r = requests.post(
        f"{BASE_URL}/analyze",
        headers=headers(),
        json={"video_id": video_id, "prompt": prompt},
    )

    if r.status_code != 200:
        fail(f"Analyze (JSON) failed (HTTP {r.status_code})", r.text[:400])

    print(f"\n  Raw HTTP response body (first 600 chars):\n  {r.text[:600]}\n")

    # TwelveLabs /analyze always streams NDJSON — concatenate text_generation chunks
    raw_text = parse_twelvelabs_stream(r.text)
    if not raw_text:
        fail("No text_generation chunks found in stream.", f"Raw body: {r.text[:400]}")

    print(f"  Full concatenated model output:\n  {raw_text[:600]}\n")

    # Strip markdown fences the model occasionally adds despite instructions
    cleaned = raw_text.strip()
    for prefix in ["```json", "```"]:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    cleaned = cleaned.removesuffix("```").strip()

    try:
        parsed = json.loads(cleaned)
        ok("JSON parsed successfully.")
        print(f"  Verdict:     {parsed.get('verdict')}")
        print(f"  Description: {parsed.get('description', '')[:120]}")
        print("  Policies:")
        for k, v in parsed.get("policies", {}).items():
            print(f"    {k:<30} {v.get('status')}")
        return parsed
    except json.JSONDecodeError as e:
        fail(
            "Model output was not valid JSON — may need prompt tuning.",
            f"Parse error: {e}\n      Cleaned text: {cleaned[:400]}"
        )


# ── Step 5: Search API ────────────────────────────────────────────────────────

def test_search(index_id: str, video_id: str):
    section("STEP 5 — Search API (timestamped clip evidence)")

    # Search endpoint requires multipart/form-data (same as /tasks).
    # Nested fields like search_options and filter must be JSON-stringified
    # strings within the form — they cannot be sent as raw nested objects.
    # requests only sends multipart/form-data when files= is used.
    # data= sends application/x-www-form-urlencoded which TwelveLabs rejects.
    # Trick: pass all fields as tuples in files= with no filename/content-type,
    # which forces genuine multipart encoding without actually uploading a file.
    # search_options must be repeated as separate form fields — one per value.
    # Sending a JSON-stringified array as a single field is rejected by the API.
    multipart_fields = [
        ("index_id",      (None, index_id)),
        ("query_text",    (None, "makeup application beauty tutorial")),
        ("search_options", (None, "visual")),
        ("search_options", (None, "transcription")),
        ("threshold",     (None, "medium")),  # low returns clips regardless of relevance; medium enforces a similarity floor
        ("page_limit",    (None, "3")),
        ("filter",        (None, json.dumps({"id": [video_id]}))),
    ]

    r = requests.post(
        f"{BASE_URL}/search",
        headers={"x-api-key": API_KEY},  # no Content-Type — requests sets multipart boundary
        files=multipart_fields,
    )
    print(f"  HTTP status: {r.status_code}")

    if r.status_code != 200:
        fail(f"Search failed (HTTP {r.status_code})", r.text[:400])

    data = r.json()
    clips = data.get("data", [])

    if not clips:
        print("  ⚠️  No clips returned — try a different query or video.")
        print(f"     Full response: {json.dumps(data, indent=2)[:400]}")
        return {}

    ok(f"{len(clips)} clip(s) returned.")
    sample = clips[0]
    print(f"\n  Sample clip keys: {list(sample.keys())}")

    start_key = next((k for k in ["start", "start_time", "clip_start"] if k in sample), None)
    end_key   = next((k for k in ["end",   "end_time",   "clip_end"]   if k in sample), None)

    if not start_key:
        fail(
            "Could not find start timestamp field.",
            f"Keys present: {list(sample.keys())}\n"
            "      Update app.py render_results() to use the correct field name."
        )

    print(f"  Timestamp fields: start='{start_key}', end='{end_key}'\n")

    # v1.3 / Marengo 3.0: score + confidence removed, use rank instead
    for i, clip in enumerate(clips):
        print(f"  Clip {i+1}: {clip.get(start_key, '?')}s – {clip.get(end_key, '?')}s  |  rank: {clip.get('rank', '?')}")

    return {"start_key": start_key, "end_key": end_key}


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(index_id: str, video_id: str, field_map: dict):
    section("SUMMARY — copy these into app.py")
    sk = field_map.get("start_key", "start")
    ek = field_map.get("end_key", "end")
    print(f"""
  index_id   = "{index_id}"
  video_id   = "{video_id}"

  API version:      v1.3
  Analyze endpoint: /analyze  (was /generate — renamed June 4, 2025)
  Stream parsing:   use parse_twelvelabs_stream() — concatenates text_generation chunks
  Search options:   ["visual", "transcription"]  (audio no longer includes speech in v1.3)
  Search ranking:   clip.get("rank")  (score + confidence removed in Marengo 3.0)

  Clip field names to use in app.py:
    start → "{sk}"
    end   → "{ek}"
    score → "rank"
""")


# ── Run all tests ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🛡️  AdSafe — TwelveLabs API Integration Test")
    print("=" * 60)

    existing_indexes = test_auth()
    index_id = test_create_index(existing_indexes)
    task_id  = test_upload_video(index_id)
    video_id = test_poll_task(task_id)

    test_analyze_simple(video_id)
    test_analyze_json(video_id, index_id)
    field_map = test_search(index_id, video_id)

    print_summary(index_id, video_id, field_map or {})

    print("\n✅  All tests passed — ready to integrate with Streamlit.\n")