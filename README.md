# AdSafe — Ad Compliance Demo
### TwelveLabs Solutions Engineer Exercise

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open `http://localhost:8501` in your browser.

---

## What it does

1. **Ingests** a creator video URL via TwelveLabs indexing (Pegasus 1.2 model)
2. **Runs compliance analysis** using the Generate API with a structured JSON prompt
3. **Fetches timestamped evidence** using the Search API for any flagged policies
4. **Renders** a full compliance report with verdict, policy scorecard, video player with timestamp jumping

## Policy categories

| Category | Verdict trigger |
|---|---|
| Hate / Harassment | BLOCK on fail, REVIEW on warn |
| Profanity / Explicit Language | BLOCK on fail, REVIEW on warn |
| Drugs / Illegal Behavior | BLOCK on fail, REVIEW on warn |
| Unsafe / Misleading Product Usage | BLOCK on fail, REVIEW on warn |
| Medical or Cosmetic Claims | BLOCK on fail, REVIEW on warn |
| Campaign Relevance | BLOCK if off_brief, REVIEW if borderline |

## Verdict logic

- **BLOCK** — any policy fails OR video is off-brief
- **REVIEW** — any policy warns OR campaign relevance is borderline
- **APPROVE** — all policies pass AND video is on-brief

## Architecture

```
Video URL
    │
    ▼
TwelveLabs Index (Pegasus 1.2)
    │
    ├─► Generate API  →  Structured compliance JSON
    │                    (description + verdict + policy statuses)
    │
    └─► Search API    →  Timestamped clip evidence
                         (per flagged policy)
    │
    ▼
Streamlit UI  →  Verdict badge + policy scorecard + video player
```

## Scaling notes

In a production ads pipeline this would work as follows:
- Videos are submitted to a job queue (e.g. SQS) when creators request promotion
- A worker pool calls the TwelveLabs indexing API and compliance generate call per video
- Results are stored in a database with the video_id, verdict, and JSON report
- The compliance team reviews REVIEW-queue items in a dashboard (this UI)
- BLOCK decisions are returned to creators with timestamped evidence explaining the rejection
- Index reuse: one shared index per campaign keeps costs low and enables cross-video search
