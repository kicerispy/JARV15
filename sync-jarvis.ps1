param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Run-Git {
    param(
        [Parameter(Mandatory=$true)]
        [string[]]$Arguments
    )

    & git @Arguments

    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($Arguments -join ' ')"
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "       JARVIS SAFE GIT SYNC" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------
# 1. Make sure we're inside the repository
# ------------------------------------------------------------

$RepoRoot = (& git rev-parse --show-toplevel).Trim()

if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($RepoRoot)) {
    throw "This directory is not inside a Git repository."
}

Set-Location $RepoRoot

Write-Host "[1/9] Repository:" -ForegroundColor Yellow
Write-Host "      $RepoRoot"

# ------------------------------------------------------------
# 2. Detect branch
# ------------------------------------------------------------

$Branch = (& git branch --show-current).Trim()

if ([string]::IsNullOrWhiteSpace($Branch)) {
    throw "Detached HEAD detected. Refusing to sync."
}

Write-Host "[2/9] Branch:" -ForegroundColor Yellow
Write-Host "      $Branch"

# Never automatically sync main/master.
if ($Branch -eq "main" -or $Branch -eq "master") {
    throw "Refusing automatic sync on '$Branch'. Use a development branch."
}

# ------------------------------------------------------------
# 3. Make sure no Git operation is already in progress
# ------------------------------------------------------------

$GitDir = (& git rev-parse --git-dir).Trim()

$InProgressFiles = @(
    (Join-Path $GitDir "MERGE_HEAD"),
    (Join-Path $GitDir "REBASE_HEAD"),
    (Join-Path $GitDir "CHERRY_PICK_HEAD"),
    (Join-Path $GitDir "REVERT_HEAD")
)

foreach ($File in $InProgressFiles) {
    if (Test-Path $File) {
        throw "Git operation already in progress: $File"
    }
}

# ------------------------------------------------------------
# 4. Check working tree
# ------------------------------------------------------------

$StatusBefore = @(git status --short)

Write-Host "[3/9] Working tree:" -ForegroundColor Yellow

if ($StatusBefore.Count -eq 0) {
    Write-Host "      Clean" -ForegroundColor Green
}
else {
    Write-Host "      Local changes detected:" -ForegroundColor DarkYellow
    $StatusBefore | ForEach-Object {
        Write-Host "      $_"
    }
}

# ------------------------------------------------------------
# 5. Fetch remote
# ------------------------------------------------------------

Write-Host "[4/9] Fetching origin..." -ForegroundColor Yellow

if (-not $DryRun) {
    Run-Git @("fetch", "origin", "--prune")
}
else {
    Write-Host "      DRY RUN - fetch skipped"
}

# ------------------------------------------------------------
# 6. Determine upstream branch
# ------------------------------------------------------------

$Upstream = ""

try {
    $Upstream = (& git rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>$null).Trim()
}
catch {
    $Upstream = ""
}

Write-Host "[5/9] Upstream:" -ForegroundColor Yellow

if ([string]::IsNullOrWhiteSpace($Upstream)) {
    Write-Host "      No upstream configured" -ForegroundColor DarkYellow
}
else {
    Write-Host "      $Upstream"
}

# ------------------------------------------------------------
# 7. Reconcile remote branch safely
# ------------------------------------------------------------

if (-not [string]::IsNullOrWhiteSpace($Upstream)) {

    $Counts = (& git rev-list --left-right --count "$Upstream...HEAD").Trim()

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to determine branch divergence."
    }

    $Parts = $Counts -split "\s+"

    $Behind = [int]$Parts[0]
    $Ahead  = [int]$Parts[1]

    Write-Host "[6/9] Branch relationship:" -ForegroundColor Yellow
    Write-Host "      Ahead:  $Ahead"
    Write-Host "      Behind: $Behind"

    if ($Behind -gt 0 -and $Ahead -gt 0) {
        throw @"
Branch has diverged from $Upstream.

Ahead:  $Ahead
Behind: $Behind

Refusing to automatically merge/rebase divergent history.
Resolve this manually first.
"@
    }

    if ($Behind -gt 0) {

        if ($StatusBefore.Count -ne 0) {
            throw "Remote has commits that you do not have and your working tree is not clean. Commit/stash local changes before rebasing."
        }

        Write-Host "      Local branch is behind. Rebasing..." -ForegroundColor Yellow

        if (-not $DryRun) {
            Run-Git @("pull", "--rebase", "origin", $Branch)
        }
        else {
            Write-Host "      DRY RUN - rebase skipped"
        }
    }
}
else {
    Write-Host "[6/9] No upstream branch configured." -ForegroundColor DarkYellow
}

