# 更新紀錄

版本號遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)。

## 1.0.0 - 2026-11-05
第一個公開版本。

**打包**
- 可勾選的檔案樹、include / exclude 規則(gitignore 語法)、自動套用巢狀 `.gitignore`、跳過二進位檔與過大檔案
- 輸出 Markdown / XML / 純文字，附目錄樹與 token 預估
- 依賴追蹤:Python `import`、C++ `#include`(支援 `compile_commands.json`)
- 只打包 git 變更的檔案，可附上 `git diff`
- 機密遮罩(API key、密碼、私鑰、JWT、連線字串、內部 IP)
- 設定檔(preset)與提問模板，皆可自訂

**套用回答**
- 解析完整檔案格式與 unified diff,預覽 diff 後才寫入
- 寫入前自動備份(git 專案另存 stash 快照),可一鍵還原;自動還原被遮罩的機密

**其他**
- 專案清單：一次記住多個專案並切換，每個專案各自記住設定與勾選
- GUI(PySide6)與 CLI(`codepack`)
- Windows 單檔執行檔 `CodePack.exe` / `codepack-cli.exe`,完全離線
