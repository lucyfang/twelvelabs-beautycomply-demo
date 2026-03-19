# BeautyComply — AI-Powered Ad Compliance Demo
### TwelveLabs Solutions Engineer Exercise

**Presentation:** [https://beautycomply-aai6qmt.gamma.site](https://beautycomply-aai6qmt.gamma.site/)  
**Live demo:** [twelvelabs-beautycomply-demo.streamlit.app](https://twelvelabs-beautycomply-demo.streamlit.app/)

You'll need a [TwelveLabs API key](https://playground.twelvelabs.io/dashboard/api-keys) to run an analysis.

---

## What it does

Evaluates creator beauty/cosmetics videos for brand safety, policy compliance, and campaign relevance before paid promotion — using TwelveLabs Pegasus 1.2 (video analysis) and Marengo 3.0 (semantic search).

1. **Ingests** a creator video by public URL, local file upload, or existing video ID
2. **Analyzes** the video with Pegasus via a structured compliance prompt grounded in GARM, FTC, and FDA standards
3. **Locates evidence** with Marengo semantic search, returning timestamped clips for every flagged policy
4. **Renders** a full compliance report: verdict badge, campaign relevance score, video player with one-click clip seeking, and per-policy scorecard

## Policy categories

| Category | Standard | Trigger |
|---|---|---|
| Hate / Harassment | GARM Cat. 6 | BLOCK on fail, REVIEW on warn |
| Profanity / Explicit | GARM Cat. 3 | BLOCK on fail, REVIEW on warn |
| Drugs / Illegal Behavior | GARM Cat. 4 | BLOCK on fail, REVIEW on warn |
| Unsafe Product Usage | FDA cosmetic safety | BLOCK on fail, REVIEW on warn |
| Medical / Cosmetic Claims | FDA FD&C §201, FTC 16 CFR 255 | BLOCK on fail, REVIEW on warn |
| Campaign Relevance | — | BLOCK if off_brief, REVIEW if borderline |

Full policy definitions and decision logic: [beautycomply_policy_framework.pdf](https://github.com/lucyfang/twelvelabs-adsafe-demo/blob/main/beautycomply_policy_framework.pdf)

## Verdict logic

- **BLOCK** — any policy fails OR video is off-brief
- **REVIEW** — any policy warns OR campaign relevance is borderline OR any confidence is low
- **APPROVE** — all policies pass AND on-brief AND all confidence ≥ medium

## Architecture

```
Video URL / file
      │
      ▼
TwelveLabs Index (Pegasus 1.2 + Marengo 3.0)
      │
      ├─► Analyze API (Pegasus)  →  Structured compliance JSON
      │                              verdict + policy statuses + timestamps
      │
      └─► Search API (Marengo)   →  Timestamped clip evidence
                                     per flagged policy
      │
      ▼
Streamlit UI  →  Verdict badge + scorecard + video player with clip seek
```

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Scaling notes

In a production ads pipeline this would extend as follows:
- Videos submitted to a job queue (e.g. SQS) when creators request promotion
- Worker pool calls TwelveLabs indexing + compliance analysis per video
- Results stored in a database with video_id, verdict, and full JSON report
- Compliance team reviews the REVIEW queue in a dashboard like this one
- BLOCK decisions returned to creators with timestamped evidence explaining the rejection
- One shared index per campaign keeps costs low and enables cross-video search
