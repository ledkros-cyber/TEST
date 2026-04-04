' VideoGenerator.vbs — тихий запуск программы (без чёрного окна)
Option Explicit

Dim shell, appDir, venvPython, mainPy

Set shell = CreateObject("WScript.Shell")

' Папка, где лежит этот .vbs файл
appDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))

venvPython = appDir & "venv\Scripts\pythonw.exe"
mainPy     = appDir & "main.py"

' Проверяем, установлена ли программа
Dim fso
Set fso = CreateObject("Scripting.FileSystemObject")

If Not fso.FileExists(venvPython) Then
    MsgBox "Программа не установлена." & vbCrLf & vbCrLf & _
           "Запустите SETUP.bat для установки.", _
           vbCritical + vbOKOnly, "YouTube Video Generator"
    WScript.Quit
End If

If Not fso.FileExists(mainPy) Then
    MsgBox "Файл main.py не найден." & vbCrLf & _
           "Убедитесь, что все файлы программы на месте.", _
           vbCritical + vbOKOnly, "YouTube Video Generator"
    WScript.Quit
End If

' Запускаем программу тихо (0 = скрытое окно)
shell.Run """" & venvPython & """ """ & mainPy & """", 0, False

Set shell = Nothing
Set fso   = Nothing
