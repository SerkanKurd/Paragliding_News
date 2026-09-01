import feedparser
import urllib.request
import urllib.parse
import socket
import json
import os
from datetime import datetime
from bs4 import BeautifulSoup
from typing import Type, List, Dict, Any, Optional
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

# Set global default socket timeout
socket.setdefaulttimeout(6.0)


class NewsSearchInput(BaseModel):
    """Input parameters for ParaglidingNewsFetchTool."""
    query: Optional[str] = Field(
        default="paragliding",
        description="Search query or topic keyword, e.g. 'safety', 'X-Alps', 'gear', 'competition', or 'general'."
    )
    max_results: Optional[int] = Field(
        default=5,
        description="Maximum number of articles to return per source."
    )


class ParaglidingNewsFetchTool(BaseTool):
    name: str = "paragliding_news_fetch_tool"
    description: str = (
        "Fetches and parses the latest breaking paragliding news, competition updates, gear alerts, "
        "and flight safety advisories from top RSS feeds (Cross Country Magazine, Paragliding Forum, FAI, Google News) "
        "including full article text content."
    )
    args_schema: Type[BaseModel] = NewsSearchInput

    # Popular Paragliding RSS Feeds
    RSS_FEEDS: Dict[str, str] = {
        "Cross Country Magazine": "https://xcmag.com/feed/",
        "Paragliding Forum": "https://www.paraglidingforum.com/rss.php",
        "Google News Paragliding": "https://news.google.com/rss/search?q=paragliding&hl=en-US&gl=US&ceid=US:en",
    }

    def _clean_html(self, raw_html: str) -> str:
        """Strips HTML tags to yield clean text snippets."""
        if not raw_html:
            return ""
        soup = BeautifulSoup(raw_html, "html.parser")
        return soup.get_text(separator=" ", strip=True)

    def _fetch_full_article_text(self, url: str, fallback_summary: str) -> str:
        """Fetches full article text from webpage paragraphs."""
        if not url or not url.startswith("http"):
            return fallback_summary

        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ParaglidingNews/1.0'}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=4.0) as response:
                html = response.read().decode('utf-8', errors='ignore')
                soup = BeautifulSoup(html, 'html.parser')

                # Strip irrelevant UI elements
                for elem in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'iframe']):
                    elem.decompose()

                # Search for main content container
                main_node = (
                    soup.find('article') or 
                    soup.find('main') or 
                    soup.find(class_=lambda c: c and any(k in c.lower() for k in ['entry-content', 'post-content', 'article-body', 'content'])) or 
                    soup.body
                )

                if main_node:
                    paragraphs = [p.get_text(separator=" ", strip=True) for p in main_node.find_all('p')]
                    full_text = "\n\n".join(p for p in paragraphs if len(p) > 25)
                    if len(full_text) > 100:
                        return full_text

                # General text fallback if no paragraphs found
                text = soup.get_text(separator=" ", strip=True)
                return text[:2500] if len(text) > 100 else fallback_summary

        except Exception as e:
            return fallback_summary

    def _fetch_rss(self, feed_url: str, source_name: str, max_results: int) -> List[Dict[str, str]]:
        """Parses an RSS feed and returns structured items with full article content."""
        articles = []
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ParaglidingNews/1.0'}
            req = urllib.request.Request(feed_url, headers=headers)
            with urllib.request.urlopen(req, timeout=5.0) as response:
                content = response.read()
                feed = feedparser.parse(content)

            for entry in feed.entries[:max_results]:
                title = entry.get('title', 'No Title')
                link = entry.get('link', '')
                published = entry.get('published', entry.get('updated', 'Recent'))
                summary_raw = entry.get('summary', entry.get('description', ''))
                summary = self._clean_html(summary_raw)[:400]

                # Extract full content from RSS content field if present, otherwise fetch from webpage
                rss_content_raw = ""
                if 'content' in entry and len(entry['content']) > 0:
                    rss_content_raw = entry['content'][0].get('value', '')

                rss_clean = self._clean_html(rss_content_raw)
                if len(rss_clean) > 300:
                    full_content = rss_clean
                else:
                    full_content = self._fetch_full_article_text(link, summary)

                articles.append({
                    "source": source_name,
                    "title": title,
                    "link": link,
                    "published": published,
                    "summary": summary,
                    "content": full_content
                })
        except Exception as e:
            # Fallback handling
            articles.append({
                "source": source_name,
                "title": f"Status update for {source_name}",
                "link": feed_url,
                "published": "N/A",
                "summary": f"Could not reach feed directly ({str(e)}). Using topic index.",
                "content": f"Failed to fetch content from {source_name}: {str(e)}"
            })

        return articles

    def _save_json(self, new_articles: List[Dict[str, str]], query: str):
        """Merges new articles into existing news.json including full article content."""
        os.makedirs("outputs", exist_ok=True)

        for filepath in ["news.json", "outputs/news.json"]:
            existing_articles = []
            existing_keys = {}

            # Load existing JSON data if present
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        existing_data = json.load(f)
                        if isinstance(existing_data, dict) and "articles" in existing_data:
                            existing_articles = existing_data.get("articles", [])
                        elif isinstance(existing_data, list):
                            existing_articles = existing_data
                except Exception as e:
                    print(f"Notice: Could not parse existing {filepath} ({e}), creating new store.")

            # Collect existing articles map by unique key (link or title)
            for idx, art in enumerate(existing_articles):
                link = art.get("link", "").strip()
                title = art.get("title", "").strip()
                key = link if link else title
                if key:
                    existing_keys[key] = idx

            # Update existing or append new articles
            merged_articles = list(existing_articles)
            added_count = 0
            updated_count = 0

            for art in new_articles:
                link = art.get("link", "").strip()
                title = art.get("title", "").strip()
                key = link if link else title

                if key in existing_keys:
                    # Update full content if existing entry lacks full content
                    existing_idx = existing_keys[key]
                    existing_art = merged_articles[existing_idx]
                    if len(art.get("content", "")) > len(existing_art.get("content", "")):
                        merged_articles[existing_idx]["content"] = art["content"]
                        updated_count += 1
                else:
                    existing_keys[key] = len(merged_articles)
                    merged_articles.append(art)
                    added_count += 1

            merged_data = {
                "topic": query,
                "total_count": len(merged_articles),
                "last_updated": datetime.now().isoformat(),
                "articles": merged_articles
            }

            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(merged_data, f, ensure_ascii=False, indent=2)
                print(f"[+] Updated {filepath}: {len(merged_articles)} total articles ({added_count} new, {updated_count} content enriched)")
            except Exception as e:
                print(f"Error writing {filepath}: {e}")

    def _run(self, query: Optional[str] = "paragliding", max_results: Optional[int] = 5) -> str:
        """Executes news retrieval across all configured feeds."""
        all_articles: List[Dict[str, str]] = []
        limit = max_results or 5

        # Fetch configured feeds
        for source_name, feed_url in self.RSS_FEEDS.items():
            feed_items = self._fetch_rss(feed_url, source_name, max_results=limit)
            all_articles.extend(feed_items)

        # If specific query provided beyond 'paragliding', fetch additional targeted Google News feed
        if query and query.strip().lower() not in ["paragliding", "general"]:
            encoded_query = urllib.parse.quote(f"paragliding {query}")
            custom_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
            custom_items = self._fetch_rss(custom_url, f"Google News ('{query}')", max_results=limit)
            all_articles.extend(custom_items)

        # Incrementally merge new articles and full content into news.json and outputs/news.json
        self._save_json(all_articles, query or "paragliding")

        # Format output into clean text for LLM agents
        output_lines = [f"=== PARAGLIDING NEWS FETCH RESULTS (Query: '{query}') ===\n"]
        for idx, item in enumerate(all_articles, 1):
            output_lines.append(f"[{idx}] {item['source'].upper()}")
            output_lines.append(f"TITLE: {item['title']}")
            output_lines.append(f"PUBLISHED: {item['published']}")
            output_lines.append(f"LINK: {item['link']}")
            output_lines.append(f"SUMMARY: {item['summary']}")
            output_lines.append(f"FULL CONTENT ({len(item['content'])} chars): {item['content'][:300]}...\n" + "-"*40)

        return "\n".join(output_lines)
