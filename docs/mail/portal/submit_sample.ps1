<#
.SYNOPSIS
  Submit a portal sample query end-to-end.

.DESCRIPTION
  Picks one of the 1-2 entries from a docs/mail/portal/*.json file,
  POSTs it to /queries with the right headers, and prints the
  returned query_id together with the local URL to watch the
  pipeline timeline live.

.PARAMETER File
  The JSON sample file to read (relative to the repo root, e.g.
  docs/mail/portal/01_invoice_payment.json).

.PARAMETER Index
  Which entry inside `samples[]` to submit. Defaults to 0.

.PARAMETER VendorId
  X-Vendor-ID header value. Defaults to V-001.

.PARAMETER ApiBase
  Backend base URL. Defaults to http://localhost:8000.

.PARAMETER FrontendBase
  Frontend base URL — printed for convenience. Defaults to http://localhost:4200.

.PARAMETER Token
  Bearer JWT. Falls back to $env:VQMS_TOKEN if not provided.

.EXAMPLE
  $env:VQMS_TOKEN = "<your-jwt>"
  .\docs\mail\portal\submit_sample.ps1 -File docs/mail/portal/01_invoice_payment.json -Index 0
#>

param(
  [Parameter(Mandatory = $true)] [string] $File,
  [int] $Index = 0,
  [string] $VendorId = "V-001",
  [string] $ApiBase = "http://localhost:8000",
  [string] $FrontendBase = "http://localhost:4200",
  [string] $Token = $env:VQMS_TOKEN
)

if (-not $Token) {
  Write-Error "No JWT supplied. Pass -Token or set `$env:VQMS_TOKEN."
  exit 1
}

if (-not (Test-Path $File)) {
  Write-Error "Sample file not found: $File"
  exit 1
}

$payload = (Get-Content $File -Raw | ConvertFrom-Json).samples[$Index]
if (-not $payload) {
  Write-Error "No samples[$Index] in $File."
  exit 1
}

Write-Host "Submitting: $($payload.label)" -ForegroundColor Cyan
Write-Host "Expected path: $($payload.expected_path)" -ForegroundColor DarkGray

$body = $payload.submission | ConvertTo-Json -Depth 6

try {
  $response = Invoke-RestMethod -Method Post -Uri "$ApiBase/queries" `
    -Headers @{
      Authorization  = "Bearer $Token"
      "X-Vendor-ID"  = $VendorId
    } `
    -ContentType "application/json" `
    -Body $body
} catch {
  Write-Error "POST /queries failed: $($_.Exception.Message)"
  if ($_.ErrorDetails.Message) {
    Write-Host $_.ErrorDetails.Message -ForegroundColor Yellow
  }
  exit 1
}

Write-Host ""
Write-Host "query_id: $($response.query_id)" -ForegroundColor Green
Write-Host "status:   $($response.status)" -ForegroundColor Green
Write-Host ""
Write-Host "Watch the timeline:" -ForegroundColor Cyan
Write-Host "  $FrontendBase/queries/$($response.query_id)"
