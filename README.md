# CodePack

把程式專案打包成單一文字檔，方便貼給網頁版 AI(Gemini、ChatGPT、Claude…)閱讀;AI 回答後，再把修改套用回專案。主要針對 C++ 與 Python 專案，完全離線運作。

```
打包 ──▶ 貼給 AI 問 ──▶ 套用回答(預覽 diff、自動備份、可一鍵還原)
```

## 功能
**打包**
- **多專案**:專案清單一次記住多個專案，用下拉選單切換;每個專案各自記住設定檔、規則與勾選的檔案
- 可勾選的檔案樹、包含 / 排除規則(gitignore 風格 glob)、自動套用 `.gitignore`、跳過二進位檔
- 輸出格式:Markdown、XML、純文字，開頭附目錄樹;Token 預估(總量與每個檔案)
- **依賴追蹤**:選一個目標檔，沿著 Python `import` 與 C++ `#include` 只抓相關檔案(會讀 `compile_commands.json` 的 include 路徑)
- **只送 git 變更**:只選變更的檔案，可附上 `git diff`(與 HEAD、某個分支或只看 staged 比較)
- **機密遮罩**(預設開啟):API key、密碼、私鑰、JWT、連線字串、內部 IP 換成 `<REDACTED:…>` 佔位符
- 可要求 AI 用固定格式回答，方便之後套用
- **提問模板**:一鍵複製常用的提問開頭(完整檔案格式、diff 格式、只問問題、除錯、Code review、解釋程式碼),貼到 Gemini 後再改成你的問題;模板可編輯、可新增

**套用回答(回程)**
- 支援兩種格式:`=== FILE: path ===` 包住完整檔案，或 unified diff(行號不準也能靠上下文對上)
- 列出會改到哪些檔案並顯示 diff,確認後才寫入
- 寫入前備份到 `.codepack/backups/`(git 專案另外留一份 `git stash` 快照，不會動到你未提交的修改),可一鍵還原
- 遮罩過的機密會自動還原成原值;保留原檔的換行與編碼(例如 Big5/cp950)

## 安裝
```bash
python -m venv .venv
.venv\Scripts\activate        # Linux: source .venv/bin/activate
pip install -e .[dev]
```
PowerShell 擋下 `Activate.ps1` 時，可以不啟用，直接執行 `.venv\Scripts\codepack-gui`。

## 使用

GUI:
```bash
codepack-gui
```
- 專案：工具列「加入專案…」把資料夾加入清單，之後用「專案」下拉選單切換;「⋯」可重新命名、排序或從清單移除(不會刪檔案)
- 依賴：在檔案樹對檔案按右鍵 →「只選取此檔案及其依賴」
- Git:中欄「選取工具」→「只選取 git 變更的檔案」
- 提問模板：工具列「複製提問模板」直接複製上次用的模板，按旁邊的 ▾ 選其他模板或「管理模板…」
- 套用：工具列「套用回答…」

CLI:
```bash
codepack pack path/to/project -f markdown -o packed.md
codepack pack path/to/project --deps src/main.cpp --reply-format files --copy
codepack pack path/to/project --git-changed --git-base main --git-diff
codepack deps path/to/project src/main.cpp
codepack secrets path/to/project
codepack projects add path/to/project --name engine
codepack projects
codepack pack engine --copy          # 用專案名稱代替路徑
codepack prompt
codepack prompt "修改程式(完整檔案格式)" --copy
codepack apply path/to/project reply.md --dry-run --diff
codepack apply path/to/project reply.md
codepack backups path/to/project
codepack restore path/to/project
```

## 建置 Windows 執行檔
```bash
pip install -e .[build]
python packaging/build.py
```
產出在 `dist/`:
- `CodePack.exe`:GUI,雙擊即可使用(約 34 MB)
- `codepack-cli.exe`:命令列版(約 7 MB),用法同上面的 `codepack` 指令

兩者都是單一檔案，可直接複製到沒有安裝 Python 的電腦使用。建置腳本會檢查 exe 內沒有任何 Qt 網路相關的 DLL。
單檔 exe 啟動時要先解壓到暫存資料夾，第一次開啟會慢幾秒;少數防毒軟體可能誤判未簽章的 PyInstaller 執行檔。

## 開發
```bash
pytest
```
架構與規範見 [CLAUDE.md](CLAUDE.md)。
