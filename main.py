import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

from src.paragliding_news_crew.crew import ParaglidingNewsCrew
from src.paragliding_news_crew.database import (
    clean_database_duplicates,
    get_latest_translated_articles,
    get_pending_articles,
    get_stats,
    get_untranslated_articles,
    init_db,
    mark_article_failed,
    update_analyzed_article,
    update_translated_article,
)
from src.paragliding_news_crew.tools.rss_news_tool import (
    discover_paragliding_links,
    fetch_single_article,
)

# Handle UTF-8 output cleanly on Windows terminal
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore

load_dotenv()


def compile_markdown_digests(articles: List[Dict[str, Any]]):
    """Compiles both Turkish and English publication-ready Markdown digests from SQLite."""
    os.makedirs("outputs", exist_ok=True)
    today_str = datetime.now().strftime("%d %B %Y")

    # Group by category
    categories = {
        "Flight Safety & Advisories": {
            "tr_title": "🛡️ Uçuş Emniyeti & Güvenlik Bültenleri",
            "articles": [],
        },
        "Gear & Equipment": {
            "tr_title": "⚙️ Kanat, Harnes & Ekipman Gelişmeleri",
            "articles": [],
        },
        "Competitions & Records": {
            "tr_title": "🏆 Yarışmalar & Dünya Rekorları",
            "articles": [],
        },
        "XC & Adventure": {
            "tr_title": "🌄 XC & Vol-Bivouac Maceraları",
            "articles": [],
        },
    }

    for art in articles:
        cat = art.get("category") or "Flight Safety & Advisories"
        matched = False
        for key in categories:
            if key.lower() in cat.lower():
                categories[key]["articles"].append(art)
                matched = True
                break
        if not matched:
            categories["Flight Safety & Advisories"]["articles"].append(art)

    # 1. Turkish Digest
    tr_lines = [
        f"# 🪂 Günlük Yamaç Paraşütü Pilot Bülteni ({today_str})",
        "",
        "> **Editörün Notu:** Bu bülten, küresel serbest uçuş ve havacılık RSS kaynaklarından otonom olarak toplanmış, yapay zeka tarafından analiz edilmiş ve Türkçe havacılık terminolojisine göre uyarlanmıştır.",
        "",
        "---",
        "",
    ]

    for cat_data in categories.values():
        if cat_data["articles"]:
            tr_lines.append(f"## {cat_data['tr_title']}\n")
            for art in cat_data["articles"]:
                title_tr = art.get("title_tr") or art.get("title")
                summary_tr = art.get("summary_tr") or art.get("summary_en")
                takeaway_tr = art.get("pilot_takeaway_tr") or art.get("pilot_takeaway_en")
                source = art.get("source", "Bilinmeyen Kaynak")
                link = art.get("link", "#")

                tr_lines.append(f"### 🔹 [{title_tr}]({link})")
                tr_lines.append(f"**Kaynak:** {source} | **Yayın:** {art.get('published', 'N/A')}\n")
                tr_lines.append(f"{summary_tr}\n")
                if takeaway_tr:
                    tr_lines.append(f"> 💡 **Pilot İçin Çıkarım / Emniyet Notu:** {takeaway_tr}\n")
                tr_lines.append("---\n")

    tr_path = Path("outputs/paragliding_digest_tr.md")
    with open(tr_path, "w", encoding="utf-8") as f:
        f.write("\n".join(tr_lines))

    # 2. English Digest
    en_lines = [
        f"# 🪂 Paragliding Daily Pilot Digest ({today_str})",
        "",
        "> **Editor's Note:** Synthesized autonomous intelligence report for free-flight pilots, covering breaking safety notices, gear releases, and competitions.",
        "",
        "---",
        "",
    ]

    for cat_key, cat_data in categories.items():
        if cat_data["articles"]:
            en_lines.append(f"## {cat_key}\n")
            for art in cat_data["articles"]:
                title = art.get("title")
                summary = art.get("summary_en")
                takeaway = art.get("pilot_takeaway_en")
                source = art.get("source")
                link = art.get("link", "#")

                en_lines.append(f"### 🔹 [{title}]({link})")
                en_lines.append(f"**Source:** {source} | **Published:** {art.get('published', 'N/A')}\n")
                en_lines.append(f"{summary}\n")
                if takeaway:
                    en_lines.append(f"> 💡 **Pilot Takeaway:** {takeaway}\n")
                en_lines.append("---\n")

    en_path = Path("outputs/paragliding_digest_en.md")
    with open(en_path, "w", encoding="utf-8") as f:
        f.write("\n".join(en_lines))

    return tr_path, en_path


