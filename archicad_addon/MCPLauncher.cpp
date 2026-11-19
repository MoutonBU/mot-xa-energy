// MCP Tools launcher: adds  MCP Tools > Open MCP Architecture & Interiors  to Archicad's menu bar.
// It only starts the separate program (path read from %APPDATA%\MCP_XA_Energy\app_path.txt, written by the program
// when VIP mode is on). It does not read or change the Archicad model; the program does that through the JSON link.
// STATUS: source only. Not built or tested yet. Build it with the Archicad API Development Kit that matches your Archicad.
#include "APIEnvir.h"
#include "ACAPinc.h"
#include <fstream>
#include <string>
#ifdef _WIN32
#include <windows.h>
#include <shellapi.h>
#endif

static const short kMenuResID = 32500;
static const short kStrResID  = 32510;

static GSErrCode MenuHandler (const API_MenuParams* params)
{
	if (params->menuItemRef.menuResID == kMenuResID && params->menuItemRef.itemIndex == 1) {
#ifdef _WIN32
		char appdata[MAX_PATH] = {0};
		if (GetEnvironmentVariableA ("APPDATA", appdata, MAX_PATH) > 0) {
			std::ifstream f (std::string (appdata) + "\\MCP_XA_Energy\\app_path.txt");
			std::string path;
			std::getline (f, path);
			if (!path.empty ())
				ShellExecuteA (nullptr, "open", path.c_str (), nullptr, nullptr, SW_SHOWNORMAL);
		}
#endif
	}
	return NoError;
}

API_AddonType __ACDLL_CALL CheckEnvironment (API_EnvirParams* envir)
{
	RSGetIndString (&envir->addOnInfo.name, kStrResID, 1, ACAPI_GetOwnResModule ());
	RSGetIndString (&envir->addOnInfo.description, kStrResID, 2, ACAPI_GetOwnResModule ());
	return APIAddon_Normal;
}

GSErrCode __ACDLL_CALL RegisterInterface (void)
{
	return ACAPI_MenuItem_RegisterMenu (kMenuResID, 0, MenuCode_Tools, MenuFlag_Default);
}

GSErrCode __ACDLL_CALL Initialize (void)
{
	return ACAPI_MenuItem_InstallMenuHandler (kMenuResID, MenuHandler);
}

GSErrCode __ACDLL_CALL FreeData (void)
{
	return NoError;
}
