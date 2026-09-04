param(
    [string]$DatabasePath = (Join-Path $PSScriptRoot '..\\law_db.js')
)

$ErrorActionPreference = 'Stop'
$url = 'https://www.court.gov.cn/zixun/xiangqing/419382.html'
$documentId = 'JUD-SPC-2023-13'
$title = '最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释'
$source = '最高人民法院司法解释'

$existing = Get-Content -LiteralPath $DatabasePath -Raw -Encoding UTF8
if ($existing.Contains('"document_id": "' + $documentId + '"')) {
    throw "数据库已存在 $documentId；为避免重复收录，未作修改。"
}

$html = (Invoke-WebRequest -Uri $url -UseBasicParsing).Content
$start = $html.IndexOf('<div class="txt_txt" id="zoom">')
$lastArticle = $html.IndexOf('第六十九条', $start)
if ($start -lt 0 -or $lastArticle -lt 0) { throw '未能在最高人民法院页面中定位解释正文或第六十九条。' }
$end = $html.IndexOf('</p>', $lastArticle)
if ($end -lt 0) { throw '未能定位第六十九条所在段落的结束位置。' }
$body = $html.Substring($start, $end + 4 - $start)
$paragraphNodes = [regex]::Matches($body, '<p[^>]*>(?<text>[\s\S]*?)</p>', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)

function Convert-OfficialParagraph([string]$markup) {
    $text = $markup -replace '(?i)<br\s*/?>', "`n" -replace '<[^>]+>', ''
    $text = [System.Net.WebUtility]::HtmlDecode($text)
    return (($text -replace '[\u00A0\u3000]', ' ' -replace '\s+', ' ').Trim())
}

$preamble = [System.Collections.Generic.List[string]]::new()
$articles = [System.Collections.Generic.List[object]]::new()
$currentChapter = $null
$currentArticle = $null

foreach ($node in $paragraphNodes) {
    $line = Convert-OfficialParagraph $node.Groups['text'].Value
    if (-not $line) { continue }
    if ($line -match '^[一二三四五六七八九十]+、') {
        $currentChapter = $line
        continue
    }
    if ($line -match '^(第[一二三四五六七八九十百零〇]+条)\s*(.*)$') {
        if ($null -ne $currentArticle) { $articles.Add($currentArticle) }
        $currentArticle = [ordered]@{
            number = $Matches[1]
            article_title = $Matches[1]
            chapter = $currentChapter
            structure_type = 'article'
            content = $Matches[2].Trim()
        }
        continue
    }
    if ($null -eq $currentArticle) { $preamble.Add($line) }
    else { $currentArticle.content = (($currentArticle.content, $line | Where-Object { $_ }) -join "`n`n") }
}
if ($null -ne $currentArticle) { $articles.Add($currentArticle) }
if ($articles.Count -ne 69) { throw "官网正文解析得到 $($articles.Count) 条，预期为 69 条；未写入数据库。" }

$allArticles = [System.Collections.Generic.List[object]]::new()
$allArticles.Add([ordered]@{
    number = '题注'
    article_title = '题注'
    chapter = $null
    structure_type = 'preamble'
    content = ($preamble -join "`n`n")
    article_id = 'a0001'
})
for ($i = 0; $i -lt $articles.Count; $i++) {
    $article = $articles[$i]
    $article.article_id = 'a' + ($i + 2).ToString('D4')
    $allArticles.Add($article)
}

$fullTextParts = [System.Collections.Generic.List[string]]::new()
$fullTextParts.Add(($preamble -join "`n`n"))
$lastChapter = $null
foreach ($article in $allArticles | Select-Object -Skip 1) {
    if ($article.chapter -and $article.chapter -ne $lastChapter) { $fullTextParts.Add($article.chapter); $lastChapter = $article.chapter }
    $fullTextParts.Add($article.article_title + "`n" + $article.content)
}
$fullText = $fullTextParts -join "`n`n"
$sha = [System.Security.Cryptography.SHA256]::Create()
$textSha = ([System.BitConverter]::ToString($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($fullText)))).Replace('-', '').ToLowerInvariant()

$document = [ordered]@{
    title = $title
    type = '司法解释'
    sub_category = '合同与民事司法解释'
    year = '2023'
    source = $source
    full_text = $fullText
    articles = $allArticles
    document_id = $documentId
    legal_document_type = '司法解释'
    issuer = '最高人民法院'
    document_number = '法释〔2023〕13号'
    publication_date = '2023-12-04'
    effective_date = '2023-12-05'
    validity_status = '有效'
    official_source = '最高人民法院官网'
    official_source_url = $url
    version_label = '最高人民法院公布文本'
    text_sha256 = $textSha
    verification_status = 'official_text_verified'
    verification_scope = 'official-electronic-text'
    verified_at = '2026-09-04'
    quality_flags = @()
    quality_review_status = 'metadata_checked'
    source_folder = '官方公开来源'
    source_filename = '最高人民法院官网（2023-12-05）'
    source_sha256 = $textSha
    official_record_id = '419382'
    official_status_code = '现行有效'
}

$json = $document | ConvertTo-Json -Depth 12
$suffix = [regex]::Match($existing, '\r?\n\];\s*$')
if (-not $suffix.Success) { throw 'law_db.js 结尾格式不符合预期；未写入数据库。' }
$updated = $existing.Substring(0, $suffix.Index).TrimEnd() + ",`r`n" + $json + "`r`n];`r`n"
[System.IO.File]::WriteAllText($DatabasePath, $updated, [System.Text.UTF8Encoding]::new($false))
Write-Output "已收录：$title（$($articles.Count) 条 + 题注）。"
