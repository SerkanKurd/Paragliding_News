import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

from bs4 import BeautifulSoup
from crewai.tools import BaseTool
from curl_cffi import requests as cureq
from googlenewsdecoder import gnewsdecoder
from pydantic import BaseModel, Field
import trafilatura


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

    def _resolve_real_url(self, url: str) -> str:
        """Resolves Google News redirects and tracking links into real source URLs."""
        if not url:
            return ""
        if "news.google.com" in url:
            try:
                decoded = gnewsdecoder(url)
                if isinstance(decoded, dict) and decoded.get("status") and decoded.get("decoded_url"):
                    return decoded["decoded_url"]
            except Exception:
                pass
        return url

    def _fetch_full_article_text(self, url: str, fallback_summary: str) -> str:
        """Fetches and extracts full article text using trafilatura, curl_cffi, and custom HTML parsers."""
        if not url or not url.startswith("http"):
            return fallback_summary

        real_url = self._resolve_real_url(url)

        # Strategy 1: Paragliding Forum custom post extraction (span.postbody)
        if "paraglidingforum.com" in real_url:
            try:
                resp = cureq.get(real_url, impersonate="chrome124", timeout=10)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for el in soup.find_all(class_=["postdetails", "genmed"]):
                        el.decompose()
                    post_bodies = soup.find_all("span", class_="postbody")
                    if post_bodies:
                        posts_text = []
                        for pb in post_bodies[:5]:
                            txt = pb.get_text(separator=" ", strip=True)
                            if len(txt) > 30:
                                posts_text.append(txt)
                        if posts_text:
                            return "\n\n---\n\n".join(posts_text)[:3500]
            except Exception:
                pass

        # Strategy 2: High fidelity article extraction using curl_cffi + trafilatura
        try:
            resp = cureq.get(real_url, impersonate="chrome124", timeout=10)
            if resp.status_code == 200 and resp.text:
                extracted = trafilatura.extract(
                    resp.text,
                    include_comments=False,
                    include_tables=True,
                    no_fallback=False
                )
                if extracted and len(extracted.strip()) > 150:
                    return extracted.strip()[:4000]

                # Strategy 3: BeautifulSoup semantic content extraction fallback
                soup = BeautifulSoup(resp.text, "html.parser")
                for elem in soup(["script", "style", "nav", "header", "footer", "aside", "form", "iframe", "noscript"]):
                    elem.decompose()

                main_node = (
                    soup.find("article")
                    or soup.find("main")
                    or soup.find(class_=lambda c: c and any(k in c.lower() for k in ["entry-content", "post-content", "article-body", "article__body", "content", "story-body"]))
                    or soup.body
                )

                if main_node:
                    paragraphs = [p.get_text(separator=" ", strip=True) for p in main_node.find_all("p")]
                    full_text = "\n\n".join(p for p in paragraphs if len(p) > 25)
                    if len(full_text) > 120:
                        return full_text[:4000]
        except Exception:
            pass

        return fallback_summary

    def _fetch_rss(self, feed_url: str, source_name: str, max_results: int) -> List[Dict[str, str]]:
        """Parses an RSS feed and returns structured items with full article content."""
        import feedparser
        articles = []
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            req = urllib.request.Request(feed_url, headers=headers)
            with urllib.request.urlopen(req, timeout=8.0) as response:
                content = response.read()
                feed = feedparser.parse(content)

            for entry in feed.entries[:max_results]:
                title = entry.get("title", "No Title")
                link = entry.get("link", "")
                published = entry.get("published", entry.get("updated", "Recent"))
                summary_raw = entry.get("summary", entry.get("description", ""))
                summary = self._clean_html(summary_raw)[:400]

                # Extract full content from RSS content field if present, otherwise fetch from webpage
                rss_content_raw = ""
                if "content" in entry and len(entry["content"]) > 0:
                    rss_content_raw = entry["content"][0].get("value", "")

                rss_clean = self._clean_html(rss_content_raw)
                real_link = self._resolve_real_url(link)

                if len(rss_clean) > 500:
                    full_content = rss_clean
                else:
                    full_content = self._fetch_full_article_text(real_link, summary)
                    if len(full_content) < len(rss_clean) and len(rss_clean) > 100:
                        full_content = rss_clean

                articles.append({
                    "source": source_name,
                    "title": title,
                    "link": real_link if real_link else link,
                    "published": published,
                    "summary": summary,
                    "content": full_content
                })
        except Exception as e:
            articles.append({
                "source": source_name,
                "title": f"Status update for {source_name}",
                "link": feed_url,
                "published": "N/A",
                "summary": f"Could not reach feed directly ({e}). Using topic index.",
                "content": f"Failed to fetch content from {source_name}: {e}"
            })

        return articles

    def _save_json(self, new_articles: List[Dict[str, str]], query: str):
        """Merges new articles into existing news.json including full article content."""
        os.makedirs("outputs", exist_ok=True)

        for filepath in ["news.json", "outputs/news.json"]:
            existing_articles = []
            existing_keys = {}

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

            for idx, art in enumerate(existing_articles):
                link = art.get("link", "").strip()
                title = art.get("title", "").strip()
                key = link if link else title
                if key:
                    existing_keys[key] = idx

            merged_articles = list(existing_articles)
            added_count = 0
            updated_count = 0

            for art in new_articles:
                link = art.get("link", "").strip()
                title = art.get("title", "").strip()
                key = link if link else title

                if key in existing_keys:
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
        """Executes news retrieval across all configured feeds and formats full article content for agents."""
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

        # Format output into rich text for LLM agents including FULL article content
        output_lines = [f"=== PARAGLIDING NEWS FETCH RESULTS (Query: '{query}') ===\n"]
        for idx, item in enumerate(all_articles, 1):
            output_lines.append(f"[{idx}] SOURCE: {item['source'].upper()}")
            output_lines.append(f"TITLE: {item['title']}")
            output_lines.append(f"PUBLISHED: {item['published']}")
            output_lines.append(f"LINK: {item['link']}")
            output_lines.append(f"SUMMARY: {item['summary']}")

            # Include the substantive full article text so agents have complete context
            full_text = item.get("content", "").strip()
            if full_text and len(full_text) > len(item.get("summary", "")):
                output_lines.append(f"FULL ARTICLE CONTENT:\n{full_text[:2500]}")
            output_lines.append("-" * 50 + "\n")

        return "\n".join(output_lines)
