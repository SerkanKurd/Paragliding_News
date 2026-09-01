from typing import List, Optional
from pydantic import BaseModel, Field


class NewsArticle(BaseModel):
    title: str = Field(description="Headline/title of the paragliding news article")
    source: str = Field(description="Source website or RSS feed (e.g. Cross Country Magazine, Paragliding Forum, FAI)")
    published: str = Field(description="Publication date or recency indicator")
    link: str = Field(description="Direct URL link to the original article or discussion thread")
    category: str = Field(description="Category: Gear & Equipment, Competitions & Records, Flight Safety & Community, or XC & Adventure")
    summary: str = Field(description="Concise summary of the news story")
    content: str = Field(description="Full text content of the news article")
    pilot_takeaway: str = Field(description="Key lesson, safety recommendation, or practical takeaway for free-flight pilots")


class ParaglidingNewsDigestJSON(BaseModel):
    title: str = Field(default="🪂 Paragliding Daily Digest", description="Title of the digest report")
    date: str = Field(description="Date or timestamp of the digest generation")
    topic: str = Field(description="Target topic or search filter applied")
    editors_note: str = Field(description="Brief editorial commentary on current paragliding trends and safety")
    total_articles: int = Field(description="Number of articles included in the digest")
    articles: List[NewsArticle] = Field(description="Structured array of analyzed paragliding news articles")
