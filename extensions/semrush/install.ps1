# Claude SEO - Semrush extension installer (Windows)
#
# Copies the seo-semrush mirror skill into ~/.claude/skills/ and the
# seo-semrush agent into ~/.claude/agents/. The Semrush MCP is a remote
# server (https://mcp.semrush.com/v1/mcp) connected via `claude mcp add`,
# so this installer does NOT write credentials.
$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "|   Claude SEO - Semrush extension     |" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$SkillDir = "$env:USERPROFILE\.claude\skills"
$AgentDir = "$env:USERPROFILE\.claude\agents"

if (-not (Test-Path "$SkillDir\seo")) {
    Write-Host "[x] claude-seo base plugin not installed. Install it first." -ForegroundColor Red
    exit 1
}

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path

New-Item -ItemType Directory -Force -Path "$SkillDir\seo-semrush" | Out-Null
Copy-Item -Force "$SourceDir\skills\seo-semrush\SKILL.md" "$SkillDir\seo-semrush\SKILL.md"
Write-Host "[+] Installed skill: $SkillDir\seo-semrush\SKILL.md" -ForegroundColor Green

New-Item -ItemType Directory -Force -Path $AgentDir | Out-Null
$AgentSrc = Join-Path $SourceDir "..\..\agents\seo-semrush.md"
if (Test-Path $AgentSrc) {
    Copy-Item -Force $AgentSrc "$AgentDir\seo-semrush.md"
    Write-Host "[+] Installed agent: $AgentDir\seo-semrush.md" -ForegroundColor Green
}

Write-Host ""
Write-Host "Connect the Semrush MCP (once, if not already connected):" -ForegroundColor Cyan
Write-Host "  claude mcp add --transport http semrush https://mcp.semrush.com/v1/mcp"
Write-Host "  (then authenticate per Semrush's MCP docs)"
Write-Host ""
Write-Host "Done. Open a new Claude Code session and run:" -ForegroundColor Cyan
Write-Host "  /seo semrush overview example.com"
Write-Host ""
Write-Host "Full docs: extensions\semrush\docs\SEMRUSH-SETUP.md" -ForegroundColor Gray