def run():
    parser = argparse.ArgumentParser(description="3-Stage SQLite Paragliding News AI Agent")
    parser.add_argument(
        "--topic",
        type=str,
        default="paragliding safety gear competition",
        help="Target topic or keyword for paragliding news search",
    )
    parser.add_argument(
        "--max-discover",
        type=int,
        default=4,
        help="Maximum new articles to discover per RSS feed",
    )
    parser.add_argument(
        "--process-limit",
        type=int,
        default=5,
        help="Number of pending articles to analyze & translate one-by-one in this run",
    )
    args = parser.parse_args()

    api_base = os.getenv("OPENAI_API_BASE", "http://192.168.1.200:8080/v1")
    model_name = os.getenv("MODEL_NAME", "gemma-4-E2B-it-Q4_K_M.gguf")

    print("==================================================")
    print(" 🪂 3-STAGE SQLITE PARAGLIDING NEWS AI PIPELINE")
    print(f" LLM Provider: {api_base}")
    print(f" Model: {model_name} (Strict 8192 Safe)")
    print(f" Topic: '{args.topic}'")
    print("==================================================\n")

    # Initialize Database & clean existing duplicates (keeping translated ones)
    init_db("news.db")
    cleaned_dups = clean_database_duplicates("news.db")
    if cleaned_dups > 0:
        print(f"[+] Mükerrer temizliği yapıldı: {cleaned_dups} adet çevrilmemiş mükerrer kayıt temizlendi.")

    # ---------------------------------------------------------
    # STAGE 1: Discovery & Deduplication (Link Scout)
    # ---------------------------------------------------------
    print(f"[Aşama 1/3] 🔍 Haber linkleri taranıyor ve SQLite'a kaydediliyor (Maks: {args.max_discover}/kaynak)...")
    discovered = discover_paragliding_links(query=args.topic, max_results=args.max_discover, db_path="news.db")
    print(f"            ✓ {len(discovered)} adet link kontrol edildi/kaydedildi.")
    print(f"            ✓ Güncel veritabanı durumu: {get_stats('news.db')}\n")

    crew = ParaglidingNewsCrew()

    # ---------------------------------------------------------
    # STAGE 2: One-by-One Article Analysis (Article Analyst)
    # ---------------------------------------------------------
    pending = get_pending_articles(limit=args.process_limit, db_path="news.db")
    print(f"[Aşama 2/3] 🤖 Bekleyen makaleler TEK TEK analiz ediliyor ({len(pending)} adet işlenecek)...")
    print("            (Her makale ayrı işlendiğinden Context 8192 asla aşılmaz)")

    for idx, art in enumerate(pending, 1):
        print(f"  [{idx}/{len(pending)}] Analiz ediliyor: {art['title'][:60]}...")
        try:
            # Fetch full text for this single article
            full_text = fetch_single_article(art["link"], fallback_summary=art.get("title", ""))
            art["raw_content"] = full_text

            # Model 2 analyzes this single article
            analysis_result = crew.analyze_article(art)

            # Save to SQLite
            update_analyzed_article(
                article_id=art["id"],
                raw_content=full_text,
                category=analysis_result["category"],
                summary_en=analysis_result["summary_en"],
                pilot_takeaway_en=analysis_result["pilot_takeaway_en"],
                db_path="news.db",
            )
            print(f"        ✓ Kategori: {analysis_result['category']}")
        except Exception as e:
            print(f"        [!] Hata oluştu: {e}")
            mark_article_failed(art["id"], str(e), db_path="news.db")

    # ---------------------------------------------------------
    # STAGE 3: One-by-One Turkish Translation (Aviation Translator)
    # ---------------------------------------------------------
    untranslated = get_untranslated_articles(limit=args.process_limit, db_path="news.db")
    print(f"\n[Aşama 3/3] 🇹🇷 Türkçe havacılık çevirisi yapılıyor ({len(untranslated)} adet işlenecek)...")

    for idx, art in enumerate(untranslated, 1):
        print(f"  [{idx}/{len(untranslated)}] Çevriliyor: {art['title'][:60]}...")
        try:
            trans_result = crew.translate_article(art)

            update_translated_article(
                article_id=art["id"],
                title_tr=trans_result["title_tr"],
                summary_tr=trans_result["summary_tr"],
                pilot_takeaway_tr=trans_result["pilot_takeaway_tr"],
                db_path="news.db",
            )
            print(f"        ✓ Türkçe Başlık: {trans_result['title_tr'][:50]}...")
        except Exception as e:
            print(f"        [!] Çeviri hatası: {e}")
            mark_article_failed(art["id"], f"Translation error: {e}", db_path="news.db")

    # ---------------------------------------------------------
    # STAGE 4: Compile Final Markdown Digests
    # ---------------------------------------------------------
    translated_articles = get_latest_translated_articles(limit=25, db_path="news.db")
    if translated_articles:
        tr_path, en_path = compile_markdown_digests(translated_articles)
        print("\n==================================================")
        print(" 🎯 BÜLTENLER BAŞARIYLA DERLENDİ!")
        print("==================================================")
        print(f"[+] Türkçe Bülten: {tr_path.resolve()}")
        print(f"[+] İngilizce Bülten: {en_path.resolve()}")
        print(f"[+] SQLite Veritabanı: {Path('news.db').resolve()}")
        print(f"[+] Toplam Durum: {get_stats('news.db')}")
    else:
        print("\n[i] Henüz çevrilmiş makale bulunmuyor. Bir sonraki çalıştırmada bülten derlenecektir.")


if __name__ == "__main__":
    run()
