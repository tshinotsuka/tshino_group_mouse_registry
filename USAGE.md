# セットアップ & 使い方（USAGE）

実験マウス管理 Registry の導入手順と日常コマンド。
（登録簿の設計・運用ルールは `README.md` を参照）

---

## 0. まず確認 — あなたに Python は必要？

| やりたいこと | Python | 必要なもの |
|---|---|---|
| マウス情報の閲覧・編集 | **不要** | Google アカウント（Sheet の共有を受ける） |
| 産仔・購入個体の登録 | **不要** | Sheet の **🐭 Registry** メニュー（下記 A） |
| 手術フォーム（IBL）の生成 | 必要 | Python 環境（下記 B） |
| スナップショット（CSV）＋ git commit | 必要 | Python 環境 + git |

→ **データを触るだけの共同研究者は、このページの A だけ読めば OK**（インストール不要）。

---

## A. Python なしでできること（Google Sheet のみ）

1. 共有された Google スプレッドシート（`tshino_group_mouse_registry`）を開く。
2. 各タブを直接編集（`colony` / `animals` / `procedures` …）。入力はドロップダウンに従う。
3. 繁殖・購入の登録は、メニュー **🐭 Registry** から：
   - **産仔を登録 (add litter)** … 交配 + 産仔 + 各仔を自動採番で追加
   - **購入個体を登録 (add vendor)** … 購入個体を追加
   いずれも **プレビュー → 追加** の 2 段階。`birth_id` は自動で振られます。

> **🐭 Registry の初回認可（各自 1 回）**: 初めて使うとき「承認が必要です」が出たら、Apps Script エディタで **`linesList_`** を実行して許可する（`onOpen` だけでは権限が足りない）。`preview`/`commit` 系の関数は**エディタから直接実行しない**（引数が無く `TypeError` になる）。実際の登録は Sheet のメニューから。
>
> **`PERMISSION_DENIED`（ダイアログが動かない）**: 複数 Google アカウントにログインしていて、**既定アカウント（`/u/0`）と Sheet を開いているアカウントが不一致**なのが原因（通常のセル編集には無関係）。恒久対処は **研究室アカウント専用の Chrome プロファイルを作る**（右上アバター → 追加 → 研究室アカウントだけログイン）か、**研究室アカウントを既定にする**（全アカウントからサインアウト → 研究室アカウントで最初にログイン）。これで常に `/u/0` で一致し、**一度認可すれば以後シークレット不要**で preview/追加(commit) が通る。確認は Sheet の URL が `…/u/0/…` になっていること。
> 各編集者も同様に「専用プロファイル（or 既定アカウント）＋初回認可」を一度やれば使える。組織ポリシーで未確認アプリの認可がブロックされる人は**手入力**でよい（dashboard の next birth_id で採番＋colony 行に `genotype`/`age_weeks` 数式をコピー）。

---

## B. Python 環境（最小・Miniconda）

手術フォーム生成・スナップショットを行う人だけ。所要 10〜15 分（初回のみ）。

### B-1. Miniconda をインストール
- 公式: <https://www.anaconda.com/download/success>（**Miniconda** の節）か <https://docs.conda.io/projects/miniconda/>
- Windows は **「Miniconda3 Windows 64-bit」** をインストール。
- インストール後、スタートメニューの **「Anaconda Prompt」** を開く（以降のコマンドはここで実行）。
- mac / Linux はターミナルでそのまま `conda` が使えます。

### B-2. リポジトリを取得
git がある場合:
```bash
git clone <このリポジトリのURL>
cd tshino_group_mouse_registry
```
git が無い場合: GitHub の「Code → Download ZIP」で取得して展開し、そのフォルダへ `cd`。

### B-3. 環境を作成（依存をまとめて導入）
```bash
conda env create -f environment.yml
conda activate mouse_registry
```
> conda を使わない場合: `python -m pip install -r requirements.txt`（ただし環境分離のため conda 推奨）。

### B-4. 動作確認
```bash
python scripts/check_registry.py snapshots
```
`RESULT: PASS` が出れば OK（`snapshots/` が空ならタブが無い旨が出るだけで問題なし）。

> 以降、**必ず `conda activate mouse_registry` してから `python ...`** で実行。Windows の `py` ランチャは別の Python を指すので使わないこと。

---

## C. 日常コマンド

いずれも、まず Google Sheet を **ファイル → ダウンロード → Microsoft Excel (.xlsx)** で書き出してから、その .xlsx の**実際のパス**を渡します。

### C-1. 手術フォームを作る
```bash
python scripts/make_surgery_form.py "<DLした.xlsx>" <procedure_id>
# 例:
python scripts/make_surgery_form.py "%USERPROFILE%\Downloads\tshino_group_mouse_registry.xlsx" pr-ts290-01
```
- 出力は `output\surgery_<procedure_id>.docx`（自動作成）。
- 充填: MouseID / Sex / 手術時週齢 / 日付 / Anesthesia(＋route) / Surgery Type / site1 座標 / Analgesia(＋route)。
- 体重・時刻・チェックリスト・site2・R/L は手書き欄として残ります。

### C-2. スナップショット（CSV）を取って commit
```bash
# 書き出し + 整合チェックのみ（commit しない）
python scripts/snapshot.py "<DLした.xlsx>"

# チェックを通したら git commit まで
python scripts/snapshot.py "<DLした.xlsx>" --commit -m "snapshot before 0615 analysis run"
```
- `snapshots/*.csv` を更新 → **commit 前に `check_registry` がゲート**として走り、`RESULT: FAIL` なら commit されません（Sheet を直して再エクスポート）。
- `age_weeks` 等の TODAY() 揮発列は自動除外（diff を安定させるため）。
- `--strict` で warning も失格扱い。

### C-3. 整合チェックだけ実行
```bash
python scripts/check_registry.py snapshots          # CSV スナップショットを検査
python scripts/check_registry.py "<DLした.xlsx>"    # xlsx を直接検査
```

> **解析 metadata（`subject`）への充填**は registry repo の操作ではない。解析側 repo
> `in_vivo_water_imaging_brain` の `registry_to_metadata.py` が、ここで作った `snapshots/*.csv` を
> `--project-id` で絞って dataset の `metadata.yaml` に流す（既定 dry-run・`--write` で空欄のみ）。
> 詳細は解析 repo を参照（cross-repo は名前参照）。

---

## D. つまずきやすい点

- **`No module named ...`**: 環境を activate していない／その環境に未導入。`conda activate mouse_registry` を確認し、必要なら `pip install -r requirements.txt`。
- **`py` と `python` の取り違え**: 必ず `conda activate` 後の **`python`** を使う（`py` は別 Python）。
- **`ファイルが見つかりません`**: xlsx は**実在するフルパス**で渡す（`"...xlsx"` は例のプレースホルダ。置き換える）。
- **PowerShell の `>>`**: 行頭に出たらコマンドの貼り付けミス。`Ctrl+C` で通常プロンプトに戻して貼り直す。
- **正本は Google Sheet**。`*.xlsx` と `output/` は git 管理外（`.gitignore`）。版管理されるのは `snapshots/*.csv`。CSV を直接編集しないこと（編集は Sheet で）。

---

## E. 困ったら
- 整合エラーの内容は `check_registry` の出力（`[ERROR]`/`[WARN]`）を見る。
- 仕様・タブ定義・ID 規則は `README.md`。
