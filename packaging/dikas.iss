; Inno-Setup-Skript für den DiKaS-Installer.
; Wird von packaging\bauen.ps1 aufgerufen (dort werden Version und Pfade übergeben).
;
; Update-Verhalten: Ist DiKaS schon installiert, fragt der Installer kurz nach,
; deinstalliert die alte Version still und installiert die neue in denselben Ordner.
; Die Vereinsdaten (%LOCALAPPDATA%\DiKaS\daten) werden dabei nie angefasst.
; Stiller Aufruf aus DiKaS heraus („Update installieren …“):
;   DiKaS-Setup-x.y.z.exe /SILENT /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS /NORESTART /SP-
; danach startet DiKaS automatisch neu.

#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef Quelle
  #define Quelle "..\build\dist\DiKaS"
#endif
#ifndef Ausgabe
  #define Ausgabe "..\build\installer"
#endif
#define AppGuid "6C2F3D8E-4B1A-4E7C-9D2B-8A1F5E3C7D90"

[Setup]
AppId={{{#AppGuid}}
AppName=DiKaS
AppVersion={#Version}
AppVerName=DiKaS {#Version}
AppPublisher=DiKaS
; Installation nur für den angemeldeten Benutzer – keine Administratorrechte nötig
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\DiKaS
DefaultGroupName=DiKaS
DisableProgramGroupPage=yes
; Bei einem Update keine Ordnerauswahl und keine Zusammenfassung – einfach durchlaufen
DisableDirPage=auto
DisableReadyPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
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
; Laufendes DiKaS vor dem Update schließen
CloseApplications=force
RestartApplications=no

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
; Normale Installation: Häkchen „DiKaS jetzt starten“ am Ende
Filename: "{app}\DiKaS.exe"; Description: "DiKaS jetzt starten"; Flags: nowait postinstall skipifsilent
; Stilles Update aus DiKaS heraus: danach automatisch wieder starten
Filename: "{app}\DiKaS.exe"; Flags: nowait; Check: WizardSilent

[Code]
const
  DeinstallSchluessel = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppGuid}}_is1';

var
  AlteVersion: String;
  AlterDeinstaller: String;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if RegQueryStringValue(HKCU, DeinstallSchluessel, 'UninstallString', AlterDeinstaller) then
  begin
    if not RegQueryStringValue(HKCU, DeinstallSchluessel, 'DisplayVersion', AlteVersion) then
      AlteVersion := '(unbekannt)';
    if not WizardSilent() then
      Result := MsgBox(
        'DiKaS ' + AlteVersion + ' ist bereits installiert.' + #13#10#13#10 +
        'Die alte Version wird deinstalliert und durch Version {#Version} ersetzt.' + #13#10 +
        'Deine Daten und Einstellungen bleiben dabei erhalten.' + #13#10#13#10 +
        'Fortfahren?', mbConfirmation, MB_YESNO) = IDYES;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Rueckgabe: Integer;
begin
  { Alte Version still entfernen, bevor die neuen Dateien kopiert werden }
  if (CurStep = ssInstall) and (AlterDeinstaller <> '') then
    Exec(RemoveQuotes(AlterDeinstaller), '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '',
         SW_HIDE, ewWaitUntilTerminated, Rueckgabe);
end;
