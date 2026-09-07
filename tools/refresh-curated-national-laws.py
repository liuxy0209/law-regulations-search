#!/usr/bin/env python3
"""以国家法律法规数据库的正式 DOCX 文本重建精选国家法规库。

运行前提：可访问 https://flk.npc.gov.cn 。脚本先为所有入选法规取得“有效”
官方记录及下载文本；任一项失败时不会改写 law_db.js，避免半成品覆盖网站数据。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

from docx import Document


ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = ROOT / "law_db.js"
REPORT_PATH = ROOT / "national-law-official-refresh.json"
SEARCH_URL = "https://flk.npc.gov.cn/law-search/search/list"
DETAIL_URL = "https://flk.npc.gov.cn/law-search/search/flfgDetails?bbbs={}"
DOWNLOAD_URL = "https://flk.npc.gov.cn/law-search/download/pc?format=docx&bbbs={}&fileId="
VERIFIED_AT = date.today().isoformat()

# 面向采购供应链管理中心的精选库：基础大法 + 采购交易、合同、数据、
# 财税国资、质量安全生态、劳动用工和知识产权直接相关规范。
CURATED = {
    "基础法律": [
        "中华人民共和国宪法", "中华人民共和国刑法", "中华人民共和国民法典",
        "中华人民共和国刑事诉讼法", "中华人民共和国民事诉讼法", "中华人民共和国行政诉讼法",
        "中华人民共和国行政处罚法", "中华人民共和国行政复议法", "中华人民共和国行政强制法",
        "中华人民共和国行政许可法",
    ],
    "采购与市场交易": [
        "中华人民共和国招标投标法", "中华人民共和国招标投标法实施条例",
        "中华人民共和国政府采购法", "中华人民共和国政府采购法实施条例",
        "保障中小企业款项支付条例", "中华人民共和国价格法",
        "中华人民共和国反垄断法", "中华人民共和国反不正当竞争法", "中华人民共和国电子商务法",
        "中华人民共和国消费者权益保护法", "中华人民共和国拍卖法",
    ],
    "合同与市场主体": [
        "中华人民共和国公司法", "中华人民共和国企业破产法", "中华人民共和国合伙企业法",
        "中华人民共和国个人独资企业法", "中华人民共和国民营经济促进法",
    ],
    "财税、国资与审计": [
        "中华人民共和国企业所得税法", "中华人民共和国个人所得税法", "中华人民共和国增值税法",
        "中华人民共和国会计法", "中华人民共和国审计法", "中华人民共和国企业国有资产法",
        "中华人民共和国发票管理办法",
    ],
    "数据、网络与保密": [
        "中华人民共和国网络安全法", "中华人民共和国数据安全法", "中华人民共和国个人信息保护法",
        "中华人民共和国电子签名法", "中华人民共和国保守国家秘密法", "中华人民共和国档案法",
    ],
    "质量、安全与生态": [
        "中华人民共和国产品质量法", "中华人民共和国标准化法", "中华人民共和国计量法",
        "中华人民共和国食品安全法", "中华人民共和国药品管理法", "中华人民共和国安全生产法",
        "中华人民共和国消防法", "中华人民共和国突发事件应对法", "中华人民共和国生态环境法典",
        "中华人民共和国循环经济促进法",
    ],
    "劳动用工": [
        "中华人民共和国劳动法", "中华人民共和国劳动合同法", "中华人民共和国社会保险法",
    ],
    "知识产权": [
        "中华人民共和国专利法", "中华人民共和国商标法", "中华人民共和国著作权法",
    ],
}

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=utf-8",
    "Referer": "https://flk.npc.gov.cn/search",
    "Origin": "https://flk.npc.gov.cn",
    "User-Agent": "Mozilla/5.0 (official-text-refresh; public-law-reference)",
}
ARTICLE_RE = re.compile(r"^(第[一二三四五六七八九十百千万零〇\d]+条)(.*)$")
PART_RE = re.compile(r"^第[一二三四五六七八九十百千万零〇\d]+编(?:\s|　|$)")
CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百千万零〇\d]+章(?:\s|　|$)")
SECTION_RE = re.compile(r"^第[一二三四五六七八九十百千万零〇\d]+节(?:\s|　|$)")


def compact(value: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", value or ""))


def matches_title(local_title: str, official_title: str) -> bool:
    official = re.sub(r"（[^）]*）", "", compact(official_title))
    local = compact(local_title)
    return local == official or (local == "中华人民共和国宪法" and official.startswith(local))


def status_name(code) -> str:
    return {1: "已废止", 2: "已修改", 3: "有效", 4: "尚未生效"}.get(code, f"待确认（状态码 {code}）")


def request_json(url: str, payload=None) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=HEADERS, method="POST" if data else "GET")
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:  # 公开站点偶有短暂验签失败，有限重试即可。
            last_error = error
            if attempt < 2:
                time.sleep(1.1 * (attempt + 1))
    raise RuntimeError(f"请求失败：{url}：{last_error}")


def download_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"], "Referer": "https://flk.npc.gov.cn/"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def official_row(title: str) -> dict:
    payload = {
        "searchContent": re.sub(r"^中华人民共和国", "", title),
        "searchRange": 1, "searchType": 1, "sxrq": [], "gbrq": [], "sxx": [],
        "pageNum": 1, "pageSize": 100,
    }
    result = request_json(SEARCH_URL, payload)
    candidates = [row for row in result.get("rows", []) if matches_title(title, row.get("title", ""))]
    current = [row for row in candidates if row.get("sxx") == 3]
    if not current:
        states = ", ".join(f"{row.get('title')}（{status_name(row.get('sxx'))}）" for row in candidates)
        raise RuntimeError(f"未找到有效的官方同名记录：{title}" + (f"；候选：{states}" if states else ""))
    return sorted(current, key=lambda row: (row.get("gbrq") or "", row.get("bbbs") or ""), reverse=True)[0]


def official_docx(row: dict) -> bytes:
    # 详情接口也用于核验官方记录存在；下载接口返回带时效签名的正式文件地址。
    detail = request_json(DETAIL_URL.format(urllib.parse.quote(str(row["bbbs"]))))
    if detail.get("code") not in (0, 200) and not detail.get("data"):
        raise RuntimeError(f"官方详情返回异常：{detail.get('msg') or detail.get('code')}")
    download = request_json(DOWNLOAD_URL.format(urllib.parse.quote(str(row["bbbs"]))))
    url = (download.get("data") or {}).get("url")
    if not url:
        raise RuntimeError(f"官方 DOCX 下载地址缺失：{download.get('msg') or download.get('code')}")
    content = download_bytes(url)
    if not content.startswith(b"PK"):
        raise RuntimeError("下载内容不是 DOCX 文件")
    return content


def clean_paragraph(text: str) -> str:
    # 仅消除 Word 排版空白；不改动正文用字，也不按行重排正文。
    text = (text or "").replace("\xa0", " ").replace("\u3000", "　").strip()
    return re.sub(r"[ \t]+", " ", text)


def extract_paragraphs(content: bytes) -> list[str]:
    document = Document(io.BytesIO(content))
    paragraphs = [clean_paragraph(paragraph.text) for paragraph in document.paragraphs]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    if not paragraphs:
        raise RuntimeError("正式 DOCX 中未提取到段落")
    return paragraphs


def heading_kind(text: str) -> str | None:
    if PART_RE.match(text): return "part"
    if CHAPTER_RE.match(text): return "chapter"
    if SECTION_RE.match(text): return "section"
    if text in ("附则", "附　则"): return "appendix"
    return None


def make_articles(paragraphs: list[str]) -> list[dict]:
    preamble: list[str] = []
    articles: list[dict] = []
    current: dict | None = None
    hierarchy: dict[str, str] = {"part": "", "chapter": "", "section": ""}

    def current_heading() -> str | None:
        values = [hierarchy[k] for k in ("part", "chapter", "section") if hierarchy[k]]
        return " · ".join(values) if values else None

    def finish_current():
        nonlocal current
        if current is None:
            return
        current["content"] = "\n\n".join(current.pop("paragraphs")).strip()
        if current["content"]:
            articles.append(current)
        current = None

    for paragraph in paragraphs:
        kind = heading_kind(paragraph)
        if kind:
            finish_current()
            if kind == "part":
                hierarchy = {"part": paragraph, "chapter": "", "section": ""}
            elif kind == "chapter":
                hierarchy["chapter"], hierarchy["section"] = paragraph, ""
            elif kind == "section":
                hierarchy["section"] = paragraph
            else:
                hierarchy = {"part": "", "chapter": paragraph, "section": ""}
            continue
        match = ARTICLE_RE.match(paragraph)
        if match:
            finish_current()
            title, opening = match.groups()
            current = {
                "number": title, "article_title": title, "chapter": current_heading(),
                "structure_type": "article", "paragraphs": [opening.strip()] if opening.strip() else [],
            }
        elif current is None:
            preamble.append(paragraph)
        else:
            current["paragraphs"].append(paragraph)
    finish_current()
    if not articles:
        raise RuntimeError("未能识别正式文本中的“第…条”结构")
    if preamble:
        articles.insert(0, {
            "number": "题注", "article_title": "题注", "chapter": None,
            "structure_type": "preamble", "content": "\n\n".join(preamble),
        })
    for index, article in enumerate(articles, 1):
        article["article_id"] = f"a{index:04d}"
    return articles


def load_database() -> list[dict]:
    source = DATABASE_PATH.read_text(encoding="utf-8")
    match = re.search(r"(?:const|var|let)\s+LAW_DATABASE\s*=\s*(\[.*\])\s*;?\s*$", source, re.S)
    if not match:
        raise RuntimeError("无法解析 law_db.js")
    return json.loads(match.group(1))


def build_record(title: str, category: str, row: dict, paragraphs: list[str]) -> dict:
    articles = make_articles(paragraphs)
    full_text = "\n\n".join(paragraphs)
    type_name = row.get("flxz") or "法律"
    source = "国家行政法规" if type_name == "行政法规" else "国家法律"
    record_id = row["bbbs"]
    return {
        "title": title,
        "type": type_name,
        "sub_category": category,
        "year": (row.get("gbrq") or "")[:4] or "未标注",
        "source": source,
        "full_text": full_text,
        "articles": articles,
        "document_id": f"NAT-{record_id}",
        "legal_document_type": type_name,
        "issuer": row.get("zdjgName") or "未标注",
        "document_number": None,
        "publication_date": row.get("gbrq") or None,
        "effective_date": row.get("sxrq") or None,
        "validity_status": "有效",
        "official_source": "国家法律法规数据库",
        "official_source_url": "https://flk.npc.gov.cn/detail2.html?" + base64.b64encode(record_id.encode()).decode(),
        "version_label": "国家法律法规数据库正式 DOCX 文本",
        "text_sha256": hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
        "verification_status": "official_text_verified",
        "verification_scope": "official-electronic-text",
        "verified_at": VERIFIED_AT,
        "quality_flags": [],
        "quality_review_status": "official_text_verified",
        "source_folder": "国家法律法规数据库（精选）",
        "source_filename": None,
        "source_sha256": None,
        "official_record_id": record_id,
        "official_status_code": row.get("sxx"),
    }


def main():
    existing = load_database()
    national_sources = {"国家法律", "国家行政法规"}
    retained: list[dict] = []
    official_rows: list[dict] = []
    failures: list[str] = []
    total = sum(len(items) for items in CURATED.values())
    position = 0

    for category, titles in CURATED.items():
        for title in titles:
            position += 1
            try:
                row = official_row(title)
                # 公开接口按序访问，避免对官方库造成不必要压力。
                time.sleep(0.35)
                paragraphs = extract_paragraphs(official_docx(row))
                retained.append(build_record(title, category, row, paragraphs))
                official_rows.append({
                    "title": title, "category": category, "official_record_id": row["bbbs"],
                    "official_title": row.get("title"), "document_type": row.get("flxz"),
                    "publication_date": row.get("gbrq"), "effective_date": row.get("sxrq"),
                    "article_count": len(retained[-1]["articles"]),
                })
                print(f"[{position}/{total}] 已核对：{title}")
            except Exception as error:
                failures.append(f"{title}：{error}")
                print(f"[{position}/{total}] 失败：{failures[-1]}")
            time.sleep(0.45)

    if failures:
        raise RuntimeError("以下文件未完成，已停止写入以保护现有数据库：\n" + "\n".join(failures))

    non_national = [record for record in existing if record.get("source") not in national_sources]
    all_records = retained + non_national
    output = (
        "// 法律法规数据库（国家精选库已按国家法律法规数据库正式文本核对）\n"
        f"// 更新日期：{VERIFIED_AT}；国家精选法规：{len(retained)} 部；总文件：{len(all_records)} 份\n\n"
        "const LAW_DATABASE = " + json.dumps(all_records, ensure_ascii=False, indent=2) + ";\n"
    )
    DATABASE_PATH.write_text(output, encoding="utf-8")
    removed = [record.get("title") for record in existing if record.get("source") in national_sources and record.get("title") not in {item["title"] for item in retained}]
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "official_source": "国家法律法规数据库",
        "official_source_home": "https://flk.npc.gov.cn/",
        "scope": "采购供应链管理中心精选国家法规库",
        "total_retained": len(retained),
        "total_non_national_preserved": len(non_national),
        "removed_from_previous_national_selection": removed,
        "records": official_rows,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"完成：已用正式文本更新 {len(retained)} 部，保留其他来源 {len(non_national)} 份。")


if __name__ == "__main__":
    main()
