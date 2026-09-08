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

from src.paragliding_news_crew.database import insert_or_deduplicate


# Popular Paragliding RSS Feeds
RSS_FEEDS: Dict[str, str] = {
    "Cross Country Magazine": "https://xcmag.com/feed/",
    "Paragliding Forum": "https://www.paraglidingforum.com/rss.php",
    "Google News Paragliding": "https://news.google.com/rss/search?q=paragliding&hl=en-US&gl=US&ceid=US:en",
}


def clean_html(raw_html: str) -> str:
    """Strips HTML tags to yield clean text snippets."""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def resolve_real_url(url: str) -> str:
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


def fetch_single_article(url: str, fallback_summary: str = "") -> str:
    """
    Fetches and extracts full article text for a SINGLE article.
    Keeps length strictly bounded (~2500 chars) to prevent context window overflow.
    """
    if not url or not url.startswith("http"):
        return fallback_summary

    real_url = resolve_real_url(url)

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
                    for pb in post_bodies[:4]:
                        txt = pb.get_text(separator=" ", strip=True)
                        if len(txt) > 30:
                            posts_text.append(txt)
                    if posts_text:
                        return "\n\n---\n\n".join(posts_text)[:2500]
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
                return extracted.strip()[:2500]

            # Strategy 3: BeautifulSoup semantic fallback
            soup = BeautifulSoup(resp.text, "html.parser")
            for elem in soup(["script", "style", "nav", "header", "footer", "aside", "form", "iframe", "noscript"]):
                elem.decompose()

            main_node = (
                soup.find("article")
                or soup.find("main")
                or soup.find(class_=lambda c: c and any(k in c.lower() for k in ["entry-content", "post-content", "article-body", "article__body", "content"]))
                or soup.body
            )

            if main_node:
                paragraphs = [p.get_text(separator=" ", strip=True) for p in main_node.find_all("p")]
                full_text = "\n\n".join(p for p in paragraphs if len(p) > 25)
                if len(full_text) > 120:
                    return full_text[:2500]
    except Exception:
        pass

    return fallback_summary


def discover_paragliding_links(
    query: Optional[str] = "paragliding",
    max_results: int = 5,
    db_path: str = "news.db"
) -> List[Dict[str, str]]:
    """
    Stage 1: Discovers news links from RSS feeds and Google News.
    Resolves real URLs and saves deduplicated entries directly to SQLite with status='pending'.
    Prioritizes keeping translated articles when duplicates are found.
    """
    import feedparser

    discovered: List[Dict[str, str]] = []
    feeds = dict(RSS_FEEDS)

    if query and query.strip().lower() not in ["paragliding", "general"]:
        encoded_query = urllib.parse.quote(f"paragliding {query}")
        feeds[f"Google News ('{query}')"] = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"

    for source_name, feed_url in feeds.items():
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            req = urllib.request.Request(feed_url, headers=headers)
            with urllib.request.urlopen(req, timeout=8.0) as response:
                content = response.read()
                feed = feedparser.parse(content)

            for entry in feed.entries[:max_results]:
                title = entry.get("title", "No Title").strip()
                raw_link = entry.get("link", "").strip()
                published = entry.get("published", entry.get("updated", "Recent"))
                summary = clean_html(entry.get("summary", entry.get("description", "")))[:300]

                real_link = resolve_real_url(raw_link)
                if not real_link:
                    real_link = raw_link

                # Save or deduplicate in SQLite
                art_id = insert_or_deduplicate(
                    source=source_name,
                    title=title,
                    link=real_link,
                    published=published,
                    db_path=db_path
                )

                discovered.append({
                    "id": str(art_id) if art_id else "",
                    "source": source_name,
                    "title": title,
                    "link": real_link,
                    "published": published,
                    "summary": summary
                })
        except Exception as e:
            print(f"[!] Error fetching feed {source_name}: {e}")

    return discovered


class NewsSearchInput(BaseModel):
    """Input parameters for ParaglidingNewsFetchTool."""
    query: Optional[str] = Field(
        default="paragliding",
        description="Search query or topic keyword, e.g. 'safety', 'X-Alps', 'gear', 'competition'."
    )
    max_results: Optional[int] = Field(
        default=5,
        description="Maximum number of articles to return per source."
    )


class ParaglidingNewsFetchTool(BaseTool):
    name: str = "paragliding_news_fetch_tool"
    description: str = "Discovers and saves paragliding news links into SQLite database."
    args_schema: Type[BaseModel] = NewsSearchInput

    def _run(self, query: Optional[str] = "paragliding", max_results: Optional[int] = 5) -> str:
        items = discover_paragliding_links(query=query, max_results=max_results or 5)
        return f"Successfully discovered and saved {len(items)} links to SQLite database."
