# 実験マウス管理 Registry

Group 内のマウスを **husbandry（繁殖・維持）** と **experiment（実験）** の 2 層で一元管理するための登録簿。
編集は Google Sheets（正本）、整合性は Python（`check_registry.py`）、版管理は CSV スナップショット + git。
セットアップは USAGE.md 参照

---

## 1. 全体フロー

```
 [繁殖]  add_litter.py ─┐
                        ├─►  colony (birth_id)  ──┐
 [購入]  add_vendor.py ─┘     ※全個体・由来       │  genotyping: gt_app/ps1/aqp4/cagegfp に +/-
                                                   │
                                   実験に投入する個体だけ
                                                   ▼
                         animals (mouse_id) ──► enrollments (project × role)
                              │  birth_id で colony と連結         ▲
                              ▼                                   │ project は実験単位
                         procedures (手術/撮影…)  ──► make_surgery_form.py（IBL フォーム）
                              │
                              ▼
        区切り/解析前: 全タブ → CSV → check_registry.py → git commit（private group repo）
```

- **husbandry 層**＝`colony`, `matings`（全個体）
- **experiment 層**＝`animals`, `enrollments`, `procedures`（実験投入分）
- 連結は **`animals.birth_id → colony.birth_id`** の 1 本だけ。

---

## 2. ID 規則（不変キー・属性は埋めない）

| キー | 形式 | いつ振る | 意味 |
|---|---|---|---|
| `birth_id` | `<line_id>-<番号>`（例 `wt-44`, `5xfad_aqp4ko-12`） | 出生/搬入時（colony） | 由来。系統内連番。 |
| `mouse_id` | `ts<連番>` / `sk<連番>`（例 `ts301`, `sk12`） | 実験投入時（animals） | 実験個体。人ごとの prefix で同時採番衝突を回避＋来歴。 |

原則:
- **ID に line/genotype/project/role を埋め込まない**（変わる/多値になる属性は列に持つ。ID は不透明な連番）。
- **小文字・ゼロ詰めしない・再採番しない**（一度振ったら不変。参照が腐らない）。
- 1 物理マウス = 1 `birth_id`、実験に使えば = 1 `mouse_id`。再利用は `enrollments`（mouse_id × project）で表現し、`animals` に重複行を作らない。

---

## 3. タブ一覧

| タブ | 主キー | 役割 |
|---|---|---|
| `dashboard` | — | 次の birth_id / mouse_id、系統別 colony 数・最若♂♀週齢、各種カウント（全て自動計算） |
| `vocab` | — | 制御語彙（ドロップダウンの元） |
| `lines` | `line_id` | 系統定義。`assays` に系統別 PCR（例 5xfad=`app,ps1`） |
| `colony` | `birth_id` | 全個体の husbandry 台帳。性別・dob・per-assay genotype・status・親など |
| `matings` | `mating_id` | 交配 → 産仔の記録（集計） |
| `animals` | `mouse_id` | 実験投入個体。`birth_id`（colony参照ドロップダウン）で連結 |
| `enrollments` | (`mouse_id`,`project_id`) | どの個体をどの project で・どの role（experimental/control/littermate_control/naive）で使うか |
| `projects` | `project_id` | 実験プロジェクト一覧 |
| `procedures` | `procedure_id` | 1 行 = 1 麻酔セッション = 1 IBL フォーム（手術・撮影・採取…）。多段は `series_id`+`session_no` |

### procedures の主な列
- `series_id` / `session_no`: **同一個体の段階手術を束ねる**。例: cranial window を 1 日目、AAV 注入を 8 日後に行う場合 → 2 行を同じ `series_id`（例 `ser-ts301-01`）にし `session_no`=1, 2。単発手術は**両方空**でよい。`series_id` 内は同一 `mouse_id` であることを check が検証。
- 麻酔/鎮痛: `anesthesia`＋`anesthesia_route`、`analgesia`＋`analgesia_route`（route は inhalation/ip/sc/iv/im/po/none から選択）。
- 注入: `construct/dye`（投与物）＋`injection_route`（**ic / ivc / icm** から選択）。
- 座標: `site1_hemi`（R/L/midline）/ `site1_region` / `site1_ap` / `site1_ml` / `site1_dv`。

---

## 4. genotyping（per-assay）

