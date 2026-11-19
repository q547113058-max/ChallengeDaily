' ChallengeDaily Desktop Launcher (source version)
' Launches start-dev.cmd with NO console window and no UAC prompt.
' Equivalent to double-clicking start-dev.cmd:
'   vite build (~6s) then start source Electron with direct cloud backend.
Option Explicit
Dim shell, fso, here, target, workdir
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = "D:\project\daily\ChallengeDaily"
target = here & "\start-dev.cmd"
If Not fso.FileExists(target) Then
    MsgBox "start-dev.cmd not found: " & target, 16, "ChallengeDaily"
    WScript.Quit 1
End If
shell.CurrentDirectory = here
' 0 = hidden window, False = do not wait
shell.Run """" & target & """", 0, False
