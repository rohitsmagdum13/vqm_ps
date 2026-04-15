# ruff: noqa: E402
"""Script: seed_knowledge_base.py

Embed and load KB articles into PostgreSQL pgvector (memory.embedding_index).

Reads the 12 JSON articles from data/knowledge_base/, generates embeddings
via the LLM Gateway (Bedrock primary, OpenAI fallback), and inserts them
into the memory.embedding_index table.

The embedding_index table schema (from migration 006):
    article_id  VARCHAR(50)
    chunk_id    VARCHAR(50)    -- NULL for single-chunk articles
    title       TEXT
    content_text TEXT
    category    VARCHAR(100)
    source_url  VARCHAR(512)
    embedding   vector(1024)   -- Titan Embed v2 or OpenAI text-embedding-3-small
    metadata    JSONB

Usage:
    uv run python scripts/seed_knowledge_base.py
    uv run python scripts/seed_knowledge_base.py --clear   # Delete existing rows first

Prerequisites:
    1. .env configured with PostgreSQL and Bedrock/OpenAI credentials
    2. Migration 006 has been run (memory.embedding_index table exists)
    3. pgvector extension enabled (migration 002)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from dotenv import load_dotenv

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
from config.settings import get_settings
from adapters.llm_gateway import LLMGateway
from db.connection import PostgresConnector
from utils.logger import LoggingSetup

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LoggingSetup.configure()
logger = logging.getLogger("scripts.seed_knowledge_base")

for _noisy in ("botocore", "urllib3", "msal", "httpx", "httpcore",
               "openai._base_client"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KB_DIR = Path("data/knowledge_base")
DIVIDER = "=" * 70
SUBDIV = "-" * 60


def banner(text: str) -> None:
    """Print a section banner."""
    print(f"\n{DIVIDER}")
    print(f"  {text}")
    print(DIVIDER)


def result(label: str, value: str, indent: int = 4) -> None:
    """Print a key-value result line."""
    safe_value = value.encode("ascii", errors="replace").decode("ascii")
    print(f"{' ' * indent}{label}: {safe_value}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def seed_kb(*, clear: bool) -> None:
    """Load KB articles, embed them, and insert into pgvector."""
    settings = get_settings()
    postgres: PostgresConnector | None = None

    try:
        banner("VQMS Knowledge Base Seeder")
        result("KB Directory", str(KB_DIR), indent=2)
        result("Embedding Provider", settings.embedding_provider, indent=2)
        result("Embedding Dimensions", str(settings.bedrock_embedding_dimensions), indent=2)

        # --- Initialize connectors ---
        print(f"\n{SUBDIV}")
        print("  Initializing connectors...")
        print(SUBDIV)

        postgres = PostgresConnector(settings)
        await postgres.connect()
        result("PostgreSQL", "[OK]")

        llm_gateway = LLMGateway(settings)
        result("LLM Gateway", f"[OK] (mode: {settings.embedding_provider})")

        # --- Clear existing rows if requested ---
        if clear:
            print(f"\n{SUBDIV}")
            print("  Clearing existing embedding_index rows...")
            print(SUBDIV)
            await postgres.execute("DELETE FROM memory.embedding_index")
            result("Cleared", "All rows deleted from memory.embedding_index")

        # --- Load KB articles ---
        print(f"\n{SUBDIV}")
        print("  Loading KB articles from disk...")
        print(SUBDIV)

        kb_files = sorted(KB_DIR.glob("KB-*.json"))
        if not kb_files:
            print("    [ERROR] No KB-*.json files found in data/knowledge_base/")
            return

        articles = []
        for kb_file in kb_files:
            with open(kb_file, encoding="utf-8") as f:
                article = json.load(f)
            articles.append(article)
            result(article["article_id"], f"{article['title'][:60]}...")

        print(f"\n    Loaded {len(articles)} articles.")

        # --- Check for existing articles ---
        existing_rows = await postgres.fetch(
            "SELECT article_id FROM memory.embedding_index"
        )
        existing_ids = {row["article_id"] for row in existing_rows}

        if existing_ids:
            print(f"\n    Found {len(existing_ids)} existing articles in DB: {', '.join(sorted(existing_ids))}")

        # --- Embed and insert each article ---
        banner("Embedding and Inserting Articles")

        inserted = 0
        skipped = 0
        failed = 0
        total_embed_ms = 0

        for article in articles:
            article_id = article["article_id"]
            title = article["title"]
            content = article["content"]
            category = article.get("category", "")
            source_url = article.get("source_url", "")
            query_type = article.get("query_type", "")
            tags = article.get("tags", [])

            # Skip if already exists (unless --clear was used)
            if article_id in existing_ids:
                result(article_id, "[SKIP] Already exists", indent=2)
                skipped += 1
                continue

            # Build the text to embed: title + content for maximum context
            embed_text = f"{title}\n\n{content}"

            # Generate embedding
            embed_start = time.perf_counter()
            try:
                embedding = await llm_gateway.llm_embed(
                    text=embed_text,
                    correlation_id=f"kb-seed-{article_id}",
                )
            except Exception as exc:
                result(article_id, f"[FAIL] Embedding failed: {exc}", indent=2)
                failed += 1
                continue

            embed_ms = int((time.perf_counter() - embed_start) * 1000)
            total_embed_ms += embed_ms

            # Validate embedding dimensions match the DB column
            expected_dims = settings.bedrock_embedding_dimensions
            if len(embedding) != expected_dims:
                result(
                    article_id,
                    f"[FAIL] Dimension mismatch: got {len(embedding)}, "
                    f"expected {expected_dims}",
                    indent=2,
                )
                failed += 1
                continue

            # Convert embedding to pgvector string format
            embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

            # Build metadata JSONB
            metadata = json.dumps({
                "query_type": query_type,
                "tags": tags,
                "last_updated": article.get("last_updated", ""),
            })

            # Insert into memory.embedding_index
            try:
                await postgres.execute(
                    "INSERT INTO memory.embedding_index "
                    "(article_id, title, content_text, category, source_url, "
                    "embedding, metadata) "
                    "VALUES ($1, $2, $3, $4, $5, $6::vector, $7::jsonb)",
                    article_id,
                    title,
                    content,
                    category,
                    source_url,
                    embedding_str,
                    metadata,
                )
                inserted += 1
                result(
                    article_id,
                    f"[OK] {title[:50]}... ({embed_ms}ms, {len(embedding)} dims)",
                    indent=2,
                )
            except Exception as exc:
                result(article_id, f"[FAIL] DB insert failed: {exc}", indent=2)
                failed += 1

        # --- Summary ---
        banner("SEED COMPLETE")
        result("Inserted", str(inserted), indent=2)
        result("Skipped (existing)", str(skipped), indent=2)
        result("Failed", str(failed), indent=2)
        result("Total articles", str(len(articles)), indent=2)
        if inserted > 0:
            result("Avg embed time", f"{total_embed_ms // max(inserted, 1)}ms", indent=2)

        # Verify final count
        count_row = await postgres.fetchrow(
            "SELECT COUNT(*) AS cnt FROM memory.embedding_index"
        )
        total_in_db = count_row["cnt"] if count_row else 0
        result("Total in DB", str(total_in_db), indent=2)

    except Exception:
        logger.exception("KB seed failed")
        print("\n    [FAIL] Seed failed -- check logs above for details")
        raise
    finally:
        if postgres:
            await postgres.disconnect()
        print("\n    Connectors closed.\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI args and run the KB seeder."""
    parser = argparse.ArgumentParser(
        description="VQMS: Embed KB articles and load into pgvector (memory.embedding_index)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete all existing rows from memory.embedding_index before seeding.",
    )
    args = parser.parse_args()

    asyncio.run(seed_kb(clear=args.clear))


if __name__ == "__main__":
    main()
