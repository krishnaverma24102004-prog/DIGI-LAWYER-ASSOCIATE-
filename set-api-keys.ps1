# Saves the service API keys into .env: eCourtsIndia, Tavily, Indian Kanoon, Twilio.
# (Supabase: set-keys.ps1 -SupabaseOnly. WhatsApp and Anthropic: later.)
# Run from the project folder:  powershell -ExecutionPolicy Bypass -File .\set-api-keys.ps1
# Press Enter on any prompt to skip it and keep the current value. Keys are typed hidden.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $root ".env"
$utf8 = New-Object System.Text.UTF8Encoding($false)
if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $root ".env.example") $envFile }

function Ask($label, [switch]$Secret) {
    if ($Secret) {
        $secure = Read-Host "$label (hidden, Enter to skip)" -AsSecureString
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr).Trim() }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    }
    return (Read-Host "$label (Enter to skip)").Trim()
}

function Set-Value($name, $value) {
    $lines = [IO.File]::ReadAllLines($envFile, $utf8)
    $found = $false
    $lines = foreach ($line in $lines) {
        if ($line -match "^$name=") { $found = $true; "$name=$value" } else { $line }
    }
    if (-not $found) { $lines += "$name=$value" }
    [IO.File]::WriteAllLines($envFile, [string[]]$lines, $utf8)
}

function Set-IfGiven($name, $value) { if ($value) { Set-Value $name $value } }

Write-Host "`neCourtsIndia (case status and hearing dates by CNR)" -ForegroundColor Cyan
Set-IfGiven "ECOURTS_API_KEY" (Ask "eCourtsIndia API key (eci_live_...)" -Secret)

Write-Host "`nTavily (live web legal research)" -ForegroundColor Cyan
Set-IfGiven "TAVILY_API_KEY" (Ask "Tavily API key (tvly-...)" -Secret)

Write-Host "`nIndian Kanoon (case-law search)" -ForegroundColor Cyan
Set-IfGiven "INDIANKANOON_API_TOKEN" (Ask "Indian Kanoon API token" -Secret)

Write-Host "`nTwilio (phone intake)" -ForegroundColor Cyan
Set-IfGiven "TWILIO_AUTH_TOKEN" (Ask "Twilio Auth Token (Console -> Account Info)" -Secret)
Set-IfGiven "PUBLIC_BASE_URL" (Ask "Public https address of this API, e.g. your ngrok URL")

Write-Host "`nSaved. Keys that are set (values not shown):" -ForegroundColor Green
foreach ($line in [IO.File]::ReadAllLines($envFile, $utf8)) {
    if ($line -match "^(ECOURTS_API_KEY|TAVILY_API_KEY|INDIANKANOON_API_TOKEN|TWILIO_AUTH_TOKEN|PUBLIC_BASE_URL)=(.*)$") {
        $state = if ($Matches[2]) { "set" } else { "EMPTY" }
        Write-Host ("  {0,-24} {1}" -f $Matches[1], $state)
    }
}
Write-Host "`nRestart the API (and the worker) so the new keys are used."
