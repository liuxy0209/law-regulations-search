<#!
Creates an atomic GitHub commit through the authenticated `gh` API when normal Git
HTTPS is unavailable.  The script only publishes the listed reviewed files and
uses the current remote main tip as the commit parent; it never force-updates main.
#>
[CmdletBinding()]
param(
    [string]$Repository = 'liuxy0209/law-regulations-search'
)

$ErrorActionPreference = 'Stop'
$files = @(
    'index.html',
    'law_db.js',
    'law-review-catalog.js',
    'national-law-official-refresh.json',
    'tools/refresh-curated-national-laws.py',
    'tools/tidy-official-preambles.py',
    'tools/add-contract-interpretation.ps1',
    'tools/repair-article-suffixes.js',
    'tools/publish-curated-national-refresh.ps1'
)

function Invoke-GitHubJson([string]$Method, [string]$Endpoint, $Body) {
    $json = $Body | ConvertTo-Json -Depth 8 -Compress
    return ($json | gh api --method $Method $Endpoint --input - | ConvertFrom-Json)
}

function New-GitBlob([string]$RelativePath) {
    $bytes = [System.IO.File]::ReadAllBytes((Join-Path $PSScriptRoot '..' $RelativePath))
    $body = @{ content = [Convert]::ToBase64String($bytes); encoding = 'base64' }
    return (Invoke-GitHubJson 'POST' "repos/$Repository/git/blobs" $body).sha
}

$remoteRef = gh api "repos/$Repository/git/ref/heads/main" | ConvertFrom-Json
$parentSha = $remoteRef.object.sha
$parentCommit = gh api "repos/$Repository/git/commits/$parentSha" | ConvertFrom-Json
$items = foreach ($file in $files) {
    Write-Host "上传 blob：$file"
    @{ path = $file; mode = '100644'; type = 'blob'; sha = New-GitBlob $file }
}
$tree = Invoke-GitHubJson 'POST' "repos/$Repository/git/trees" @{ base_tree = $parentCommit.tree.sha; tree = @($items) }
$commit = Invoke-GitHubJson 'POST' "repos/$Repository/git/commits" @{
    message = 'fix: clarify provision counts and prioritize default browsing'
    tree = $tree.sha
    parents = @($parentSha)
}
$updated = Invoke-GitHubJson 'PATCH' "repos/$Repository/git/refs/heads/main" @{ sha = $commit.sha; force = $false }
Write-Host "已发布提交：$($updated.object.sha)"
