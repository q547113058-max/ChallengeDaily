' ChallengeDaily watchdog launcher - runs watchdog.cmd with NO window.
' Task Scheduler's Hidden flag is unreliable for cmd.exe; launching via
' WScript.Shell.Run with window style 0 guarantees no console window.
Option Explicit
Dim shell, fso, here, target
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
target = here & "\watchdog.cmd"
If Not fso.FileExists(target) Then
    WScript.Quit 1
End If
' 0 = hidden window, False = don't wait
shell.Run """" & target & """", 0, False
