' run-hidden-args.vbs <exe> [arg1] [arg2] ...
' Launches an executable with args, NO console window.
' Silently ignores "file not found" (80070002) to avoid WScript error popups
' when the watchdog briefly sees a missing node/python path.
Option Explicit
Dim shell, fso, exe, i, cmd

If WScript.Arguments.Count = 0 Then
    WScript.Quit 1
End If

exe = WScript.Arguments(0)
Set fso = CreateObject("Scripting.FileSystemObject")

' Resolve path: if given a bare command (e.g. "node"), verify it exists via PATH;
' otherwise require the literal path to exist. Silently skip if not found.
If Not fso.FileExists(exe) Then
    WScript.Quit 0
End If

cmd = """" & exe & """"
For i = 1 To WScript.Arguments.Count - 1
    cmd = cmd & " """ & WScript.Arguments(i) & """"
Next

Set shell = CreateObject("WScript.Shell")
' 0 = hidden window, False = do not wait. On Error Resume Next suppresses
' transient launch failures so no modal error dialog appears.
On Error Resume Next
shell.Run cmd, 0, False
WScript.Quit 0
