' run-task-hidden.vbs <script.ps1>
' Runs a PowerShell script with NO console window at all.
' Task Scheduler's "-WindowStyle Hidden" still flashes a window on Win11;
' WScript.Shell.Run with windowStyle=0 truly hides it.
Option Explicit
Dim shell, fso, ps, script, cmd
If WScript.Arguments.Count = 0 Then WScript.Quit 1
Set fso = CreateObject("Scripting.FileSystemObject")
script = WScript.Arguments(0)
If Not fso.FileExists(script) Then WScript.Quit 0
ps = "C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"
cmd = """" & ps & """ -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & script & """"
Set shell = CreateObject("WScript.Shell")
On Error Resume Next
shell.Run cmd, 0, False
WScript.Quit 0
