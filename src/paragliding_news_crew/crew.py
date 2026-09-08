import os
import re
from typing import Any, Dict, Optional

from crewai import LLM, Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from dotenv import load_dotenv

from src.paragliding_news_crew.tools.rss_news_tool import ParaglidingNewsFetchTool


load_dotenv()


@CrewBase
class ParaglidingNewsCrew:
    """Paragliding News Crew with modular agents for single-article analysis and translation."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(self) -> None:
        api_base = os.getenv("OPENAI_API_BASE", "http://192.168.1.200:8080/v1").rstrip("/")
        if not api_base.endswith("/v1"):
            api_base += "/v1"

        api_key = os.getenv("OPENAI_API_KEY", "your_api_key_here")
        model_name = os.getenv("MODEL_NAME", "openai//models/gemma-4-E2B-it-Q4_K_M.gguf")
        if not model_name.startswith("openai/"):
            model_name = f"openai/{model_name}"

        self.llm = LLM(
            model=model_name,
            base_url=api_base,
            api_key=api_key,
            temperature=0.3,
        )

        self.rss_tool = ParaglidingNewsFetchTool()

    @agent
    def news_scout(self) -> Agent:
        return Agent(
            config=self.agents_config["news_scout"],
            tools=[self.rss_tool],
            llm=self.llm,
            verbose=False,
        )

    @agent
    def article_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["article_analyst"],
            llm=self.llm,
            verbose=False,
        )

    @agent
    def aviation_translator(self) -> Agent:
        return Agent(
            config=self.agents_config["aviation_translator"],
            llm=self.llm,
            verbose=False,
        )

    def analyze_article(self, article: Dict[str, Any]) -> Dict[str, str]:
        """
        Executes Model 2 (Article Analyst) on a SINGLE article.
        Input context is strictly bounded to prevent exceeding 8192 context window.
        """
        content_preview = (article.get("raw_content") or article.get("summary") or "")[:2500]

        analysis_task = Task(
            description=(
                f"Analyze the single paragliding article:\n"
                f"SOURCE: {article.get('source')}\n"
                f"TITLE: {article.get('title')}\n"
                f"URL: {article.get('link')}\n\n"
                f"CONTENT:\n{content_preview}\n\n"
                f"Extract:\n"
                f"1. CATEGORY: (one of 'Gear & Equipment', 'Competitions & Records', 'Flight Safety & Advisories', 'XC & Adventure')\n"
                f"2. SUMMARY: (2-3 concise English sentences)\n"
                f"3. PILOT_TAKEAWAY: (1-2 actionable pilot lessons)\n"
                f"Format output as:\n"
                f"CATEGORY: <category>\n"
                f"SUMMARY: <summary>\n"
                f"PILOT_TAKEAWAY: <takeaway>"
            ),
            expected_output="CATEGORY, SUMMARY, and PILOT_TAKEAWAY text.",
            agent=self.article_analyst(),
        )

        single_crew = Crew(
            agents=[self.article_analyst()],
            tasks=[analysis_task],
            process=Process.sequential,
            verbose=False,
        )

        output_str = str(single_crew.kickoff()).strip()

        # Parse outputs
        category = "Flight Safety & Advisories"
        summary_en = ""
        pilot_takeaway_en = ""

        cat_m = re.search(r"CATEGORY:\s*(.+)", output_str, re.IGNORECASE)
        if cat_m:
            category = cat_m.group(1).strip()

        sum_m = re.search(r"SUMMARY:\s*(.+?)(?=PILOT_TAKEAWAY:|$)", output_str, re.IGNORECASE | re.DOTALL)
        if sum_m:
            summary_en = sum_m.group(1).strip()

        take_m = re.search(r"PILOT_TAKEAWAY:\s*(.+)", output_str, re.IGNORECASE | re.DOTALL)
        if take_m:
            pilot_takeaway_en = take_m.group(1).strip()

        if not summary_en:
            summary_en = output_str[:300]
        if not pilot_takeaway_en:
            pilot_takeaway_en = "Stay updated with local flight manuals and safety guidelines."

        return {
            "category": category,
            "summary_en": summary_en,
            "pilot_takeaway_en": pilot_takeaway_en,
        }

    def translate_article(self, article: Dict[str, Any]) -> Dict[str, str]:
        """
        Executes Model 3 (Aviation Translator) on a SINGLE analyzed article.
        Translates into Turkish with proper free-flight terminology.
        """
        trans_task = Task(
            description=(
                f"Translate this analyzed paragliding story into fluent Turkish for paragliding pilots:\n"
                f"ENGLISH TITLE: {article.get('title')}\n"
                f"CATEGORY: {article.get('category')}\n"
                f"ENGLISH SUMMARY: {article.get('summary_en')}\n"
                f"ENGLISH PILOT TAKEAWAY: {article.get('pilot_takeaway_en')}\n\n"
                f"Use genuine Turkish pilot terminology (termik, asimetrik kapanma, yedek atımı, harnes, speedbar, vol-bivouac).\n"
                f"Format output EXACTLY as:\n"
                f"TITLE_TR: <Turkish title>\n"
                f"SUMMARY_TR: <Turkish summary>\n"
                f"PILOT_TAKEAWAY_TR: <Turkish pilot takeaway>"
            ),
            expected_output="TITLE_TR, SUMMARY_TR, and PILOT_TAKEAWAY_TR text.",
            agent=self.aviation_translator(),
        )

        single_crew = Crew(
            agents=[self.aviation_translator()],
            tasks=[trans_task],
            process=Process.sequential,
            verbose=False,
        )

        output_str = str(single_crew.kickoff()).strip()

        title_tr = ""
        summary_tr = ""
        takeaway_tr = ""

        title_m = re.search(r"TITLE_TR:\s*(.+)", output_str, re.IGNORECASE)
        if title_m:
            title_tr = title_m.group(1).strip()

        sum_m = re.search(r"SUMMARY_TR:\s*(.+?)(?=PILOT_TAKEAWAY_TR:|$)", output_str, re.IGNORECASE | re.DOTALL)
        if sum_m:
            summary_tr = sum_m.group(1).strip()

        take_m = re.search(r"PILOT_TAKEAWAY_TR:\s*(.+)", output_str, re.IGNORECASE | re.DOTALL)
        if take_m:
            takeaway_tr = take_m.group(1).strip()

        if not title_tr:
            title_tr = article.get("title", "")
        if not summary_tr:
            summary_tr = article.get("summary_en", "")
        if not takeaway_tr:
            takeaway_tr = article.get("pilot_takeaway_en", "")

        return {
            "title_tr": title_tr,
            "summary_tr": summary_tr,
            "pilot_takeaway_tr": takeaway_tr,
        }
