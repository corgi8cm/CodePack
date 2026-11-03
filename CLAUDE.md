# CodePack — 開發規範

CodePack 把程式專案(主要是 C++ / Python)打包成單一文字檔,方便貼給網頁版 AI 閱讀。

## 硬性規範(每次修改都必須遵守)

1. **完全離線**:執行期不得有任何網路連線。`codepack/` 內不得 import `socket`、`urllib`、`http`、`requests`、`tiktoken` 等會連網的模組。`tests/core/test_offline.py` 會檢查。
2. **core 與 GUI 分離**:
   - `codepack/core/`:掃描、過濾、依賴分析、輸出格式化、token 估算。**不得 import PySide6 或任何 GUI 套件**(`tests/core/test_offline.py` 檢查)。
   - `codepack/cli.py`:命令列介面,只呼叫 core。
   - `codepack/gui/`:PySide6 介面,只呼叫 core;業務邏輯(勾選連動、規則判斷)一律放 core。
3. **跨平台**:Windows(主要)與 Linux。路徑在 core 內部一律以 POSIX 風格的相對路徑字串(`"src/a.cpp"`)表示;只有實際讀檔時才轉成 `Path`。
4. **設定檔(preset)用 JSON**,帶 `schema_version`,新增欄位要給預設值以相容舊檔。
5. **測試**:pytest。core 每個模組都要有測試;新增 core 功能必須同時加測試並執行通過。
6. Python 3.10+;相依只有 `pathspec`、`PySide6`(GUI)。新增相依前要先確認可離線運作且能被 PyInstaller 打包。

## 架構

```
scan_project ─▶ ScanResult ─▶ (Collector) ─▶ (Transforms) ─▶ Formatter ─▶ (Splitter) ─▶ PackResult
```

| 模組 | 職責 |
|---|---|
| `core/models.py` | `FileEntry`、`DirEntry`、`ScanResult`、`ExcludeReason` |
| `core/rules.py` | `RuleSet`(include/exclude glob、gitignore 開關、檔案大小上限)、`GitignoreStack`(巢狀 .gitignore) |
| `core/binary.py` | `is_binary()`:副檔名 + 前 8KB 內容判斷 |
| `core/reader.py` | `read_text()`:編碼回退 utf-8 → utf-8-sig → cp950 → latin-1 |
| `core/languages.py` | 副檔名 → 程式碼區塊語言 |
| `core/tokens.py` | `TokenEstimator` 協定、`CharTokenEstimator`(ASCII ÷4、CJK 每字 1) |
| `core/scanner.py` | `scan_project()`,支援 progress / cancel 回呼 |
| `core/selection.py` | `Selection`:勾選狀態,資料夾勾選連帶子項目(不含被排除者) |
| `core/tree_render.py` | `render_tree()` |
| `core/formatters/` | `Formatter` ABC + markdown / xml / plain,以註冊表 `get_formatter()` 取用 |
| `core/packer.py` | `PackOptions`、`PackResult`(`parts: list[str]`,為分段預留)、`build_pack()` |
| `core/preset.py` | `Preset` JSON 讀寫、內建 preset(`core/presets/*.json`)、使用者 preset 目錄 |

CLI 剪貼簿使用 `codepack/clipboard.py`(Windows 走 ctypes Win32 API,Linux 走 wl-copy/xclip/xsel),不依賴 GUI 套件。

### GUI(`codepack/gui/`)
| 模組 | 職責 |
|---|---|
| `app.py` | `main()` 進入點(`codepack-gui`) |
| `main_window.py` | 工具列、三欄 QSplitter、狀態列;QSettings 記住上次專案/視窗大小 |
| `file_tree_model.py` | `FileTreeModel(QAbstractItemModel)`,直接讀 core 的 `ScanResult` + `Selection` |
| `file_tree_panel.py` | 搜尋(`QSortFilterProxyModel` 遞迴過濾)+ 樹狀檢視 |
| `rules_panel.py` | 規則與輸出選項;規則變更 debounce 後觸發重新掃描 |
| `preview_panel.py` | 預覽、token 上限進度條、複製/另存 |
| `workers.py` | `ScanJob` / `PackJob`(QRunnable),以 job id 丟棄過期結果 |

GUI 測試用 pytest-qt,`tests/gui/conftest.py` 設定 `QT_QPA_PLATFORM=offscreen`;MainWindow 測試要傳入暫存的 `QSettings` 與 `preset_dir`,不可寫到使用者真實設定。

### 規則語意
- include 為空 = 全部納入;exclude 優先於 include;語法皆為 gitignore 風格(pathspec `gitwildmatch`)。
- `.git/` 一律跳過。被忽略的目錄不往下掃描,以單一 `DirEntry(pruned=...)` 呈現。
- 被排除的檔案仍出現在 `ScanResult` 中(GUI 顯示灰色),使用者可手動勾選強制納入,但 `BINARY` 不可勾選。勾選資料夾時不會連帶勾選被排除的檔案。

## 預留擴充(尚未實作)
- 第二階段:`core/deps/`(`DependencyResolver`:自寫 #include 解析 → g++ -MM → MSVC /showIncludes;`compile_commands.json`)、`PackOptions.preamble` 前置提示詞、`core/scanners/`(`ContentScanner` 機密掃描)。
- 第三階段:`core/collectors/`(git 變更檔)、`PackOptions.max_tokens_per_part` 自動分段、`core/transforms/`(移除註解)。

## 常用指令
```bash
python -m venv .venv && .venv\Scripts\activate   # Linux: source .venv/bin/activate
pip install -e .[dev]
pytest
python -m codepack pack <dir> -f markdown -o out.md
codepack-gui
```
