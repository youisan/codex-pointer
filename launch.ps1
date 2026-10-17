$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskExe = Join-Path $taskRoot 'dist\v0.6.1\CodexPointer.exe'
if (Test-Path -LiteralPath $taskExe) {
    Start-Process -FilePath $taskExe -WorkingDirectory $taskRoot -WindowStyle Hidden
} else {
    $taskPython = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if (-not $taskPython) { throw '需要 Python 3.10–3.12 和 PySide6，或先运行 scripts\build.ps1 生成 EXE。' }
    Start-Process -FilePath $taskPython.Source -ArgumentList @('"' + (Join-Path $taskRoot 'run.py') + '"') -WorkingDirectory $taskRoot -WindowStyle Hidden
}
