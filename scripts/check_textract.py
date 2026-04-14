"""Script: check_textract.py

Verify Amazon Textract access for OCR on scanned documents/images.

Tests:
  1. Textract client creation
  2. DetectDocumentText on a simple test image
  3. Response parsing — extract detected text lines

Textract is used for extracting text from scanned PDFs and images
that pdfplumber/openpyxl can't handle (OCR fallback).

NOTE: Textract requires an actual document/image to test. This script
creates a minimal PNG test image in memory. If you have a real scanned
document in S3, use --s3-key to test against it.

Usage:
    uv run python scripts/check_textract.py
    uv run python scripts/check_textract.py --s3-key "attachments/VQ-2026-0001/scan.png"
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
import zlib

# Add src/ to Python path so imports work when run directly
sys.path.insert(0, ".")
sys.path.insert(0, "src")

import boto3  # noqa: E402
from botocore.exceptions import ClientError, NoCredentialsError  # noqa: E402

from config.settings import get_settings  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402


def print_header(text: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


def print_check(name: str, passed: bool, detail: str = "") -> None:
    """Print a check result."""
    status = "[PASS]" if passed else "[FAIL]"
    suffix = f" — {detail}" if detail else ""
    print(f"  {status} {name}{suffix}")


def _create_minimal_png() -> bytes:
    """Create a minimal 1x1 white PNG in memory (no Pillow dependency).

    This is just enough to verify the Textract API accepts our call.
    Textract may return empty text (1px image has nothing to read)
    but the API call succeeding proves access works.
    """
    # 1x1 white pixel PNG (manually constructed)
    # IHDR: width=1, height=1, bit_depth=8, color_type=2 (RGB)
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
    ihdr_chunk = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)

    # IDAT: single row, filter byte 0, then RGB white (255, 255, 255)
    raw_data = b"\x00\xff\xff\xff"
    compressed = zlib.compress(raw_data)
    idat_crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
    idat_chunk = (
        struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)
    )

    # IEND
    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend_chunk = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)

    # PNG signature + chunks
    png_signature = b"\x89PNG\r\n\x1a\n"
    return png_signature + ihdr_chunk + idat_chunk + iend_chunk


def check_textract(s3_key: str | None = None) -> None:
    """Run all Textract access checks."""
    LoggingSetup.configure()
    settings = get_settings()

    print_header("VQMS — Amazon Textract Check")
    print(f"  Region: {settings.aws_region}")
    if s3_key:
        print(f"  S3 Key: {s3_key}")
        print(f"  Bucket: {settings.s3_bucket_data_store}")
    else:
        print("  Mode:   In-memory test image (1x1 PNG)")
    print()

    # --- Check 1: Create Textract client ---
    try:
        client = boto3.client("textract", region_name=settings.aws_region)
        print_check("Textract client", True)
    except NoCredentialsError:
        print_check("Textract client", False, "No AWS credentials found")
        return
    except Exception as e:
        print_check("Textract client", False, str(e))
        return

    # --- Check 2: Call DetectDocumentText ---
    try:
        if s3_key:
            # Use document from S3
            document = {
                "S3Object": {
                    "Bucket": settings.s3_bucket_data_store,
                    "Name": s3_key,
                }
            }
            print("  Calling DetectDocumentText on S3 object...")
        else:
            # Use minimal in-memory PNG
            png_bytes = _create_minimal_png()
            document = {"Bytes": png_bytes}
            print(f"  Calling DetectDocumentText on in-memory PNG ({len(png_bytes)} bytes)...")

        start = time.perf_counter()
        response = client.detect_document_text(Document=document)
        elapsed = (time.perf_counter() - start) * 1000

        # Parse response
        blocks = response.get("Blocks", [])
        line_blocks = [b for b in blocks if b.get("BlockType") == "LINE"]
        word_blocks = [b for b in blocks if b.get("BlockType") == "WORD"]
        page_blocks = [b for b in blocks if b.get("BlockType") == "PAGE"]

        print_check(
            "DetectDocumentText",
            True,
            f"{elapsed:.0f}ms",
        )
        print(f"          Pages:  {len(page_blocks)}")
        print(f"          Lines:  {len(line_blocks)}")
        print(f"          Words:  {len(word_blocks)}")

        # Show detected text lines (if any)
        if line_blocks:
            print("\n  Detected text:")
            for i, block in enumerate(line_blocks[:10], 1):
                text = block.get("Text", "")
                confidence = block.get("Confidence", 0)
                print(f"    [{i}] \"{text}\" (confidence: {confidence:.1f}%)")
            if len(line_blocks) > 10:
                print(f"    ... and {len(line_blocks) - 10} more lines")
        else:
            print("\n  No text detected (expected for a 1x1 test image)")
            if not s3_key:
                print("  Use --s3-key with a real document to test OCR extraction")

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "AccessDeniedException":
            print_check(
                "DetectDocumentText",
                False,
                "Access denied — check IAM permissions for textract:DetectDocumentText",
            )
        elif code == "UnsupportedDocumentException":
            print_check(
                "DetectDocumentText",
                False,
                "Unsupported document format",
            )
        elif code == "InvalidS3ObjectException":
            print_check(
                "DetectDocumentText",
                False,
                f"S3 object not found: {s3_key}",
            )
        else:
            print_check("DetectDocumentText", False, f"{code}: {e.response['Error']['Message']}")
    except Exception as e:
        print_check("DetectDocumentText", False, str(e))

    print(f"\n{'=' * 60}\n")


def main() -> None:
    """Parse args and run."""
    parser = argparse.ArgumentParser(description="Check Amazon Textract access")
    parser.add_argument(
        "--s3-key",
        type=str,
        default=None,
        help="S3 key of a document to test (e.g., 'attachments/VQ-2026-0001/scan.png')",
    )
    args = parser.parse_args()

    check_textract(s3_key=args.s3_key)


if __name__ == "__main__":
    main()