# ------------------------------------------------------------
# 8. Stage changes, inspect them, and validate
# ------------------------------------------------------------

Write-Host "[7/9] Preparing changes..." -ForegroundColor Yellow

if (-not $DryRun) {

    # Stage tracked/untracked files while respecting .gitignore.
    Run-Git @("add", "-A")

    $Staged = @(git diff --cached --name-only)

    if ($Staged.Count -eq 0) {
        Write-Host ""
        Write-Host "No changes to commit." -ForegroundColor Green
        Write-Host ""

        $FinalStatus = @(git status --short)

        if ($FinalStatus.Count -eq 0) {
            Write-Host "Repository is already synchronized." -ForegroundColor Green
        }
        else {
            Write-Host "Remaining status:" -ForegroundColor Yellow
            $FinalStatus | ForEach-Object {
                Write-Host "  $_"
            }
        }

        exit 0
    }

    Write-Host ""
    Write-Host "Files staged for commit:" -ForegroundColor Cyan

    foreach ($File in $Staged) {
        Write-Host "  $File"
    }

    # --------------------------------------------------------
    # Safety denylist
    # --------------------------------------------------------

    $ForbiddenPatterns = @(
        "^\s*jarvis_cuda/",
        "^\s*\.venv/",
        "^\s*venv/",
        "^\s*playwright_profile/",
        "^\s*__pycache__/",
        "(^|/)\.jarvis_checkpoints/",
        "\.(onnx|pt|pth|bin|safetensors|gguf)$",
        "\.(wav|db|db-shm|db-wal)$",
        "\.log$",
        "\.tmp$"
    )

    $Dangerous = @()

    foreach ($File in $Staged) {
        foreach ($Pattern in $ForbiddenPatterns) {
            if ($File -match $Pattern) {
                $Dangerous += $File
                break
            }
        }
    }

    if ($Dangerous.Count -gt 0) {

        Write-Host ""
        Write-Host "DANGEROUS FILES DETECTED." -ForegroundColor Red

        $Dangerous | Sort-Object -Unique | ForEach-Object {
            Write-Host "  $_" -ForegroundColor Red
        }

        git reset | Out-Null

        throw "Sync aborted. Dangerous files were staged."
    }

    # --------------------------------------------------------
    # Python syntax validation
    # --------------------------------------------------------

    $PythonFiles = @(
        $Staged |
        Where-Object { $_ -match "\.py$" } |
        Sort-Object -Unique
    )

    if ($PythonFiles.Count -gt 0) {

        Write-Host ""
        Write-Host "Running Python syntax checks..." -ForegroundColor Cyan

        $Python = Join-Path $RepoRoot "jarvis_cuda\Scripts\python.exe"

        if (-not (Test-Path $Python)) {
            $Python = "python"
        }

        foreach ($File in $PythonFiles) {

            Write-Host "  Checking $File"

            & $Python -m py_compile $File

            if ($LASTEXITCODE -ne 0) {
                git reset | Out-Null
                throw "Python syntax check failed: $File"
            }
        }
    }

    # --------------------------------------------------------
    # Commit
    # --------------------------------------------------------

    $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $CommitMessage = "sync: JARVIS local state $Timestamp"

    Write-Host ""
    Write-Host "Creating commit:" -ForegroundColor Cyan
    Write-Host "  $CommitMessage"

    Run-Git @("commit", "-m", $CommitMessage)
}
else {
    Write-Host "      DRY RUN - staging/validation/commit skipped"
}

# ------------------------------------------------------------
# 9. Push
# ------------------------------------------------------------

Write-Host "[8/9] Pushing branch..." -ForegroundColor Yellow

if (-not $DryRun) {

    Run-Git @("push", "-u", "origin", $Branch)

    Write-Host ""
    Write-Host "[9/9] Sync complete." -ForegroundColor Green
    Write-Host ""
    Write-Host "Branch: $Branch" -ForegroundColor Cyan

    $FinalStatus = @(git status --short)

    if ($FinalStatus.Count -eq 0) {
        Write-Host "Working tree: CLEAN" -ForegroundColor Green
    }
    else {
        Write-Host "Working tree still contains:" -ForegroundColor Yellow
        $FinalStatus | ForEach-Object {
            Write-Host "  $_"
        }
    }
}
else {
    Write-Host "[9/9] DRY RUN complete." -ForegroundColor Green
}

Write-Host ""