- colony のマーカー列 **`gt_app` / `gt_ps1` / `gt_aqp4` / `gt_cagegfp`**（各 `+/+ +/- -/- + - na`）。
- `genotype`（結合表示）は自動生成（例 `APP:+/-; PS1:+/-; AQP4:-/-`）。
- `lines.assays` が系統ごとの対象を定義（wt=なし, aqp4ko=`aqp4`, 5xfad=`app,ps1`, 5xfad_aqp4ko=`app,ps1,aqp4`, cagegfp 系も同様）。
- `genotype_status`: pending → 全対象 assay が埋まれば confirmed（WT は na）。
- **5xFAD-negative の同腹仔を WT/対照に使う場合**: genotype は客観値（全 −）・birth line も元のまま。「対照として使う」は `enrollments.role`（littermate_control 等）で表現する。genotype/line を書き換えない。

---

## 5. 日々のワークフロー（SOP）

1. **繁殖**: `add_litter.py` で産仔を採番（または Sheet で手入力）。genotyping 前は gt_* 空（pending）。
2. **購入**: `add_vendor.py`（matings 行は作らない・source=vendor）。
3. **genotyping**: colony の gt_* に +/- を入力 → status を confirmed に。
4. **実験投入**: dashboard の「次の mouse_id」を採番 → `animals` 行を作成 → **`birth_id` をドロップダウンで選択**（連結）→ `enrollments` に project/role を記入。
5. **手術/撮影**: `procedures` に行追加（procedure_type/operator/date/座標 等）→ `make_surgery_form.py` で当日フォーム印刷。
6. **スナップショット**: 区切り or 解析 run の直前に、全タブを `<table>.csv` に書き出し → `check_registry.py` 通過 → `git commit`（private group repo）。解析はこの凍結 CSV を読む（再現性）。

> 旧来の "WT###" のような自由記述タグは廃止。系統は `line`（colony から pull）、使用数は集計で出す。

---

## 6. スナップショット & git

- **Sheet = 正本の編集面**（同時編集に強い・バージョン履歴あり）。
- **CSV = git に積む版管理形式**（テキストで diff/blame 可能）。編集は CSV でなく Sheet で行う。
- 物理行順は挿入順のまま保つ（CSV diff を安定させる）。並べ替えは filter view / `=QUERY()` ビューで。
- スナップショット先は **group 階層の private repo**（1 プロジェクト配下に置かない）。

---

## 7. スクリプト

| スクリプト | 用途 | 例 |
|---|---|---|
| `check_registry.py` | 整合性ゲート（PK 形式/重複・FK・語彙・意味検査）。exit 0/1, `--strict` | `py scripts/check_registry.py registry.xlsx` |
| `add_litter.py` | 産仔の一括登録（自動採番＋matings 行） | `py scripts/add_litter.py registry.xlsx --line aqp4ko --males 6 --females 4 --dob 2026-06-14 --sire aqp4ko-122 --dam aqp4ko-123` |
| `add_vendor.py` | 購入個体の登録（matings なし） | `py scripts/add_vendor.py registry.xlsx --line wt --females 5 --dob 2026-06-01 --vendor CLEA --genotype-status na` |
| `make_surgery_form.py` | procedures から IBL 手術フォーム生成 | `py scripts/make_surgery_form.py registry.xlsx templates/SurgeryInformation_template.docx <procedure_id>` |

- 依存: `openpyxl`（全スクリプト）、`docxtpl`（フォームのみ）。`py -m pip install openpyxl docxtpl`。
- `-/-` のように `-` で始まる引数は `--gt-aqp4=-/-` の `=` 形式で渡す。

---

## 8. 整合チェック（check_registry.py が見るもの）

- **PK**: 形式（`mouse_id ^(ts|sk)\d+$`、`birth_id ^<line>-<n>$` 小文字）＋重複なし。
- **FK**: `animals.birth_id→colony`、`enrollments.mouse_id→animals`、`enrollments.project_id→projects`、`procedures.mouse_id→animals`、`matings.sire_id/dam_id→colony`。空欄はスキップ。`colony.sire/dam` は free-text（FK 対象外）。
- **uniqueness**: `animals.birth_id`（非空）の重複禁止（1 個体=1 mouse_id）。
- **語彙**: sex/genotype_call/animal_status/role/procedure_type 等を vocab と照合。
- **意味**: sire=M/dam=F、series 同一 mouse_id、procedure_date ≥ dob、cohort↔prefix 等。

---

## 9. 既知の制約 / TODO

- `enrollments` は空（実験台帳に project 情報が無いため）。project/role は手動割当。
- 歴史 400 個体（ts1–300, sk1–100）は `birth_id` 空（旧タグは notes 温存）。今後の個体から birth_id をドロップダウンで連結。
- `registry_to_metadata.py`（registry CSV → project 別 metadata.yaml、`enrollments.project_id` で絞る）: 未実装。
- `snapshot.py`（全タブ→CSV＋check＋git commit を 1 コマンド）: 未実装。
- 要記入の placeholder: project タイトル、operator 実名、手術座標/construct。
