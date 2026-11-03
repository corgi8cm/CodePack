# CodePack

把程式專案打包成單一文字檔,方便貼給網頁版 AI(Gemini、ChatGPT、Claude…)閱讀。主要針對 C++ 與 Python 專案,完全離線運作。

## 功能(MVP)
- 選擇專案資料夾,以可勾選的檔案樹挑選要打包的檔案
- 包含 / 排除規則(gitignore 風格 glob,每行一條)
- 自動套用 `.gitignore`、自動跳過二進位檔
- 輸出格式:Markdown、XML、純文字,開頭附目錄樹
- Token 預估(總量與每個檔案)
- 複製到剪貼簿、另存檔案
- 設定檔(preset)以 JSON 儲存

## 安裝
```bash
python -m venv .venv
.venv\Scripts\activate        # Linux: source .venv/bin/activate
pip install -e .[dev]
```

## 使用

GUI:
```bash
codepack-gui
```

CLI:
```bash
codepack pack path/to/project -f markdown -o packed.md
codepack pack path/to/project --exclude "tests/" --include "*.cpp" --include "*.h" --copy
codepack tree path/to/project
codepack stats path/to/project
```

## 開發
```bash
pytest
```
架構與規範見 [CLAUDE.md](CLAUDE.md)。
