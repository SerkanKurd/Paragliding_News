import argparse
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.paragliding_news_crew.crew import ParaglidingNewsCrew
from src.paragliding_news_crew.tools.rss_news_tool import ParaglidingNewsFetchTool

# Reconfigure stdout to handle UTF-8 symbols cleanly on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8") # type: ignore

load_dotenv()


def sync_json_files():
    """Ensures news.json and outputs/news.json are synchronized incrementally."""
    root_json = Path("news.json")
    out_json = Path("outputs/news.json")

    if root_json.exists() and not out_json.exists():
        os.makedirs("outputs", exist_ok=True)
        shutil.copy(root_json, out_json)
    elif out_json.exists() and not root_json.exists():
        shutil.copy(out_json, root_json)


def run():
    parser = argparse.ArgumentParser(description="Paragliding News AI Agent Crew")
    parser.add_argument(
        "--topic",
        type=str,
        default="paragliding safety gear competition",
        help="Target topic or keyword for paragliding news search (e.g. 'safety', 'X-Alps', 'gear', 'PWC')",
    )
    args = parser.parse_args()

    api_base = os.getenv("OPENAI_API_BASE", "http://192.168.1.200:8080/v1")
    model_name = os.getenv("MODEL_NAME", "gemma-4-E2B-it-Q4_K_M.gguf")

    print("==================================================")
    print(" 🪂 PARAGLIDING NEWS AI AGENT CREW")
    print(f" LLM Provider: Llama Server ({api_base})")
    print(f" Model: {model_name}")
    print(f" Target Topic: '{args.topic}'")
    print("==================================================\n")

    print("[1/2] 🔍 Scraping RSS feeds & extracting full article content...")
    fetcher_tool = ParaglidingNewsFetchTool()
    news_text_data = fetcher_tool._run(query=args.topic, max_results=5)
    print("      ✓ Scraped & incrementally updated news.json!\n")

    print("[2/2] 🤖 Launching AI Agents to analyze & author digest...")
    inputs = {"topic": args.topic, "news_data": news_text_data}

    try:
        crew_instance = ParaglidingNewsCrew()
        result = crew_instance.crew().kickoff(inputs=inputs)

        sync_json_files()

        print("\n==================================================")
        print(" 🎯 PARAGLIDING DIGEST & JSON GENERATED SUCCESSFULLY!")
        print("==================================================")

        root_json = Path("news.json")
        if root_json.exists():
            print(f"[+] Incremental JSON dataset: {root_json.resolve()}")

        output_md = Path("outputs/paragliding_digest.md")
        if output_md.exists():
            print(f"[+] Markdown report saved to:  {output_md.resolve()}")

    except Exception as e:  # noqa: BLE001
        print(f"\n[!] Crew execution error: {e}")


if __name__ == "__main__":
    run()
