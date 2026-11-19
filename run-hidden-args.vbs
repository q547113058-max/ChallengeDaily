' run-hidden-args.vbs <exe> [arg1] [arg2] ...
' Launches an executable with args, NO console window.
' Unlike run-hidden.vbs (single script path), this supports multiple args
' so it can start node.exe bridge-proxy.cjs and python.exe -u producer.py.
Option Explicit
Dim shell, exe, args, i, cmd
If WScript.Arguments.Count = 0 Then
    WScript.Quit 1
End If
Set shell = CreateObject("WScript.Shell")
exe = WScript.Arguments(0)
cmd = """" & exe & """"
For i = 1 To WScript.Arguments.Count - 1
    cmd = cmd & " """ & WScript.Arguments(i) & """"
Next
' 0 = hidden window, False = do not wait
shell.Run cmd, 0, False
