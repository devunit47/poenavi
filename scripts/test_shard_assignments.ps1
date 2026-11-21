$ErrorActionPreference = "Stop"
$runner = Join-Path $PSScriptRoot run_tests_by_file.ps1
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    $files = @(Get-ChildItem tests/test_*.py -File | ForEach-Object Name)
    foreach ($markExpression in @("", "not qt_matrix")) {
        $mode = if ($markExpression) { "fast" } else { "full" }
        Write-Host "Checking $mode shard assignments"
        $assignments = @(& $runner -ShardCount 3 -MarkExpression $markExpression -ListAssignments)
        $repeated = @(& $runner -ShardCount 3 -MarkExpression $markExpression -ListAssignments)

        if ($assignments.Count -ne $files.Count -or
            (Compare-Object $files @($assignments | ForEach-Object Name))) {
            throw "Shard assignments must contain each test file exactly once."
        }
        if (($assignments | ConvertTo-Json -Compress) -cne ($repeated | ConvertTo-Json -Compress)) {
            throw "Shard assignments changed between runs."
        }

        $largestFile = ($assignments | Measure-Object EstimatedSeconds -Maximum).Maximum
        $summary = foreach ($index in 1..3) {
            $shard = @($assignments | Where-Object ShardIndex -eq $index)
            if ($shard.Count -eq 0) {
                throw "Shard $index is empty."
            }
            [pscustomobject]@{
                Shard = $index
                Files = $shard.Count
                EstimatedSeconds = [Math]::Round(($shard | Measure-Object EstimatedSeconds -Sum).Sum, 2)
            }
        }
        $totals = $summary | Measure-Object EstimatedSeconds -Minimum -Maximum -Sum
        # The current timings permit near-equal shards. A future long test may set the lower bound.
        $lowerBound = [Math]::Max($largestFile, $totals.Sum / 3)
        if ($totals.Maximum -gt $lowerBound * 1.05) {
            throw "The slowest shard is more than 5% above the theoretical minimum."
        }
        $summary | Format-Table -AutoSize
    }
} finally {
    Pop-Location
}
