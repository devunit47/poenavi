param(
    [string]$Python = "python",
    [ValidateRange(1, 2147483647)]
    [int]$ShardIndex = 1,
    [ValidateRange(1, 2147483647)]
    [int]$ShardCount = 1,
    [ValidateRange(1, 2147483)]
    [int]$TimeoutSeconds = 600,
    [switch]$ListAssignments
)

$ErrorActionPreference = "Stop"

if ($ShardIndex -gt $ShardCount) {
    throw "ShardIndex must be between 1 and ShardCount ($ShardCount)."
}

$testFiles = @(Get-ChildItem tests/test_*.py -File | Sort-Object Name)
if ($ShardCount -gt 1 -or $ListAssignments) {
    $durations = Get-Content -Raw (Join-Path $PSScriptRoot test_durations.json) | ConvertFrom-Json
    $shardTotals = [decimal[]]::new($ShardCount)
    $estimatedFiles = foreach ($testFile in $testFiles) {
        $duration = $durations.PSObject.Properties[$testFile.Name]
        $seconds = if ($null -eq $duration) { 2.0d } else { [decimal]$duration.Value }
        [pscustomobject]@{
            Name = $testFile.Name
            Path = $testFile.FullName
            EstimatedSeconds = $seconds
            ShardIndex = 0
        }
    }
    $sortProperties = @(@{ Expression = 'EstimatedSeconds'; Descending = $true }, 'Name')
    $assignments = foreach ($file in ($estimatedFiles | Sort-Object -Property $sortProperties -Culture en-US)) {
        $lightestShard = 0
        for ($index = 1; $index -lt $ShardCount; $index++) {
            if ($shardTotals[$index] -lt $shardTotals[$lightestShard]) {
                $lightestShard = $index
            }
        }
        $shardTotals[$lightestShard] += $file.EstimatedSeconds
        $file.ShardIndex = $lightestShard + 1
        $file
    }
    if ($ListAssignments) {
        $assignments
        return
    }
    $testFiles = $assignments | Where-Object ShardIndex -eq $ShardIndex
    $estimatedTotal = [Math]::Round($shardTotals[$ShardIndex - 1], 2)
    Write-Host "Shard $ShardIndex/$ShardCount - $(@($testFiles).Count) files, estimated ${estimatedTotal}s"
    $testFiles = @($testFiles | ForEach-Object { $_.Path })
} else {
    $testFiles = @($testFiles | ForEach-Object { $_.FullName })
}

$pythonPath = (Get-Command $Python -CommandType Application | Select-Object -First 1).Source
$stackTimeout = [Math]::Max(0.5, $TimeoutSeconds - 30)
$stackTimeout = $stackTimeout.ToString([Globalization.CultureInfo]::InvariantCulture)
$failedFiles = @()

foreach ($testFile in $testFiles) {
    Write-Host "::group::$testFile"
    $process = [Diagnostics.Process]::new()
    try {
        $process.StartInfo.FileName = $pythonPath
        $process.StartInfo.Arguments = "-u -m pytest -q -o faulthandler_timeout=$stackTimeout `"$testFile`""
        $process.StartInfo.WorkingDirectory = (Get-Location).ProviderPath
        $process.StartInfo.UseShellExecute = $false
        [void]$process.Start()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            $failedFiles += $testFile
            Write-Host "$testFile timed out after $TimeoutSeconds seconds"
            try {
                if ($env:OS -eq 'Windows_NT') {
                    & taskkill.exe /PID $process.Id /T /F
                    if ($LASTEXITCODE -ne 0 -and -not $process.HasExited) {
                        $process.Kill()
                    }
                } else {
                    $process.Kill($true)
                }
            } catch {
                Write-Warning "Could not terminate the process tree for ${testFile}: $_"
            }
            if (-not $process.WaitForExit(5000)) {
                Write-Warning "Test process did not exit after termination: $testFile"
            }
        } elseif ($process.ExitCode -ne 0) {
            $failedFiles += $testFile
            Write-Host "$testFile failed with exit code $($process.ExitCode)"
        }
    } finally {
        $process.Dispose()
        Write-Host "::endgroup::"
    }
}

if ($failedFiles.Count -gt 0) {
    throw "Failing test files: $($failedFiles -join ', ')"
}
