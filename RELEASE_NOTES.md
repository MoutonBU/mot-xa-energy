# MCP Architecture and Interiors XA Energy - Release notes

Current version: **1.32.0**. You can read these notes in the program: File > Release notes... The version number is shown in the installer, in the installer file name
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
- **Search, filters and Next problem (1.31.0):** the notes list now has a search box (type DPC or insulation) and filter buttons: All, Checked, To verify, Unfinished, each with a count. The number of each note is coloured by status (green checked, red to verify, amber unfinished). New “Next problem” button jumps to the next note that still needs you and brings it into view on the drawing. The status line shows the percentage checked.
- **Workflow rail, project dashboard and submission checklist (1.32.0):** the Detail Notes tab has a left rail (Open, Auto note, Review, Export) with progress and a Next problem button; it hides on narrow windows. After Batch folder a Project dashboard opens: counts, one card per detail with a progress bar, the same-material-different-wording warning, and a submission checklist (waterproofing/DPC, roof and wall R-values against your climate zone, foundation depth, products to verify, specifications chosen). “Build submission pack” gathers the noted drawings, each detail's schedule, the project schedule and the checklist into one folder. The checklist only reads what the notes say; you still approve each note.
- **Resize a note by its corner, normal window size, no start-up question (1.30.0):** select a note and a small yellow square appears on its bottom corner. Drag it to make the note wider or narrower and the text re-flows to fit; right-click > Back to the standard width undoes it. The width is saved with the detail and covered by undo. The program no longer opens wider than your screen: long rows of buttons now wrap onto a second line and long hint texts wrap instead of forcing the window wide. It also no longer asks “Start a new project?” each time it opens when nothing of yours is open.
- **Faster note editing on the drawing (1.29.0):** right-click a note for a menu (edit text, choose specification, pointer, snap to column, mark as checked, delete). A small bar appears beside the selected note with Spec, In line, Delete and Pointer. Double-click a note to type its new wording right on the drawing (Enter saves, Shift+Enter new line, Esc cancels). Notes get a coloured outline: green = checked by you, red = to verify, amber = no specification chosen yet. A status line under the drawing counts notes, checked, to verify and unfinished, and shows the town and XA zone.
- **Town and climate zone on the Detail Notes tab (1.28.0):** type the nearest SANS 10400-XA town in the Notes step and press Enter. It sets the same town and energy zone as the Energy tab, shows the zone's roof and wall R-values, and every insulation note already on the detail is rewritten to that zone. Changing the zone on the Energy tab updates the notes the same way.
- **Project check (1.27.0):** after "Batch folder" the tool compares all the details together. It flags the same material that is worded differently on different details (a different thickness does not count), lists the parts that still have no specification chosen, and saves one combined project notes schedule PDF for the whole folder.
- **Layout menu, layer matching and style presets (1.26.0):** new Layout button on the Detail Notes toolbar. Note column on the right, left, or both sides (each note goes to the nearer side). Align selected notes (left or right edges), spread three or more evenly top to bottom, or snap them to the column; moved notes snap to the nearest column. Choose the note text font. Save the whole look (scale, text size, width, numbering, pointer, column side, font) as a named style preset and reuse it on any detail. In the spec picker, More options now has “Use this for everything on layer ...”: next time any part on that layer gets the note automatically on every detail. Layout > Remembered matches lists the material and layer matches so you can forget any.
- **Straight note column and leader end styles (1.25.0):** a note you move now snaps back into the straight column of the other notes when you drop it close to the column (tick "Keep notes in line" off, or hold Alt while dropping, to place it freely). New "Pointer" list: dot, arrow, ring, tick or none for the end of the leader. With notes selected it changes those notes, with none selected it changes all of them. Saved with the detail and covered by undo/redo.
- **Friendlier spec picker (1.23.0):** the 34 groups are folded into 8 families with icons (foundations and floors, walls, roof and ceiling, waterproofing and insulation, windows and doors, services and outside, finishes, South African products) and each group has its own icon. Each option shows a short preview of its note under its name. Click-to-try chips under the search box ("concrete coping", "stone cill", "170 slab"...). Approve, Save to My specs and Remember moved under "More options", so the main view is just: search, pick, check your note, Use this note.
- **Other notes adjust around the ones you move (1.22.0):** when you drag a note, the remaining notes close the gap it left and flow around its new spot, so nothing overlaps. Move one and the whole column re-arranges itself.
- **Place notes anywhere (1.21.0):** drag a note's text to any spot, on or off the drawing, and drag its white dot to change exactly what it points at. The leader follows both, with a live dashed line while you drag. Both are saved with the detail, are part of Undo, and "Reset note positions" puts everything back in a neat column.
- **Detail Notes: smoother and nicer to use (1.20.0):** zoom now glides and is limited to a sensible range; antialiasing is paused while you pan or zoom so big details stay fluid; on-canvas buttons for zoom in, zoom out and fit, with the zoom percentage; an "Updating..." badge while the drawing is redrawn, and the redraw waits until you let go of the mouse. Dragging a note now shows a live dashed leader to its spot, and note highlights have rounded corners. Compact toolbar buttons, slimmer scroll bars, striped note list, a wider drag handle between drawing and list, and the checks under the list are folded to two lines (hover for the rest).
- **South African products in the catalog (1.19.0):** three new groups in the spec picker, 32 specifications that name real products and say "or similar approved". **Insulation:** IsoBoard (cavity wall 30 mm, nail-up ceiling 30 mm, over purlin 40 mm, inverted roof 50 mm, under floor / foundation perimeter 25 mm, over rafter and truss, surface bed), Isotherm and Aerolite glasswool. **Waterproofing (a.b.e.):** abeproof liquid membrane, super laycryl, peel and stick membrane, Mariseal 250, Duraslurry, brixeal, wallseal, dura proof cem block, silvakote eco, duraroof acrylic roof paint, bituseal Plastic, flexothane 27 and dura grout GP. **Boards, cement and masonry:** Nutec fibre-cement, Rhinoboard and Gyproc, Corobrik face and plaster brick, PPC / AfriSam cement, TAL / Ardex adhesive, Plascon / Dulux paint. Typing "isoboard" or "abe waterproofing" in the picker also writes a note. Thicknesses are only the ones the maker lists; the rest say "per manufacturer's spec". Insulation notes still pick up the XA minimum R-value for your climate zone. Please check the current data sheet and Agrement certificate before specifying.
- **Detail Notes: drag notes, batch folder, XA R-values (1.18.0):**
  - **Drag a note** by its text on the drawing to put it where you want; its leader follows. Positions are saved with the detail and are part of Undo. "Auto-arrange notes" puts them back in a column. To move the drawing itself, drag empty space.
  - **Batch: whole folder** writes the standard notes for every detail in a folder, saves each noted drawing and a notes schedule PDF, and keeps what you already did on details you opened before.
  - **Energy XA link:** inside the suite, insulation notes now carry the minimum total R-value for your climate zone (roof / ceiling, masonry wall or light-weight wall) from the Energy (XA) tab, for example "min. total R-value 3.7 m2K/W for the roof / ceiling (SANS 10400-XA, climate zone 1)". Check that the zone on the Energy tab is right.
