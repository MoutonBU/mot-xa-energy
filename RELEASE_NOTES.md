# MCP Architecture and Interiors XA Energy - Release notes

Current version: **1.9.0**. You can read these notes in the program: File > Release notes... The version number is shown in the installer, in the installer file name
(`MCP_XA_Energy_Setup_x.y.z.exe`) and in Windows' list of installed programs.

## What is new since the first version (1.0.0)

### New features
- **Coverage & FAR tab** (beside Energy XA): stand area, blocks, carport roofs; coverage % and floor area ratio for
  one block, all blocks, and all blocks with carport roofs; PASS/FAIL against the limits you enter; areas filled from
  the Rooms list (storeys and floor areas per level from the IFC); choice of net rooms + walls, IFC gross, or the gross
  floor area from Building details; its own PDF report.
- **One PDF per subject**: every report (Light & Ventilation, Energy XA, Rational Design, Coverage & FAR) can be exported
  as a separate PDF for each subject (Reports menu > "Export each subject as its own PDF...").
- **Cover page** on every report: logo, project, site, location, client, architect and who compiled it.
- **Sign-in and licences**: accounts with email and password; a licence is created automatically for every new
  account (no key to type); licences can be blocked, extended or expired; the key is also emailed; users who are signed
  in stay signed in.
- **Updates**: the red "Update available" button and Menu > Check for updates download and install the new version in
  one click, with no token. Your work is saved and restored after the update.
- **Dark / light mode** switch that changes the interface at once, without restarting. The installer matches the dark theme.
- **Detail Notes (WIP) tab (1.9.0):** your Detailmakker tool is now a tab in the suite with its own icon. Open a DWG/DXF of a construction detail and it writes the callout notes, draws brickwork and house colours, checks for missing elements and saves the noted drawing. Work in progress. It needs the ODA File Converter for .dwg files (set under its Settings); .dxf works without it. Saved files go to your MCP_XA_Energy\\DetailNotes_outputs folder.
- **Add block from IFC (1.8.5):** Coverage & FAR has a new button that reads one more block from its own IFC (levels, storeys, floor areas) and adds it to the table. Typing blocks in by hand still works.
- **Typing in tables (1.8.4):** the box you type in inside a table cell (for example Storeys in Coverage & FAR) is now full height with clear light text; Coverage rows are taller.
- **Keep me signed in fixed (1.8.3):** the saved sign-in was written but never read back when the program started, so it asked for email and password every time. It is now restored on every start.
- **Release notes** inside the program (File > Release notes...) and a tab icon for Coverage & FAR.
- **Version numbers** (1.0.0, 1.0.1 ...) shown everywhere, including inside the installer.

### Improvements
- Light & Ventilation PASS/FAIL results update by themselves after any change to windows, doors or rooms.
- Changing a window's width or height now changes its glazed area, opening size and opening percentage with it.
- Lighting check follows the occupancy class (SANS 10400-XA Table 12) instead of always using the residential 4 W/m2.
- Installer is readable (dark theme, summary box), names the version and replaces older copies and shortcuts.
- **Faster reports**: the 3D model is read once instead of for every PDF. A Rational Design PDF takes about 0.4 s instead of
  11 s after the first one, and "export each subject" for that report takes about 2 s instead of about 100 s.
- Keep me signed in is more reliable: the saved sign-in is only removed when the licence is switched off.

### Renamed
- The program is now **MCP Architecture and Interiors XA Energy** (was "MOT XA Energy"): window title, installer,
  shortcuts, program file (`MCP_XA_Energy.exe`) and your work folder (`MCP_XA_Energy`; the old folder is renamed, nothing is lost).

## What stays the same
- SANS 10400-O natural light and ventilation checks, window / door / room schedules, IFC and PDF import.
- SANS 10400-XA energy: envelope R-values, fenestration, orientation and shading, air leakage, hot water and solar,
  lighting and power, energy zones and the rational design report.
- Archicad PDF placement, simulation export (EnergyPlus IDF), weather files.

## Standards used (checked against the published text)
- SANS 10400-XA:2021 Table 1 (annual consumption), Table 2 (demand), Table 4 (fenestration), Table 12 (lighting power),
  wall / roof / floor R-values by energy zone, pipe insulation, hot water 50 % rule.
- SANS 10400-O: ventilation 5 % of floor area (0.2 m2 minimum). Confirm the natural-light percentage and category
  rule in your copy of the standard before submission.
- Every report states that it supports, and does not replace, the competent person's declaration.

## Quality check done for this release
- Static scan of the whole program: no undefined names, no crashes.
- Every menu action, button, tab, drop-down and theme switch was run against a real model: no errors.
- Speed: Light & Ventilation check 0.02 s, Energy XA calculation 0.12 s, Energy XA PDF 0.3 s, Coverage PDF 0.2 s.
  The first Rational Design PDF of a session needs about 10 s to read the 3D model; the dark/light switch takes about 2 s.
- Standards tables compared with the published SANS 10400-XA:2021 text: consumption and demand tables, fenestration
  table, R-values by zone, hot water and pipe insulation all match.

## Upgrading
Install the latest `MCP_XA_Energy_Setup_x.y.z.exe` once. It replaces the old program in place and removes the old
shortcuts. After that, use the update button inside the program.
