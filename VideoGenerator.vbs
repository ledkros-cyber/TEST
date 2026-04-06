' VideoGenerator.vbs - silent launcher (no black console window)
Option Explicit

Dim shell, fso, appDir, venvPython, mainPy, venvPath

Set shell = CreateObject("WScript.Shell")
Set fso   = CreateObject("Scripting.FileSystemObject")

appDir  = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
mainPy  = appDir & "main.py"

' Check if venv was installed to a custom path (non-ASCII app dir case)
Dim venvPathFile
venvPathFile = appDir & "venv_path.txt"

If fso.FileExists(venvPathFile) Then
    Dim ts
    Set ts = fso.OpenTextFile(venvPathFile, 1)
    venvPath = Trim(ts.ReadAll())
    ts.Close
    venvPython = venvPath & "\Scripts\pythonw.exe"
Else
    venvPython = appDir & "venv\Scripts\pythonw.exe"
End If

If Not fso.FileExists(venvPython) Then
    MsgBox "Program is not installed." & vbCrLf & vbCrLf & _
           "Please run SETUP.bat first.", _
           vbCritical + vbOKOnly, "YouTube Video Generator"
    WScript.Quit
End If

If Not fso.FileExists(mainPy) Then
    MsgBox "File main.py not found." & vbCrLf & _
           "Make sure all program files are present.", _
           vbCritical + vbOKOnly, "YouTube Video Generator"
    WScript.Quit
End If

' Launch silently (0 = hidden window)
shell.Run """" & venvPython & """ """ & mainPy & """", 0, False

Set shell = Nothing
Set fso   = Nothing
