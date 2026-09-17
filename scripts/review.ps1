#requires -Version 7.0
# PowerShell 7 wrapper for AstraZit OpenRouter Specialist Review Matrix (OS-009)
[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [string]$Ticket,

    [Parameter()]
    [string]$Profile,

    [Parameter()]
    [ValidateSet("claude", "deepseek", "grok")]
    [string]$Specialist,

    [Parameter()]
    [string]$Output = "reports/reviews",

    [Parameter()]
    [switch]$Live,

    [Parameter()]
    [Alias("dry-run")]
    [switch]$DryRun,

    [Parameter()]
    [switch]$Offline
)

$ErrorActionPreference = "Stop"

# 1. Enforce PowerShell 7+ Runtime
if ($PSVersionTable.PSVersion.Major -lt 7) {
    Write-Error "ERROR: PowerShell 7+ (pwsh) is required to run review.ps1. Currently running PSVersion $($PSVersionTable.PSVersion)."
    exit 1
}

# 2. Mutually exclusive flag checks
if ($Live -and ($DryRun -or $Offline)) {
    Write-Error "ERROR: Cannot specify both -Live and -DryRun/-Offline. Choose either live execution or offline validation."
    exit 1
}

# 2b. If -Live is requested, retrieve OPENROUTER_API_KEY from User or Machine scope if not in process scope
if ($Live -and -not $env:OPENROUTER_API_KEY) {
    $foundKey = [System.Environment]::GetEnvironmentVariable("OPENROUTER_API_KEY", "User")
    if (-not $foundKey) {
        $foundKey = [System.Environment]::GetEnvironmentVariable("OPENROUTER_API_KEY", "Machine")
    }
    if ($foundKey) {
        $env:OPENROUTER_API_KEY = $foundKey
    }
}

# 3. Locate a compatible Python interpreter (>= 3.12)
$pythonCmd = $null
$candidateCommands = @("python", "python3", "py")

foreach ($cmd in $candidateCommands) {
    try {
        $checkScript = "import sys; print(str(sys.version_info.major) + '.' + str(sys.version_info.minor))"
        $out = & $cmd -c $checkScript 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            $parts = $out.Trim().Split(".")
            $major = [int]$parts[0]
            $minor = [int]$parts[1]
            if (($major -eq 3 -and $minor -ge 12) -or ($major -gt 3)) {
                $pythonCmd = $cmd
                break
            }
        }
    } catch {
        # continue searching
    }
}

if (-not $pythonCmd) {
    Write-Error "ERROR: A Python interpreter >= 3.12 is required but could not be located on PATH."
    exit 1
}

# 4. Locate review_runner.py
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runnerPath = Join-Path $scriptDir "review_runner.py"

if (-not (Test-Path $runnerPath)) {
    Write-Error "ERROR: Review runner script not found at $runnerPath"
    exit 1
}

# 5. Assemble arguments
$pyArgs = @($runnerPath, $Ticket)

if ($Profile) {
    $pyArgs += @("--profile", $Profile)
}
if ($Specialist) {
    $pyArgs += @("--specialist", $Specialist)
}
if ($Output) {
    $pyArgs += @("--output", $Output)
}
if ($Live) {
    $pyArgs += "--live"
}
if ($DryRun -or $Offline) {
    $pyArgs += "--dry-run"
}

# 6. Invoke runner without leaking secrets
& $pythonCmd @pyArgs
exit $LASTEXITCODE

