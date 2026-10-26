; ComfyNexus v1.3.3 安装包脚本（Inno Setup 7）
; 用法: ISCC.exe build_installer.iss
; 输入: dist\ComfyNexus\（PyInstaller COLLECT 产物）
; 输出: 发布包\ComfyNexus-v1.3.3-setup.exe

#define MyAppName "ComfyNexus"
#define MyAppVersion "1.3.3"
#define MyAppPublisher "ComfyNexus"
#define MyAppExeName "ComfyNexus.exe"

[Setup]
; AppId 必须是合法 GUID（8-4-4-4-12 位十六进制），否则编译直接报错。
; 这个值决定「同系列安装包互相覆盖升级」的身份，一经发布不要再改。
AppId={{A3E32D21-88B2-4C95-8734-826864298CE1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
; 默认安装到 D:\Program\ComfyNexus\（目录不存在时安装器会自动逐级创建）
; 用户在「选择目标位置」页可直接输入路径，或点「浏览…」弹窗选择文件夹
DefaultDirName=D:\Program\ComfyNexus
; 一律使用上面的默认路径，不再继承历史安装目录，避免旧版本残留路径覆盖默认值
UsePreviousAppDir=no
; 必须显示「选择目标位置」页，允许用户自定义安装目录
DisableDirPage=no
; 目标目录已存在且非空时给出提示（不阻止安装）
DirExistsWarning=auto
DefaultGroupName={#MyAppName}
; 应用本身需要管理员权限（硬件监控），安装器保持一致
PrivilegesRequired=admin
OutputDir=D:\Downloads\ComfyNexus\发布包
OutputBaseFilename=ComfyNexus-v{#MyAppVersion}-setup
SetupIconFile=icon.ico
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; 安装包自身的版本资源（资源管理器「属性」面板可见）
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
UninstallDisplayIcon={app}\{#MyAppExeName}
; 卸载时保留用户数据目录（data/logs/config/cache）
UninstallFilesDir={app}\uninst

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
; 主程序与全部运行时（递归整个 COLLECT 产物）
; Excludes: mtab —— Git for Windows 的 etc/mtab 是指向 /proc/mounts 的 WSL reparse
; point，Windows 安装器无法读取也无法复制，git 本身完全用不到它，直接排除。
Source: "dist\ComfyNexus\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "mtab"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallDelete]
; 卸载后清理运行时生成的空壳目录（用户数据 data/logs/config/cache 默认保留）
Type: filesandordirs; Name: "{app}\uninst"
