# 🪂 Paragliding News AI Agent (CrewAI + uv + Llama Server)

An autonomous **CrewAI** multi-agent project that monitors live RSS news feeds (Cross Country Magazine, Paragliding Forum, FAI, Google News), analyzes aviation safety advisories and competition reports, and synthesizes a publication-ready **Paragliding News Digest**.

## 🚀 Features

- **Managed with `uv`**: Fast, deterministic package resolution and Python 3.12 virtual environment management.
- **Network Llama Server**: Configured to connect directly to your local network Llama server running on `http://192.168.1.200:8080/v1`.
- **Multi-Agent Crew**:
  - **`news_scout`**: Scrapes live RSS feeds & fetches breaking paragliding news.
  - **`news_analyst`**: Fact-checks, categorizes, and extracts key pilot takeaways (Gear, Competitions, Safety, XC).
  - **`digest_editor`**: Authors styled Markdown reports saved to `outputs/paragliding_digest.md`.

---

## 🛠️ Configuration & Setup

1. **Set API Key & Model in `.env`**:
   Edit [.env](file:///d:/Wolf/Projelerim/CrewProject/.env):
   ```env
   OPENAI_API_BASE=http://192.168.1.200:8080/v1
   OPENAI_API_KEY=YOUR_API_KEY
   MODEL_NAME=openai/llama
   ```

2. **Sync Dependencies**:
   ```bash
   uv sync
   ```

---

## 💻 Usage

### Run Default Daily Scan
```bash
uv run python main.py
```

### Search Specific Topics (e.g. Safety, X-Alps, Gear)
```bash
uv run python main.py --topic "safety gear recalls"
uv run python main.py --topic "X-Alps competitions"
```

### Test RSS Tools Directly
```bash
uv run python test_tools.py
```

---

## 📁 Output

The generated report will be saved to:
`outputs/paragliding_digest.md`
