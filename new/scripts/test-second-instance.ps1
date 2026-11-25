# Проверка нового exe: при уже запущенном приложении второй экземпляр должен
# корректно выйти за пару секунд (защита «один экземпляр»), без сбоев.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$exe = 'C:\Users\Sky\Desktop\ворк\Заметки\new\dist\Заметки.exe'
$t0 = Get-Date
$p = Start-Process -FilePath $exe -PassThru
$exited = $p.WaitForExit(10000)
$sec = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
if ($exited) {
    Write-Output ('вышел сам за ' + $sec + ' сек, код=' + $p.ExitCode + ' (второй экземпляр — норма)')
} else {
    Stop-Process -Id $p.Id -Force
    Write-Output 'продержался 10+ сек — значит запустился первым (приложение пользователя закрыто?)'
}
