# Saves your API keys into .env (backend) and frontend/.env.local (browser app).
# Run from the project folder:  powershell -ExecutionPolicy Bypass -File .\set-keys.ps1
# Press Enter on any prompt to keep the current value. Secret keys are typed hidden.
# Only the Supabase keys:  powershell -ExecutionPolicy Bypass -File .\set-keys.ps1 -SupabaseOnly

param([switch]$SupabaseOnly)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root ".env"
$frontend = Join-Path $root "frontend\.env.local"
$utf8 = New-Object System.Text.UTF8Encoding($false)

foreach ($pair in @(@($backend, ".env.example"), @($frontend, "frontend\.env.local.example"))) {
    if (-not (Test-Path $pair[0])) { Copy-Item (Join-Path $root $pair[1]) $pair[0] }
}

function Ask($label, [switch]$Secret) {
    if ($Secret) {
        $secure = Read-Host "$label (hidden)" -AsSecureString
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr).Trim() }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    }
    return (Read-Host $label).Trim()
}

function Set-Value($file, $name, $value) {
    if (-not $value) { return }
    $lines = [IO.File]::ReadAllLines($file, $utf8)
    $found = $false
    $lines = foreach ($line in $lines) {
        if ($line -match "^$name=") { $found = $true; "$name=$value" } else { $line }
    }
    if (-not $found) { $lines += "$name=$value" }
    [IO.File]::WriteAllLines($file, [string[]]$lines, $utf8)
}

Write-Host "`nSupabase: Project Settings -> API (and the Connect button for the database URI)" -ForegroundColor Cyan
$url = Ask "Project URL (https://xxxx.supabase.co)"
$anon = Ask "anon / publishable key"
$service = Ask "service_role / secret key" -Secret
$dbUrl = Ask "Session pooler URI, with your DB password filled in" -Secret

$gateway = $anthropic = $bearer = $deepgram = $tavily = ""
if (-not $SupabaseOnly) {
    Write-Host "`nAI services" -ForegroundColor Cyan
    $gateway = Ask "Claude gateway base URL, e.g. http://localhost:4000 (Enter for Anthropic directly)"
    $anthropic = Ask "Anthropic API key, or your gateway's key" -Secret
    if ($gateway) { $bearer = Ask "Does the gateway want the key as 'Authorization: Bearer'? (y/N)" }
    $deepgram = Ask "Deepgram API key" -Secret
    $tavily = Ask "Tavily API key (optional, Enter to skip)" -Secret
}

Set-Value $backend "SUPABASE_URL" $url
Set-Value $backend "SUPABASE_ANON_KEY" $anon
Set-Value $backend "SUPABASE_SERVICE_ROLE_KEY" $service
Set-Value $backend "SUPABASE_DB_URL" $dbUrl
Set-Value $backend "ANTHROPIC_BASE_URL" $gateway
if ($bearer -match "^[yY]") { Set-Value $backend "ANTHROPIC_AUTH_TOKEN" $anthropic } else { Set-Value $backend "ANTHROPIC_API_KEY" $anthropic }
Set-Value $backend "DEEPGRAM_API_KEY" $deepgram
Set-Value $backend "TAVILY_API_KEY" $tavily
Set-Value $backend "REDIS_URL" "redis://localhost:6379/0"

# The browser app only gets the public values, never the secret keys.
Set-Value $frontend "NEXT_PUBLIC_SUPABASE_URL" $url
Set-Value $frontend "NEXT_PUBLIC_SUPABASE_ANON_KEY" $anon

Write-Host "`nSaved. Keys that are set (values not shown):" -ForegroundColor Green
foreach ($file in @($backend, $frontend)) {
    Write-Host "  $file"
    foreach ($line in [IO.File]::ReadAllLines($file, $utf8)) {
        if ($line -match "^(SUPABASE_\w+|NEXT_PUBLIC_SUPABASE_\w+|ANTHROPIC_(?:API_KEY|AUTH_TOKEN|BASE_URL)|DEEPGRAM_API_KEY|TAVILY_API_KEY)=(.*)$") {
            $state = if ($Matches[2] -and $Matches[2] -notmatch "^your-") { "set" } else { "EMPTY" }
            Write-Host ("    {0,-32} {1}" -f $Matches[1], $state)
        }
    }
}
