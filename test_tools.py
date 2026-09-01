import sys
from src.paragliding_news_crew.tools.rss_news_tool import ParaglidingNewsFetchTool

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print("Testing ParaglidingNewsFetchTool with new topic...")
    tool = ParaglidingNewsFetchTool()
    results = tool._run(query="X-Alps Red Bull paragliding competition", max_results=3)
    print("Fetch Completed!")

if __name__ == "__main__":
    main()
