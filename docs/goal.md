Use this brief as the single prompt to build the ActivityWatch LLM categorizer sidecar.

# Project

Build a sidecar that ingests ActivityWatch events, enriches, classifies into pre-named buckets via LLM + rules, and writes back to a new AW bucket. Target NixOS.

# Objective

Accurate, auditable categorization across windows and browser tabs into:

* Client Work → {STS Contract, Qualira (AWP), Xodus Medical, Hand Consultants, DTG Engineering, Docs & Spreadsheets, Code & IDE, Comms, Admin & Billing}
* Hobby → {Programming, Machining & CAD, Video-Learning, Comms}
* Entertainment → {Gaming, Video, Social}
* Uncategorized

# Constraints

* Sources: `aw-watcher-window`, `aw-watcher-web-zen`, `aw-watcher-afk`.
* Minimum event duration: 10s.
* LLM only when needed. Temperature 0. JSON only. Confidence gate 0.70.
* Redact PII and volatile strings before LLM. No raw URLs with queries.
* Deterministic fallbacks must exist. Offline should still work.
* NixOS service. No desktop prompts.

# Inputs (examples)

ActivityWatch event (window/web):

```
{
  "timestamp": "ISO8601Z",
  "duration": 23.4,
  "data": {
    "app": "Zen Browser",
    "title": "STS – PPAP Control Plan – Google Docs",
    "url": "https://docs.google.com/document/d/…",
    "appname": "zen"
  }
}
```

# Output bucket

Create `aw-llm-categories_{hostname}`. Event schema:

```
{
  "timestamp": "<from original>",
  "duration": <from original>,
  "data": {
    "category": "Client Work|Hobby|Entertainment|Uncategorized",
    "subcategory": "<one of allowed or null>",
    "client": "<client name or null>",
    "confidence": 0.00-1.00,
    "source": "llm|rule|cache",
    "rationale": "≤140 chars",
    "features": { "app": "...", "title": "...", "domain": "..." }
  }
}
```

# Strong signals (short-circuit to Client Work)

* Exact domain or path prefix match for known clients.
* Repo/workdir prefix match in editor/terminal titles.
* Mail/chat thread containing client key terms near QMS/PPAP/FMEA/SOW/PO/Invoice.
  These bypass LLM and set `confidence=0.98`.

# Config (external, hot-reload)

`config.json` or `config.yaml`:

```
clients:
  STS Contract:
    domains: ["stsdiesel.com","microsoftonline.com"]
    keywords: ["STS","Turbo","QMS","PPAP","FMEA"]
    paths: ["/work/clients/sts"]
  Qualira (AWP): {…}
  Xodus Medical: {…}
  Hand Consultants: {…}
  DTG Engineering: {…}
rules:
  hobby_prog_keywords: ["nix","dotfiles","neovim","kicad","freecad"]
  machining_keywords: ["cnc","lathe","end mill","toolpath","feeds","speeds","cam"]
  edu_keywords: ["tutorial","how to","guide"]
thresholds:
  min_duration_sec: 10
  llm_confidence_min: 0.70
  cache_ttl_days: 7
```

# LLM contract

System prompt:

```
You are a deterministic classifier. Output strict JSON only. No prose. Labels:
Top: ["Client Work","Hobby","Entertainment","Uncategorized"]
Sub:
- Client Work: ["STS Contract","Qualira (AWP)","Xodus Medical","Hand Consultants","DTG Engineering","Docs & Spreadsheets","Code & IDE","Comms","Admin & Billing"]
- Hobby: ["Programming","Machining & CAD","Video-Learning","Comms"]
- Entertainment: ["Gaming","Video","Social"]
Rules:
1) Any client indicator → Client Work with that client.
2) Prefer Hobby over Entertainment when educational/DIY terms are present.
3) Video domains without educational terms → Entertainment/Video.
4) Tie-break priority: Client Work > Hobby > Entertainment.
Return: {category, subcategory, client|null, confidence, rationale<=140}
```

User content per call (redacted):

```
{"app":"Zen Browser","domain":"stsdiesel.com","title":"STS – PPAP Control Plan – Google Docs","path_root":null,
 "hints":{"client_domains":{…},"client_keywords":{…},"edu_keywords":[…],"hobby_prog_keywords":[…]}}
```

Expected:

```
{"category":"Client Work","subcategory":"STS Contract","client":"STS Contract","confidence":0.96,"rationale":"STS domain + PPAP"}
```

# Pipeline

1. **Collector**: Poll window and web buckets since T-15m. Merge by temporal proximity. Drop AFK and <10s.
2. **Enricher**: Derive `domain` from URL, `path_root` from titles, normalize `app`, detect browser profile, extract repo path fragments.
3. **Redactor**: Strip emails, query strings, long IDs. Truncate titles to 120 chars.
4. **Cache**: key = SHA1(`app|domain|title|path_root`). TTL 7d. If hit, write cached label.
5. **Strong hints**: run client/domain/path checks. If hit, label and write.
6. **LLM**: If still ambiguous, call once with schema above.
7. **Gate**: If confidence ≥0.70, accept. Else rules fallback.
8. **Rules fallback**:

   * Media domains/apps → Entertainment/Video.
   * Social domains → Entertainment/Social.
   * Hobby dev terms → Hobby/Programming.
   * Machining/CAD terms → Hobby/Machining & CAD.
   * Else Uncategorized.
9. **Writer**: Post to `aw-llm-categories_{hostname}`.

# Implementation choices

* Language: Python 3.12. Requests + sqlite3. No heavy frameworks.
* Model: local first (Ollama/llama.cpp). Fallback to OpenAI API via env var. Always `temperature=0`, `response_format=json`.
* Service: NixOS systemd unit. Restart always. Env via service config.
* Logging: structured to stdout. Summaries per minute. Error with backoff.

# CLI

* `aw-sorter run --since 15m`
* `aw-sorter label <key> <Category/Sub>` writes correction and seeds few-shot memory.
* `aw-sorter stats` prints label distribution, LLM hit rate, cache hit rate.

# Tests

* Unit: redaction, domain parsing, strong-hint matching, rules fallback.
* Contract: reject any non-JSON LLM outputs; validate schema.
* Integration: simulate events covering each bucket; assert outputs and confidence.
* Load: 10k events replay within 60s on laptop.

# Definition of done

* New bucket present with correct schema.
* ≥90% of events resolved without LLM after first day due to cache/hints.
* Zero PII leaks in LLM inputs.
* Configurable clients without code changes.
* Systemd service healthy for 24h, no crashes.

# Stretch

* Time-boxed blocks with majority label.
* Per-client work time exports (CSV).
* On-device embedding index for zero-shot fallback.
