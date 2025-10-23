# ActivityWatch LLM Categorizer (Time Goggles)

An intelligent sidecar application that enriches and categorizes ActivityWatch events using LLM-powered classification with deterministic fallbacks.

## Overview

This project implements an ActivityWatch categorizer that:
- Polls existing ActivityWatch buckets (window, web, afk events)
- Enriches events with derived metadata (domains, paths, normalized apps)
- Classifies events into hierarchical categories using a multi-tier strategy
- Writes categorized events to a new bucket for analysis

## Features

### Multi-Tier Classification Strategy

1. **Cache** (7-day TTL) - Instant classification for repeated patterns
2. **Strong Hints** (conf=0.98) - Domain/path/keyword matching for client work
3. **LLM** (conf≥0.70) - Ollama (local) or OpenAI for ambiguous cases
4. **Rules Fallback** - Deterministic classification when LLM unavailable

### Categories

**Client Work:**
- STS Contract
- Qualira (AWP)
- Xodus Medical
- Hand Consultants
- DTG Engineering
- Docs & Spreadsheets
- Code & IDE
- Comms
- Admin & Billing

**Hobby:**
- Programming
- Machining & CAD
- Video-Learning
- Comms

**Entertainment:**
- Gaming
- Video
- Social

**Uncategorized:** Fallback category

### Privacy & Security

- PII redaction before LLM calls (emails, UUIDs, query params)
- No raw URLs with sensitive tokens sent to LLM
- Offline-capable with deterministic fallbacks
- Local-first LLM support via Ollama

## Installation

### Prerequisites

- Python 3.11+
- ActivityWatch server running
- (Optional) Ollama for local LLM
- (Optional) OpenAI API key for cloud LLM

### NixOS (Recommended)

```bash
# Enter development shell
nix develop

# Install dependencies
poetry install

# Copy and customize config
cp config.example.yaml config.yaml
# Edit config.yaml with your client definitions
```

### Manual Installation

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with poetry
poetry install

# Or with pip
pip install -e .
```

## Configuration

Copy `config.example.yaml` to `config.yaml` and customize:

```yaml
clients:
  "Your Client Name":
    domains: ["client-domain.com"]
    keywords: ["Client", "Project", "Keywords"]
    paths: ["/path/to/client/work"]

llm:
  provider: "ollama"  # or "openai"
  ollama:
    host: "http://localhost:11434"
    model: "llama3"
  openai:
    model: "gpt-4o-mini"  # requires OPENAI_API_KEY env var

thresholds:
  min_duration_sec: 10
  llm_confidence_min: 0.70
  cache_ttl_days: 7
```

## Usage

### CLI Commands

```bash
# Run once (process last 15 minutes)
aw-sorter run

# Run with custom lookback
aw-sorter run --since 60

# Run continuously (polls every minute)
aw-sorter run --continuous

# View statistics
aw-sorter stats

# Manual labeling (coming soon)
aw-sorter label <cache_key> "Client Work" "STS Contract"
```

### As a Service (NixOS)

```nix
# In your NixOS configuration
systemd.services.aw-llm-worker = {
  description = "ActivityWatch LLM Categorizer";
  after = [ "network.target" ];
  wantedBy = [ "multi-user.target" ];

  serviceConfig = {
    Type = "simple";
    User = "your-user";
    WorkingDirectory = "/path/to/time-goggles";
    ExecStart = "${pkgs.poetry}/bin/poetry run aw-sorter run --continuous";
    Restart = "always";
  };

  environment = {
    # Optional: for OpenAI
    OPENAI_API_KEY = "your-key-here";
  };
};
```

## Architecture

### Data Pipeline

```
AW Events → Collector → Enricher → Redactor
                                      ↓
                               Cache Check ←→ SQLite Cache
                                      ↓
                              Strong Hints? → High-confidence match
                                      ↓
                                 LLM Call? → Ollama/OpenAI
                                      ↓
                              Rules Fallback → Deterministic
                                      ↓
                                   Writer → aw-llm-categories_<hostname>
```

### Modules

- `models.py` - Data schemas (CategorizedEvent, CategoryResult, EnrichedFeatures)
- `config.py` - YAML configuration with hot-reload
- `collector.py` - Poll AW buckets, filter by duration/AFK
- `enricher.py` - Extract domain, path, normalize apps
- `redactor.py` - Strip PII (emails, IDs, query params)
- `cache.py` - SQLite cache with TTL and SHA1 keys
- `strong_hints.py` - High-confidence client matching
- `llm.py` - Ollama + OpenAI integration
- `rules.py` - Deterministic fallback classifier
- `writer.py` - Write to AW output bucket

## Development

### Project Structure

```
time-goggles/
├── aw_llm_worker/          # Main Python package
│   ├── __init__.py
│   ├── __main__.py         # CLI entry point
│   ├── models.py
│   ├── config.py
│   ├── collector.py
│   ├── enricher.py
│   ├── redactor.py
│   ├── cache.py
│   ├── strong_hints.py
│   ├── llm.py
│   ├── rules.py
│   └── writer.py
├── activitywatch_src/      # AW source (reference)
├── config.example.yaml     # Example configuration
├── pyproject.toml          # Poetry dependencies
├── flake.nix               # Nix development environment
└── README.md
```

### Testing

```bash
# Run tests (coming soon)
poetry run pytest

# Type checking
poetry run mypy aw_llm_worker

# Linting
poetry run ruff check aw_llm_worker
```

## Performance Targets

- ≥90% cache hit rate after first day
- <60s to process 10k events
- Zero PII leaks to LLM
- Offline-capable with deterministic fallbacks

## Troubleshooting

### Common Issues

**"No source buckets found"**
- Ensure ActivityWatch is running
- Check bucket names match your hostname: `aw-watcher-window_<hostname>`

**"Ollama connection refused"**
- Start Ollama: `ollama serve`
- Check host in config: `http://localhost:11434`

**"Low LLM hit rate"**
- Check confidence threshold (default 0.70)
- Review strong hints configuration
- Verify client domain/keyword matches

### Debugging

```bash
# Enable debug logging
aw-sorter --log-level DEBUG run

# Check cache stats
aw-sorter stats

# View ActivityWatch buckets
aw-client buckets list
```

## License

Mozilla Public License 2.0 (following ActivityWatch)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## Acknowledgments

- Built on [ActivityWatch](https://activitywatch.net/)
- Uses Ollama for local LLM inference
- Inspired by ActivityWatch's suggest_categories_gpt.py example

---

**Note:** This is an independent sidecar application. It reads from and writes to ActivityWatch buckets but does not modify the core ActivityWatch installation.
