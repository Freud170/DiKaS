; Inno-Setup-Skript für den DiKaS-Installer.
; Wird von packaging\bauen.ps1 aufgerufen (dort werden Version und Pfade übergeben).

#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef Quelle
  #define Quelle "..\build\dist\DiKaS"
#endif
#ifndef Ausgabe
  #define Ausgabe "..\build\installer"
#endif

[Setup]
AppId={{6C2F3D8E-4B1A-4E7C-9D2B-8A1F5E3C7D90}
AppName=DiKaS
AppVersion={#Version}
AppVerName=DiKaS {#Version}
AppPublisher=DiKaS
; Installation nur für den angemeldeten Benutzer – keine Administratorrechte nötig
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\DiKaS
DefaultGroupName=DiKaS
DisableProgramGroupPage=yes
OutputDir={#Ausgabe}
OutputBaseFilename=DiKaS-Setup-{#Version}
SetupIconFile=dikas.ico
UninstallDisplayIcon={app}\DiKaS.exe
UninstallDisplayName=DiKaS {#Version}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Laufendes DiKaS vor dem Update schließen lassen
CloseApplications=yes

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Verknüpfung auf dem Desktop anlegen"; GroupDescription: "Zusätzliche Verknüpfungen:"

[Files]
Source: "{#Quelle}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\DiKaS"; Filename: "{app}\DiKaS.exe"
Name: "{group}\DiKaS deinstallieren"; Filename: "{uninstallexe}"
Name: "{userdesktop}\DiKaS"; Filename: "{app}\DiKaS.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DiKaS.exe"; Description: "DiKaS jetzt starten"; Flags: nowait postinstall skipifsilent

; Hinweis: Die Vereinsdaten liegen getrennt in %LOCALAPPDATA%\DiKaS\daten und bleiben bei
; Updates und bei der Deinstallation erhalten.
