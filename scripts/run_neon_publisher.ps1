param(
    [Parameter(Mandatory)]
    [ValidateSet('dry-run', 'write', 'verify')]
    [string]$Mode,
    [string]$Root = '.',
    [string]$LiveBase = 'https://blueyco.in'
)

$ErrorActionPreference = 'Stop'
$branch = 'br-damp-sun-bky4w0l6'
$connection = @(neon connection-string $branch --project-id falling-surf-51551585 --database-name bluey 2>$null)
if ($LASTEXITCODE -ne 0 -or $connection.Count -ne 1 -or $connection[0] -notmatch '^postgres(ql)?://') {
    throw 'The production Neon connection could not be loaded.'
}

$env:BLUEY_NEON_BRANCH_ID = $branch
$env:DATABASE_URL = $connection[0]
try {
    vercel.cmd env run --environment production --project blueycoin --scope jimmylove '--' python "$PSScriptRoot/publish_sold.py" --root $Root --ledger neon --mode $Mode --live-base $LiveBase
    $result = $LASTEXITCODE
}
finally {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:BLUEY_NEON_BRANCH_ID -ErrorAction SilentlyContinue
}
exit $result
