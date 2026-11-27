# 部署到手机：装包 + 注入第二个智能体 + 注入群聊会话。
# 用法：pwsh -File deploy.ps1
# 前提：dist\app-debug.apk 和 dist\config.withkey.json 已就绪。

$ErrorActionPreference = "Continue"
$adb = "C:\Users\Administrator\AppData\Local\Microsoft\WinGet\Packages\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe\platform-tools\adb.exe"
$dist = "F:\twobody-app\dist"
$pkg = "com.castrite.twobody"

# 本机 adb 地址：放 scripts/local.ps1（不进 git）
$adbAddr = ""
$localCfg = Join-Path $PSScriptRoot "local.ps1"
if (Test-Path $localCfg) { . $localCfg }

$d = (& $adb devices 2>&1) -join "`n"
if ($d -notmatch "`tdevice" -and $adbAddr) {
    & $adb connect $adbAddr | Out-Null
    Start-Sleep -Seconds 3
}

"== 装包 =="
& $adb uninstall $pkg | Out-Null
& $adb install "$dist\app-debug.apk" | Select-Object -Last 1

& $adb shell "run-as $pkg mkdir -p files" | Out-Null
& $adb push "$dist\config.withkey.json" /data/local/tmp/cfg.json | Out-Null
& $adb shell "run-as $pkg cp /data/local/tmp/cfg.json files/config.json" | Out-Null

"== 首次启动（建 a1）=="
& $adb shell am start -n "$pkg/.MainActivity" | Out-Null
Start-Sleep -Seconds 14
& $adb shell am force-stop $pkg | Out-Null
Start-Sleep -Seconds 2

"== 注入第二个智能体 =="
cmd /c "`"$adb`" exec-out run-as $pkg cat databases/agents.db > $dist\agents.db"
python -c "import sqlite3; con=sqlite3.connect(r'$dist\agents.db'); n=con.execute('SELECT COUNT(*) FROM agents').fetchone()[0]; con.execute('INSERT INTO agents(name,created_at,last_used_at) VALUES(?,?,?)',('b',0,0)) if n<2 else None; con.commit(); print('agents:', con.execute('SELECT id,name FROM agents').fetchall())"

"== 注入群聊会话 =="
python -c "import sqlite3; p=r'$dist\conversations.db'; con=sqlite3.connect(p); con.execute('CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, agent_ids TEXT NOT NULL, is_group INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)'); con.execute('INSERT INTO conversations(title,agent_ids,is_group,created_at) VALUES(?,?,?,?)',('group','1,2',1,0)); con.execute('PRAGMA user_version=1'); con.commit()"

& $adb push "$dist\agents.db" /data/local/tmp/agents.db | Out-Null
& $adb push "$dist\conversations.db" /data/local/tmp/conversations.db | Out-Null
& $adb shell "run-as $pkg cp /data/local/tmp/agents.db databases/agents.db" | Out-Null
& $adb shell "run-as $pkg cp /data/local/tmp/conversations.db databases/conversations.db" | Out-Null
& $adb shell "run-as $pkg mkdir -p files/agents/a2" | Out-Null
& $adb shell "run-as $pkg cp files/agents/a1/config.json files/agents/a2/config.json" | Out-Null
& $adb shell "run-as $pkg cp files/agents/a1/persona.txt files/agents/a2/persona.txt" | Out-Null

"== 启动 =="
& $adb shell am start -n "$pkg/.MainActivity" | Out-Null
Start-Sleep -Seconds 13
"deploy done"

