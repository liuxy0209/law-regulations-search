#!/usr/bin/env python3
"""仅清理正式文本展示时重复的标题、目录行；不改动任何法条正文。"""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "law_db.js"


def compact(value):
    return re.sub(r"[\s　]+", "", value or "")


def main():
    source = DB.read_text(encoding="utf-8")
    match = re.search(r"(?:const|var|let)\s+LAW_DATABASE\s*=\s*(\[.*\])\s*;?\s*$", source, re.S)
    if not match:
        raise RuntimeError("无法解析 law_db.js")
    records = json.loads(match.group(1))
    changed = 0
    for record in records:
        if record.get("verification_status") != "official_text_verified":
            continue
        preamble = next((article for article in record.get("articles", []) if article.get("structure_type") == "preamble"), None)
        if not preamble:
            continue
        kept, previous = [], None
        for paragraph in preamble.get("content", "").split("\n\n"):
            normalized = compact(paragraph)
            # 法律标题已显示在详情页标题；“目录”及其孤立的“附则”是 Word 目录字段残留。
            if normalized in {compact(record.get("title")), "目录", "附则"}:
                continue
            if paragraph == previous:
                continue
            kept.append(paragraph)
            previous = paragraph
        cleaned = "\n\n".join(kept).strip()
        if cleaned != preamble.get("content", ""):
            preamble["content"] = cleaned
            changed += 1
    output = source[:match.start(1)] + json.dumps(records, ensure_ascii=False, indent=2) + ";\n"
    DB.write_text(output, encoding="utf-8")
    print(f"已清理 {changed} 部正式法规的题注展示。")


if __name__ == "__main__":
    main()
