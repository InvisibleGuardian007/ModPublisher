; 网易模组发布器 正式安装包（Inno Setup 6）
; 编译：ISCC.exe installer\ModPublisher.iss → dist\ModPublisher-*-setup.exe

#define MyAppName "网易模组发布器"
#define MyAppVersion "26.11.11"
#define MyAppPublisher "InvisibleGuardian007"
#define MyAppURL "https://github.com/InvisibleGuardian007/ModPublisher"
#define MyAppExeName "网易模组发布器.exe"

[Setup]
AppId={{A7C3E1D0-6F5B-4E0A-9C7D-1E2F3A4B5C6D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases/latest
; 按用户安装：无需管理员权限，目录与热更新就地替换兼容
DefaultDirName={localappdata}\Programs\ModPublisher
PrivilegesRequired=lowest
DefaultGroupName={#MyAppName}
SetupIconFile=..\docs\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\dist
OutputBaseFilename=ModPublisher-{#MyAppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式(&D)"; GroupDescription: "附加任务："; Flags: checkedonce

[Files]
Source: "..\dist\网易模组发布器.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\icon.png"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载{#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行{#MyAppName}"; Flags: nowait postinstall skipifsilent
