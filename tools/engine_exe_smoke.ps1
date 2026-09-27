# Packaged-app smoke: does each exe start, and does the engine really come up?
#
# A windowed onefile exe writes no console output, so "it stayed alive" proves
# little. What proves the engine initialised is QtWebEngineProcess — Chromium's
# child process, spawned only when a web view is actually created. The onefile
# bootloader adds a level (the real app is a *child* of the exe, and the engine
# processes hang off that), so the whole descendant tree is walked, and the
# thread count / memory footprint are printed as a shape to compare against the
# last known-good build.
#
# Processes are killed by PID, deepest first, never by image name: you may have
# your own Mei open, and it must survive this.
#
# Usage (from the repository root):
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools/engine_exe_smoke.ps1 -ExePaths dist/Mei.exe
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools/engine_exe_smoke.ps1 -ExePaths dist/Mei.exe,build/alpha/Mei.exe

param(
    [Parameter(Mandatory = $true)][string[]]$ExePaths,
    [int]$SettleSeconds = 35
)

# Run each exe from its own folder: the app treats the folder holding the exe as
# its data root, so this keeps a test run out of the real install's files.
foreach ($candidate in $ExePaths) {
    if (-not (Test-Path $candidate)) {
        "$candidate RESULT missing exe"
        continue
    }
    $exe = (Resolve-Path $candidate).Path
    $dir = Split-Path -Parent $exe

    $p = Start-Process -FilePath $exe -WorkingDirectory $dir -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds $SettleSeconds

    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $byParent = @{}
    foreach ($proc in $all) {
        $key = [int]$proc.ParentProcessId
        if (-not $byParent.ContainsKey($key)) { $byParent[$key] = @() }
        $byParent[$key] += $proc
    }

    $tree = @()
    $queue = @($p.Id)
    while ($queue.Count -gt 0) {
        $next = @()
        foreach ($q in $queue) {
            $key = [int]$q
            if ($byParent.ContainsKey($key)) {
                foreach ($kid in $byParent[$key]) {
                    $tree += $kid
                    $next += $kid.ProcessId
                }
            }
        }
        $queue = $next
    }

    $engine = @($tree | Where-Object { $_.Name -like 'QtWebEngineProcess*' })
    $shape = @()
    foreach ($id in @($p.Id) + @($tree | Select-Object -ExpandProperty ProcessId)) {
        $live = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($live) {
            $shape += ("{0}#{1}(threads={2},mem={3}MB,cpu={4:N1}s)" -f $live.Name, $live.Id, $live.Threads.Count, [int]($live.WorkingSet64 / 1MB), $live.CPU)
        }
    }

    "$candidate RESULT bootloader-exited=$($p.HasExited) engine-procs=$($engine.Count)"
    "$candidate SHAPE $($shape -join ' | ')"

    for ($i = $tree.Count - 1; $i -ge 0; $i--) { Stop-Process -Id $tree[$i].ProcessId -Force -ErrorAction SilentlyContinue }
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 3
}

'--- leftovers (should be empty) ---'
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -match '^(Mei|QtWebEngineProcess)' } |
    Select-Object ProcessId, Name, ExecutablePath | Format-Table -AutoSize
