# MCP Tools launcher for Archicad (WIP, not built yet)

What it is: a very small Archicad add-on (.apx on Windows) that puts one command in Archicad's menu bar,
**MCP Tools > Open MCP Architecture & Interiors**, which starts the separate program.

What it is not: it does not read the model. Reading the open project is done by the program itself, through
Archicad's JSON link (File > Archicad link (WIP)...).

## To build it
1. Download the Archicad API Development Kit for your Archicad version from Graphisoft (graphisoft.com/downloads/api-development-kit) and install Visual Studio with the C++ tools.
2. Copy this folder next to the Development Kit's "Examples/Template" (or use that template's project), put `MCPLauncher.cpp` and `RFIX/MCPLauncher.grc` in it, and build the Release x64 target.
3. Copy the resulting `.apx` into Archicad's Add-Ons folder (or load it with Options > Add-On Manager), then restart Archicad.
4. In the program, turn on File > WIP mode. It writes the program's location to `%APPDATA%\MCP_XA_Energy\app_path.txt`, which the launcher reads.

Each Archicad version needs its own build. The menu resource layout follows the Development Kit template; if your kit's template differs, adjust the resource IDs in the .grc and the .cpp.

## Installing the built file
`install_to_archicad.bat "<Archicad 28 .apx>" "<Archicad 30 .apx>"` (run as administrator) copies them into
`C:\Program Files\GRAPHISOFT\Archicad 28\Add-Ons` and `...\Archicad 30\Add-Ons`.
