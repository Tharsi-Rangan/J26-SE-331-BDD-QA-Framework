# Run C3 on every BugsJS batch fixture (fixtures/bugsjs/<bug>) with one command, then compare buggy vs fixed.
# Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File packages\c3-test-generation\scripts\run-bugsjs.ps1
# Options:
#   -Subjects C:\c3-subjects   where the BugsJS clones and the buggy/fixed folders go (outside the repo)
#   -Only eslint-22,hexo-7     run only these bugs
#   -SkipSetup                 do not clone / install again (folders already there)
#   -Cache readwrite           LLM_CACHE for this run: readwrite (first real run) or readonly (replay, offline)
# For each bug: clone github.com/BugsJS/<project> once, add a buggy and a fixed folder at the refs in the
# fixture's subject-manifest.json, npm install, copy the fixture to runs\bugsjs-<bug>, c3 run on the buggy
# version, c3 pilot on buggy vs fixed. At the end: one summary table (also written to runs\bugsjs-summary.md).
param(
  [string]$Subjects = 'C:\c3-subjects',
  [string[]]$Only = @(),
  [switch]$SkipSetup,
  [ValidateSet('readwrite', 'readonly', 'off')][string]$Cache = 'readwrite'
)
$ErrorActionPreference = 'Stop'
$repo = (Get-Location).Path
$fixtures = Join-Path $repo (Join-Path 'packages' (Join-Path 'c3-test-generation' (Join-Path 'fixtures' 'bugsjs')))
if (-not (Test-Path $fixtures)) { throw "Run this from the repo root (no $fixtures here)." }
$runs = Join-Path $repo 'runs'
New-Item -ItemType Directory -Force -Path $Subjects, (Join-Path $Subjects 'bugs'), $runs | Out-Null
$env:LLM_CACHE = $Cache   # values set outside .env win over .env
$fwd = { param($p) $p -replace '\\', '/' }

$bugs = Get-ChildItem $fixtures -Directory | Sort-Object Name
$Only = @($Only | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })   # -File passes 'a,b' as one string
if ($Only.Count) { $bugs = $bugs | Where-Object { $Only -contains $_.Name } }
$summary = @()

foreach ($b in $bugs) {
  $id = $b.Name
  $m = (Get-Content (Join-Path $b.FullName 'subject-manifest.json') -Raw | ConvertFrom-Json).subjects[0]
  $clone = Join-Path $Subjects $m.project
  $buggy = Join-Path (Join-Path $Subjects 'bugs') "$id-buggy"
  $fixed = Join-Path (Join-Path $Subjects 'bugs') "$id-fixed"
  Write-Host "`n===== $id ($($m.source.bug_id), $($m.module_path)) =====" -ForegroundColor Cyan

  if (-not $SkipSetup) {
    if (-not (Test-Path $clone)) { git clone "https://github.com/BugsJS/$($m.project).git" $clone; if ($LASTEXITCODE) { throw "clone failed: $($m.project)" } }
    foreach ($v in @(@($buggy, $m.source.buggy_ref), @($fixed, $m.source.fixed_ref))) {
      if (-not (Test-Path $v[0])) {
        git -C $clone worktree add --detach $v[0] $v[1]; if ($LASTEXITCODE) { throw "worktree failed: $($v[0])" }
      }
      if (-not (Test-Path (Join-Path $v[0] 'node_modules'))) {
        Write-Host "  npm install in $($v[0]) ..."
        npm --prefix $v[0] install --omit=dev --ignore-scripts --no-audit --no-fund --loglevel=error
        if ($LASTEXITCODE) { throw "npm install failed: $($v[0])" }
      }
    }
  }

  $run = "runs/bugsjs-$id"
  if (Test-Path $run) { Remove-Item -Recurse -Force $run }
  Copy-Item -Recurse $b.FullName $run

  pnpm c3 run --in $run --out $run --subject-root (& $fwd $buggy)
  $runOk = ($LASTEXITCODE -eq 0)
  if ($runOk) {
    pnpm c3 pilot --run $run --buggy (& $fwd $buggy) --fixed (& $fwd $fixed) --label $id
  }
  $res = Join-Path $run (Join-Path 'c3' (Join-Path 'work' 'pilot_results.json'))
  if ($runOk -and (Test-Path $res)) {
    $s = (Get-Content $res -Raw | ConvertFrom-Json).summary
    $summary += [pscustomobject]@{ Bug = $id; Scenarios = $s.scenarios; Runnable = $s.runnable_scenarios; Stubs = $s.stub_scenarios;
      Tests = $s.tests_generated; BugDetected = $s.bugs_detected_tests; FalseAlarms = $s.false_alarm_tests; NoSignal = $s.no_signal_tests }
  } else {
    $summary += [pscustomobject]@{ Bug = $id; Scenarios = '-'; Runnable = '-'; Stubs = '-'; Tests = '-'; BugDetected = '-'; FalseAlarms = 'RUN FAILED'; NoSignal = '-' }
  }
}

# Express-5 was piloted earlier (runs\express5-pilot-run4); add it to the table when it is there.
$e5 = Join-Path $runs (Join-Path 'express5-pilot-run4' (Join-Path 'c3' (Join-Path 'work' 'pilot_results.json')))
if (-not $Only.Count -and (Test-Path $e5)) {
  $s = (Get-Content $e5 -Raw | ConvertFrom-Json).summary
  $summary = @([pscustomobject]@{ Bug = 'express-5'; Scenarios = $s.scenarios; Runnable = $s.runnable_scenarios; Stubs = $s.stub_scenarios;
    Tests = $s.tests_generated; BugDetected = $s.bugs_detected_tests; FalseAlarms = $s.false_alarm_tests; NoSignal = $s.no_signal_tests }) + $summary
}

Write-Host "`n===== SUMMARY (same tests on buggy and fixed) =====" -ForegroundColor Green
$summary | Format-Table -AutoSize | Out-String | Write-Host
$md = @('| Bug | Scenarios | Runnable | Stubs | Tests | Bug detected | False alarms | No signal |', '|---|---|---|---|---|---|---|---|')
$md += $summary | ForEach-Object { "| $($_.Bug) | $($_.Scenarios) | $($_.Runnable) | $($_.Stubs) | $($_.Tests) | $($_.BugDetected) | $($_.FalseAlarms) | $($_.NoSignal) |" }
$mdFile = Join-Path $runs 'bugsjs-summary.md'
$md | Set-Content -Encoding utf8 $mdFile
Write-Host "Summary written to $mdFile"
