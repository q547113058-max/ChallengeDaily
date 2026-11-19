' run-hidden.vbs <script-path>
' Launches the given .cmd/.bat with NO console window.
' Silently skips missing files to avoid WScript modal error popups.
Option Explicit
Dim shell, fso, target

Set fso = CreateObject("Scripting.FileSystemObject")
If WScript.Arguments.Count = 0 Then
    WScript.Quit 1
End If
target = WScript.Arguments(0)
If Not fso.FileExists(target) Then
    WScript.Quit 0
End If

Set shell = CreateObject("WScript.Shell")
On Error Resume Next
' 0 = hidden window, False = do not wait for completion
shell.Run """" & target & """", 0, False
WScript.Quit 0
