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
| `core/packer.py` | `PackOptions`、`PackResult`(`parts: list[str]`,為分段預留;`findings` 為遮罩紀錄)、`build_pack()` |
| `core/preset.py` | `Preset` JSON 讀寫、內建 preset(`core/presets/*.json`)、使用者 preset 目錄 |
| `core/paths.py` | `user_config_dir()`(preset、遮罩金鑰都放這裡) |
| `core/scanners/secrets.py` | `SecretMasker`:API key / 密碼 / 私鑰 / JWT / 連線字串 / 內部 IP → `<REDACTED:kind:hmac8>`;`unmask()` |
| `core/deps/` | `resolve_dependencies()` + `DependencyResolver` 協定;`PythonImportResolver`(ast)、`CppIncludeResolver`(自寫 #include 解析 + `compile_commands.json`) |
| `core/collectors/git.py` | `changed_files()`、`git_diff_text()`(只呼叫本機 `git`) |
| `core/prompts.py` | 提問模板：內建模板 + 使用者模板(`user_config_dir()/prompts.json`,同名覆蓋內建);完整檔案範例沿用 `apply.formats` 的標記，測試確保範例可被 `parse_reply` 解析 |
| `core/apply/` | 回程:`formats`(要求 AI 的回答格式)、`parser`(FILE 區塊 / unified diff)、`patch`(容錯套用 hunk)、`planner`(`plan_changes` / `apply_plan`)、`backup`(備份與還原) |

### 機密遮罩
- placeholder 的 8 碼是以「每台機器隨機金鑰」(`user_config_dir()/mask.key`)計算的 HMAC:同一個值永遠得到同一個 placeholder,但從 placeholder 推不回原值。
- 套用回答時，`plan_changes` 會先用舊檔內容、再用整個專案的檔案重建 placeholder → 原值對照表，自動還原;還原不了的會列為警告。
- 規則順序即優先序(越前面越具體);新增規則時要在 `tests/core/test_secrets.py` 補正反例。測試裡的假金鑰要用字串拼接產生，不要寫成完整字面值。

### 依賴追蹤
- Python:被隱式執行的 package `__init__.py`(例如 `from pkg.mod import x` 會跑 `pkg/__init__.py`)會納入但不往下追(`Dependencies.leaves`),否則會把整個套件拉進來。明確 `import pkg` 或從 `__init__` 匯入名稱時才會追。
- C++:不跑前處理器，所有 `#include` 都算(不看 `#if`)。解析順序:引用檔所在目錄(僅 `""`)→ include 目錄(自動:`""`/`include`/`inc`/`src` + 使用者指定 + `compile_commands.json`)→ 專案內路徑後綴唯一比對。
- 被規則排除的依賴預設不加入，列在 `DependencyResult.skipped`。

### 套用回答(回程)
- 安全：拒絕絕對路徑、`..`、經由連結跳出專案、`.git/`、`.codepack/`。寫入前比對 sha256,檔案在預覽後被改過就拒絕。
- 保留原檔的換行(CRLF)與編碼(例如 cp950)。
- 備份放 `<專案>/.codepack/backups/<id>/`(資料夾內自帶 `.gitignore`),掃描器一律跳過 `.codepack/`。git repo 另外用 `git stash create` + `git stash store` 留一份快照：**不可用 `git stash push`**,那會把使用者未提交的修改移走。

CLI 剪貼簿使用 `codepack/clipboard.py`(Windows 走 ctypes Win32 API,Linux 走 wl-copy/xclip/xsel),不依賴 GUI 套件。

### GUI(`codepack/gui/`)
| 模組 | 職責 |
|---|---|
| `app.py` | `main()` 進入點(`codepack-gui`) |
| `main_window.py` | 工具列、三欄 QSplitter、狀態列;QSettings 記住上次專案/視窗大小 |
| `file_tree_model.py` | `FileTreeModel(QAbstractItemModel)`,直接讀 core 的 `ScanResult` + `Selection` |
| `file_tree_panel.py` | 搜尋(`QSortFilterProxyModel` 遞迴過濾)+ 樹狀檢視 |
| `rules_panel.py` | 分頁：過濾規則 / 輸出選項 / 選取工具(git、依賴);規則變更 debounce 後觸發重新掃描 |
| `preview_panel.py` | 預覽、token 上限進度條、遮罩數量、複製/另存 |
| `prompt_dialog.py` | 提問模板的檢視/編輯/新增/刪除(內建模板可修改或還原預設);工具列「複製提問模板」按鈕複製上次用的模板(記在 QSettings `prompt_template`) |
| `apply_dialog.py` | 貼上 AI 回答 → 變更清單 + diff 預覽 → 勾選套用(備份)→ 還原 |
| `workers.py` | `ScanJob` / `PackJob`(QRunnable),以 job id 丟棄過期結果 |

GUI 測試用 pytest-qt,`tests/gui/conftest.py` 設定 `QT_QPA_PLATFORM=offscreen`;MainWindow 測試要傳入暫存的 `QSettings` 與 `preset_dir`,不可寫到使用者真實設定。`tests/conftest.py` 的 autouse fixture 會把 `APPDATA` / `XDG_CONFIG_HOME` 指到暫存目錄(preset 與遮罩金鑰)。

### 規則語意
- include 為空 = 全部納入;exclude 優先於 include;語法皆為 gitignore 風格(`pathspec.GitIgnoreSpec`)。
- `.git/`、`.codepack/` 一律跳過。被忽略的目錄不往下掃描,以單一 `DirEntry(pruned=...)` 呈現。
- 被排除的檔案仍出現在 `ScanResult` 中(GUI 顯示灰色),使用者可手動勾選強制納入,但 `BINARY` 不可勾選。勾選資料夾時不會連帶勾選被排除的檔案。

## 打包 exe(PyInstaller)
- `python packaging/build.py` → `dist/CodePack.exe`(windowed GUI)與 `dist/codepack-cli.exe`(console,不含 Qt)。設定在 `codepack.spec`,入口在 `packaging/*_entry.py`。
- 工作目錄放系統暫存資料夾(專案在 OneDrive 時 `build/` 會被鎖住導致 `--clean` 失敗)。
- 離線保證：spec 排除 QtNetwork/QML/WebEngine 等模組，並從 binaries 移除會拉進 Qt6Network 的外掛(`imageformats/qpdf`、`qtuiotouchplugin`)。`build.py` 建置後用 pefile 檢查，任何 DLL 是或匯入 `Qt6Network.dll` 就失敗。新增 Qt 模組時要重新跑建置確認。
- 新增執行期需要的資料檔時，要同時加到 `pyproject.toml` 的 package-data 與 spec 的 datas。
- 圖示 `codepack/gui/codepack.ico` 由 `packaging/make_icon.py` 產生。
- 凍結狀態下 CLI 的程式名是 `codepack-cli`(`cli.PROG`)。

## 預留擴充(尚未實作)
- `DependencyResolver` 的 g++ -MM / MSVC /showIncludes 實作。
- `PackOptions.max_tokens_per_part` 自動分段、`core/transforms/`(移除註解)。

## 常用指令
```bash
python -m venv .venv && .venv\Scripts\activate   # Linux: source .venv/bin/activate
pip install -e .[dev]
pytest
python -m codepack pack <dir> -f markdown -o out.md
python -m codepack pack <dir> --deps src/main.cpp --reply-format files --copy
python -m codepack apply <dir> reply.md --dry-run
codepack-gui
```
