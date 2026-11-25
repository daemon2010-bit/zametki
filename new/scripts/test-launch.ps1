# Проверка запуска собранного exe: старт, ожидание 8 секунд, проверка живости, закрытие.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$exe = 'C:\Users\Sky\Desktop\ворк\Заметки\new\dist\Заметки.exe'
$p = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 8
$alive = -not $p.HasExited
if ($alive) {
    Stop-Process -Id $p.Id -Force
}
Write-Output ('Запуск без падения в первые 8 секунд: ' + $alive)