- **Detail Notes: tested on your real details, remembers your choices (1.17.0):** I ran it on D-6, D-21, D-22, D-23 and D-24 from your Desktop and fixed what showed up: "Cut Stone" was getting a concrete note; a thin solid fill was called "10 mm concrete"; a 595 mm concrete part was written as a slab (now a foundation note, flagged VERIFY). The thickness check also caught a real mismatch in D-6 (insulation named 135 mm but drawn 70 mm). New: when you choose a note for a material name such as AR-SAND or ANSI31, tick "Remember this note" and it is used automatically in every later detail.
- **Detail Notes: references, checks, templates, undo, schedule (1.16.0):**
  - **Reference column** in the notes list: each note shows the SANS 10400 part (and the NHBRC Home Building Manual where it applies) for its group. These are part-level references only, never clause numbers: confirm the clause in the current edition. A group with no confident reference says "no reference".
  - **Checked by you:** "Approve this wording" in the spec picker, or "Mark selected as checked" in the list, gives a note a green tick everywhere. Edit the wording and the tick goes, so only text you have verified shows as approved.
  - **Checks under the list:** warns when a note starts with a thickness that does not match the drawing, when two notes say the same thing, lists parts that still have no note, VERIFY items, and how many notes you have approved.
  - **Templates:** pick a common detail (parapet with concrete coping, slab-on-ground at the wall, window head and cill, pitched roof at the eaves, door threshold, garden / retaining wall), then click its parts in turn; each note is written for you. Right-click skips a step.
  - **Undo / redo for everything** (Ctrl+Z / Ctrl+Y): choosing or removing a note, editing its wording, your own elements, recoloured fills and Auto notes.
  - **Notes schedule (PDF):** a one-page table of the notes with material, reference and checked / not checked, with the competent-person disclaimer.
  - Retaining wall and garden wall coping wording corrected.
