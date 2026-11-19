@echo off
rem Copies a built MCPLauncher.apx into the Add-Ons folder of Archicad 28 and Archicad 30.
rem Usage: right-click > Run as administrator, or:  install_to_archicad.bat "C:\path\to\MCPLauncher.apx"
rem Use the .apx built with the matching Development Kit: one build for 28, another for 30.
setlocal
set APX28=%~1
set APX30=%~2
if "%APX28%"=="" (echo Give the path of the Archicad 28 build as the first argument, and the Archicad 30 build as the second. & exit /b 1)
if "%APX30%"=="" set APX30=%APX28%
copy /Y "%APX28%" "C:\Program Files\GRAPHISOFT\Archicad 28\Add-Ons\MCPLauncher.apx" && echo Archicad 28 done
copy /Y "%APX30%" "C:\Program Files\GRAPHISOFT\Archicad 30\Add-Ons\MCPLauncher.apx" && echo Archicad 30 done
echo Restart Archicad. Look for MCP Tools in the menu bar. Turn on WIP mode in the program first (File menu).
