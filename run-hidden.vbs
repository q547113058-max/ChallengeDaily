' run-hidden.vbs <script-path>
' Launches the given .cmd/.bat with NO console window.
' WScript.Shell.Run(windowStyle=0) hides the console reliably, unlike
' Task Scheduler's Hidden flag or cmd's "start /min".
Option Explicit
Dim shell, target
Set shell = CreateObject("WScript.Shell")
If WScript.Arguments.Count = 0 Then
    WScript.Quit 1
End If
target = WScript.Arguments(0)
If Not CreateObject("Scripting.FileSystemObject").FileExists(target) Then
    WScript.Quit 1
End If
' 0 = hidden, False = do not wait for completion
shell.Run """" & target & """", 0, False
