; ComfyNexus v1.3.5 安装包脚本（Inno Setup 7）
; 用法: ISCC.exe build_installer.iss
; 输入: dist\ComfyNexus\（PyInstaller COLLECT 产物）
; 输出: 发布包\ComfyNexus-v1.3.5-setup.exe

#define MyAppName "ComfyNexus"
#define MyAppVersion "1.3.5"
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
; 卸载器自身放在 {app}\uninst，卸载结束时由 [UninstallDelete] 清掉
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
; 1) 卸载器自身目录（含 unins000.exe/.dat）
Type: filesandordirs; Name: "{app}\uninst"
; 2) 仅当 {app} 已经空了才移除目录本身 —— 用户把程序装进混用目录时，
;    别人还有文件在里面，这一步会自动跳过（dirifempty 只删空目录）
Type: dirifempty; Name: "{app}"

[Code]
#include "scripts\uninstall_clear_data.issinc"

var
  CNX_ClearDataApproved: Boolean;
  CNX_ClearDataReport: String;

{ 卸载器命令行里是否有某个参数（供自动化/无人值守显式指定，忽略大小写） }
function CNX_CmdParamExists(const Param: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Param) = 0 then
    begin
      Result := True;
      Exit;
    end;
end;

{ ────────────────────────────────────────────────────────────────────────
  卸载开始时询问「是否清除所有数据」
  ────────────────────────────────────────────────────────────────────────
  · 默认按钮是「否」，用户手快直接回车也不会删数据
  · 静默卸载（/SILENT、/VERYSILENT）一律按「否」处理，符合无人值守预期
  · 自动化脚本可用 /CLEARDATA 显式要求清除
}
function InitializeUninstall(): Boolean;
var
  Answer: Integer;
begin
  CNX_ClearDataApproved := False;
  CNX_ClearDataReport := '';

  if UninstallSilent() then
  begin
    if CNX_CmdParamExists('/CLEARDATA') then
      CNX_ClearDataApproved := True;
    Result := True;
    Exit;
  end;

  if CNX_CmdParamExists('/CLEARDATA') then
  begin
    CNX_ClearDataApproved := True;
    Result := True;
    Exit;
  end;

  Answer := MsgBox(
    '是否同时清除 ComfyNexus 的所有本地数据？' + #13#10 + #13#10 +
    '选择「是」将删除安装目录下由本程序生成的内容：' + #13#10 +
    '    配置文件（含已添加的 ComfyUI 环境与模型路径记录）' + #13#10 +
    '    提示词、画廊图片、对话数据库' + #13#10 +
    '    插件、模型库、下载缓存、运行日志' + #13#10 + #13#10 +
    '无论选择哪一项，以下内容都不会被删除：' + #13#10 +
    '    · 您已配置的 ComfyUI 环境目录与模型目录' + #13#10 +
    '    · 安装目录中其它软件的文件' + #13#10 + #13#10 +
    '选择「否」则仅卸载程序本体，保留全部本地数据，下次安装可直接沿用。',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2);

  CNX_ClearDataApproved := (Answer = IDYES);
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if CNX_ClearDataApproved then
    begin
      { 此刻安装目录里的程序文件还在，指纹校验才有依据；
        必须在卸载器自己开始删文件之前（usUninstall）执行 }
      CNX_ClearDataReport := CNX_ClearAppData(ExpandConstant('{app}'));
      Log(CNX_ClearDataReport);

      { 排一个「脱离本进程」的收尾脚本：卸载器删不掉正在运行的自己
        （uninst\unins000.exe 被占用 → 目录非空 → dirifempty 失效），
        独立目录卸载后会残留一个只装着卸载器的 uninst。
        该脚本等卸载器退出后再清 uninst，并且只有安装目录已经空了才删目录本身，
        所以混用目录依旧安全。必须用 ewNoWait 异步启动，否则会挡住我们退出。 }
      if CNX_ScheduleUninstallerCleanup(ExpandConstant('{app}')) then
        Log('[ComfyNexus] 已排入卸载器收尾清理脚本')
      else
        Log('[ComfyNexus] 收尾清理脚本生成失败，uninst 目录可能残留');
    end;
  end

  { 注意：绝不能在 usPostUninstall 里同步清 uninst 目录！
    卸载器还需往该目录写 _unins-done.tmp 等收尾标记，提前清空会让它
    在收尾阶段崩溃，导致「程序本体已删但收尾没做完」的坏状态
    （实测：日志停在 Creating "_unins-done.tmp"，exe/version.json 反而不删）。
    清理交给上面那个外部脚本，它在卸载器进程退出之后才动手。 }
end;