- **Detail Notes: easier to move around and select (1.15.0):** drag with the left mouse button to move the drawing in any mode (no more switching to Pan), wheel zooms, F or the Fit button shows the whole detail. Click a note on the drawing to select it (it turns yellow, and its row in the list is selected too); Ctrl+click adds more; Shift+drag selects every note in a box; Ctrl+A selects all; Esc clears. Selecting rows in the list highlights the same notes on the drawing and scrolls to them. Delete (on the drawing or in the list) removes all selected notes from both. Double-click a note on the drawing to change its spec.
- **Detail Notes: type it and the note writes itself (1.14.0):** in the spec picker, just type what the part is (for example "concrete coping", "stone cill", "damp proof course", "50 x 50 purlin"). The first line of the list, "Write it from what I typed", builds the full detailed note: coping gets drip grooves (throatings) and a fall to the roof side, cills get a drip and a slope, slabs get DPM and mesh, and so on. Press Enter to use it, or edit the wording. If you have an API key set up, a "Write it with AI" button asks Claude to write the note from your words. The catalog grew to 461 specifications in 31 groups (foundations, waterproofing, roof falls, flashings, windows and doors, wet areas, drainage, electrical, paving, fencing and more). Please check the wording against your office standard and SANS before issuing drawings.
- **Detail Notes cleaned up (1.13.0):**
  - Fixed: clicking a part of the detail did nothing (clicks snapped to corner points instead of the part itself).
  - The detail shows in house colours (red brick with real bricks, green concrete, pink insulation) as soon as it opens, again.
  - One simple row: "Auto note everything" for all notes at once, or "Click a part and choose its spec" for manual work. The drawing tools (roof sheet, purlin, fill box, line, note, edit fill, delete) are hidden under "More tools".
  - The catalog now has stone, coping and cladding (287 specs), and the picker pre-selects the option that matches the material name and size.
- **Site plan sheets (1.12.0):** Coverage & FAR has a new button, "Site plan sheets", that saves small PDFs with no cover page: one for each block (its footprint, levels, floor area, coverage and FAR on the stand) and one for all the blocks together (with the carport roofs and both results). Each page is cut to the size of its content so it can be placed straight onto the site plan.
- **Detail Notes redesigned (1.11.0):** nothing is added automatically any more. Open a detail, click a part of it (concrete, brick, insulation, timber...) and choose its specification from a built-in catalog of 268 SA specifications in 18 groups (slabs 85 to 255 mm, purlins 76 x 50 / 50 x 50 / 38 x 38 and more, insulation, roof covering, walls, ceilings, gutters, steel, stairs...). The thickness measured from the drawing pre-selects the closest option. Search the whole catalog, edit the wording, and save your own wording under "My specs". Your choices are kept with the detail and come back when you reopen it. Double-click a note in the list to change its spec. The Detail workspace is now the first tab and the settings are on the second ("Setup"). "Draw missing elements" is off by default, and "Suggest notes for everything" is optional.
- **Detail Notes improved (1.10.0):**
  - Numbered callouts: tick "Number the notes" and each callout carries the same number as the saved notes list.
  - Editing: Redo button, Ctrl+Z / Ctrl+Y, Esc back to Pan, and Undo now also brings back something you deleted.
  - Draws more missing parts to SA practice: DPC in the wall, wall plate on the highest wall, and 135 mm ceiling insulation (wall ties and fascia are still added by hand).
  - Better note text: when a material name has no size, the thickness is measured from the drawing (to the nearest 5 mm) and the note is flagged VERIFY.
- **Detail Notes (1.9.1):** an element the tool draws itself (for example purlins) no longer gets a second callout when the same note is already on the drawing.
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
