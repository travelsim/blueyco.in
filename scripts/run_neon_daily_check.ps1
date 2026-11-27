param(
    [string]$BaseUrl = 'https://blueyco.in',
    [string]$ProductIds
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
    $scriptPath = Join-Path $PSScriptRoot '..\db\daily_check.py'
    $arguments = @($scriptPath, $BaseUrl)
    if ($ProductIds) {
        $arguments += @('--product-ids', $ProductIds)
    }
    python @arguments
    $result = $LASTEXITCODE
}
finally {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:BLUEY_NEON_BRANCH_ID -ErrorAction SilentlyContinue
}
exit $result
