# Список процессов приложения «Заметки» (учитывает кириллицу).
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$procs = Get-Process | Where-Object { $_.ProcessName -like '*аметки*' -or $_.ProcessName -like '*Zametki*' }
if ($procs) {
    $procs | ForEach-Object { Write-Output ("PID=" + $_.Id + "  name=" + $_.ProcessName + "  start=" + $_.StartTime + "  win=" + $_.MainWindowTitle) }
} else {
    Write-Output 'нет запущенных процессов Заметки'
}
