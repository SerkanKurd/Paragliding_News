import os
import yaml
import shutil
from pathlib import Path
from dotenv import load_dotenv
from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, crew, task
from src.paragliding_news_crew.tools.rss_news_tool import ParaglidingNewsFetchTool
from src.paragliding_news_crew.models import ParaglidingNewsDigestJSON

# Load environment variables
load_dotenv()

@CrewBase
class ParaglidingNewsCrew():
    """Paragliding News Crew for fetching, analyzing, and formatting news."""

    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    def __init__(self) -> None:
        # Configure Llama Local/Network LLM Server (192.168.1.200:8080)
        api_base = os.getenv("OPENAI_API_BASE", "http://192.168.1.200:8080/v1").rstrip("/")
        if not api_base.endswith("/v1"):
            api_base += "/v1"

        api_key = os.getenv("OPENAI_API_KEY", "your_api_key_here")
        model_name = os.getenv("MODEL_NAME", "openai/llama")
        if not model_name.startswith("openai/"):
            model_name = f"openai/{model_name}"

        self.llm = LLM(
            model=model_name,
            base_url=api_base,
            api_key=api_key,
            temperature=0.6,
        )

        # Initialize tools
        self.rss_tool = ParaglidingNewsFetchTool()

    @agent
    def news_scout(self) -> Agent:
        return Agent(
            config=self.agents_config['news_scout'],
            tools=[self.rss_tool],
            llm=self.llm,
            verbose=True
        )

    @agent
    def news_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config['news_analyst'],
            llm=self.llm,
            verbose=True
        )

    @agent
    def digest_editor(self) -> Agent:
        return Agent(
            config=self.agents_config['digest_editor'],
            llm=self.llm,
            verbose=True
        )

    @task
    def fetch_news_task(self) -> Task:
        return Task(
            config=self.tasks_config['fetch_news_task']
        )

    @task
    def analyze_news_task(self) -> Task:
        return Task(
            config=self.tasks_config['analyze_news_task']
        )

    @task
    def write_digest_task(self) -> Task:
        os.makedirs("outputs", exist_ok=True)
        return Task(
            config=self.tasks_config['write_digest_task'],
            output_file='outputs/paragliding_digest.md'
        )

    @task
    def export_json_task(self) -> Task:
        os.makedirs("outputs", exist_ok=True)
        return Task(
            config=self.tasks_config['export_json_task'],
            output_json=ParaglidingNewsDigestJSON,
            output_file='outputs/news.json'
        )

    @crew
    def crew(self) -> Crew:
        """Creates the Paragliding News Crew"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True
        )
