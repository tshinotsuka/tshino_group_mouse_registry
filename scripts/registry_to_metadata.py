#!/usr/bin/env python3
r"""registry_to_metadata.py — registry snapshot CSV → metadata.yaml subject 充填.

解析 ↔ mouse registry（別 repo `tshino_group_mouse_registry`）の主接点（roadmap §7 未決の
"registry_to_metadata.py"）。registry の **snapshots/*.csv**（正本=Google Sheet・版管理=CSV）を
読み、`enrollments.project_id` で当該 project に enroll された個体を絞り、その個体の `subject.*` を
解析側 dataset の `metadata.yaml` に流し込む。

loose coupling: 本 script は registry repo を import しない。snapshots ディレクトリを **パス引数**で
受け取り CSV を直読みするだけ（cross-repo は名前参照・相対リンクにしない）。

契約準拠（docs/metadata_schema.md / file_naming.md）:
- 充填先は `subject`: species / strain / genotype / sex / age_weeks（＋ species）。workflow.md §3 の
  「手書きで埋める部分（genotype/sex/age_weeks）」を registry から自動化する位置づけ。
- `age_weeks` は **揮発列**（registry では TODAY() 由来で snapshot 除外）→ ここで
  **(acquisition_date − dob)/7 で再計算**する（registry の値は使わない）。
- `genotype` は registry の **安定表示列**（snapshot が安定値で保持）をそのまま使う
  （gt_* per-assay 列からは再構成しない）。
- mouse_id は小文字・`^(ts|sk)\d+$`。metadata.subject.sub_id と join。

非破壊が既定:
- 既定は **dry-run**（流し込み予定の subject ブロックと現状との差分を print するだけ）。
- `--write` で初めて書く。既存の非空フィールドは**上書きしない**（`--force` で上書き）。
- 列名は repo の実ヘッダに完全一致しない場合があるため **COLMAP**（候補名リスト）で吸収。
  解決できない論理フィールドは利用可能列を列挙して明示エラー（`--strict`）/警告（既定）。

依存: 標準 csv + PyYAML（ivwib env にある）。pandas 不要（軽量・check_registry の pandas 依存解消方針と整合）。
コメント保持のため `--write` は ruamel.yaml があれば round-trip、無ければ PyYAML で全書き換え（警告）。

使い方:
    # dry-run（既定）: sk8 の subject を作って metadata と差分表示
    python registry_to_metadata.py \
        --snapshots /path/to/tshino_group_mouse_registry/snapshots \
        --project-id 2025_brain_water_dynamics \
        --metadata /ws/.../20260429_sub-sk8_ses-01/raw/metadata.yaml

    # metadata 無しで subject フラグメントだけ吐く（貼り付け用）
    python registry_to_metadata.py --snapshots ... --project-id ... --mouse-id sk8

    # 実書き込み（非破壊・空欄のみ）
    python registry_to_metadata.py --snapshots ... --project-id ... --metadata ... --write
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML が要る: pip install pyyaml  (ivwib env には入っているはず)")

# --- 論理フィールド → CSV 候補列名（実ヘッダ揺れを吸収）-------------------------
# registry の実ヘッダが違っても、ここに候補を足せば動く。先頭から最初に見つかった列を採用。
# 実 snapshot ヘッダで確認済み（2026-06-16）: animals=mouse_id,birth_id,cohort,sex,line,
#   dob_intake,sac_date,fixation,genotype,notes / colony=...,birth_id,line_id,...,dob,...,genotype,... /
#   enrollments=mouse_id,project_id,enroll_date,role,exp_status,notes / lines=line_id,line_name,
#   genotype_expected,background,source,assays,notes（strain は無く background が実体）。
COLMAP = {
    "animals": {
        "mouse_id":   ["mouse_id"],
        "birth_id":   ["birth_id"],
        "sex":        ["sex"],
        "genotype":   ["genotype"],          # 安定表示列（gt_* は使わない）
        "dob_intake": ["dob_intake", "dob", "date_of_birth"],
        "line":       ["line", "line_id"],
        "species":    ["species"],
        "strain":     ["strain"],
        "status":     ["status"],
    },
    "colony": {
        "birth_id": ["birth_id"],
        "dob":      ["dob", "date_of_birth"],
        "line_id":  ["line_id", "line"],
        "sex":      ["sex"],
        "genotype": ["genotype"],
    },
    "enrollments": {
        "mouse_id":   ["mouse_id"],
        "project_id": ["project_id"],
        "role":       ["role"],
    },
    "lines": {
        "line_id": ["line_id", "line"],
        # registry の実名は background（遺伝背景＝subject.strain）。line_name は系統ラベルで予備。
        "strain":  ["strain", "background", "line_name"],
        "species": ["species"],
    },
}

# subject に流す論理フィールド（metadata_schema.md の subject ブロック）
SUBJECT_FIELDS = ["species", "strain", "genotype", "sex", "age_weeks"]
DEFAULT_SPECIES = "Mus musculus"


# --- CSV ロード ---------------------------------------------------------------
def load_csv(snap_dir: Path, name: str) -> tuple[list[dict], list[str]]:
    """snapshots/<name>.csv を読む。無ければ ([], []) を返す（任意テーブル対応）。"""
    p = snap_dir / f"{name}.csv"
    if not p.exists():
        return [], []
    with p.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return rows, (reader.fieldnames or [])


def resolve_col(table: str, logical: str, header: list[str]) -> str | None:
    for cand in COLMAP.get(table, {}).get(logical, []):
        if cand in header:
            return cand
    return None


def getval(row: dict, table: str, logical: str, header: list[str]):
    col = resolve_col(table, logical, header)
    if col is None:
        return None
    v = row.get(col)
    return v.strip() if isinstance(v, str) and v.strip() != "" else None


# --- 個体解決 -----------------------------------------------------------------
def index_by(rows: list[dict], table: str, key: str, header: list[str]) -> dict:
    out = {}
    for r in rows:
        k = getval(r, table, key, header)
        if k is not None:
            out[k.lower()] = r
    return out


def compute_age_weeks(dob_str: str | None, acq_str: str | None) -> int | None:
    if not dob_str or not acq_str:
        return None
    try:
        dob = date.fromisoformat(dob_str[:10])
        acq = date.fromisoformat(acq_str[:10])
    except ValueError:
        return None
    days = (acq - dob).days
    if days < 0:
        return None
    return int(round(days / 7.0))


def build_subject(mouse_id: str, project_id: str, acq_date: str | None,
                  snap_dir: Path, strict: bool, warn) -> dict:
    mouse_id = mouse_id.lower()
    animals, a_hdr = load_csv(snap_dir, "animals")
    colony,  c_hdr = load_csv(snap_dir, "colony")
    enroll,  e_hdr = load_csv(snap_dir, "enrollments")
    lines,   l_hdr = load_csv(snap_dir, "lines")

    if not animals:
        warn("animals.csv が空/不在。snapshots パスを確認。", fatal=strict)
    a_idx = index_by(animals, "animals", "mouse_id", a_hdr)
    arow = a_idx.get(mouse_id)
    if arow is None:
        warn(f"mouse_id '{mouse_id}' が animals に無い。", fatal=strict)
        return {}

    # --- enrollment 確認（project で絞る主条件）---
    roles = []
    enrolled = False
    for r in enroll:
        if (getval(r, "enrollments", "mouse_id", e_hdr) or "").lower() == mouse_id \
           and getval(r, "enrollments", "project_id", e_hdr) == project_id:
            enrolled = True
            role = getval(r, "enrollments", "role", e_hdr)
            if role:
                roles.append(role)
    if not enrolled:
        warn(f"'{mouse_id}' は project '{project_id}' に enroll されていない"
             f"（enrollments に (mouse_id, project_id) 行が無い）。", fatal=strict)
    if roles:
        print(f"  [info] enrollment role(s): {', '.join(roles)}  "
              f"(role は subject でなく enrollment の属性ゆえ metadata には書かない)")

    # --- colony 行（birth_id 経由）を 1 度引く（dob / genotype / line のフォールバック源）---
    birth_id = getval(arow, "animals", "birth_id", a_hdr)
    crow = index_by(colony, "colony", "birth_id", c_hdr).get(birth_id.lower()) if birth_id else None

    # dob: colony 優先 → 無ければ animals.dob_intake（歴史個体は birth_id 空）
    dob = getval(crow, "colony", "dob", c_hdr) if crow else None
    if dob is None:
        dob = getval(arow, "animals", "dob_intake", a_hdr)
        if birth_id is None:
            print("  [info] birth_id 空（歴史個体）→ dob は animals.dob_intake を使用")

    # genotype: animals.genotype（安定表示列）優先 → 空なら colony.genotype にフォールバック
    genotype = getval(arow, "animals", "genotype", a_hdr)
    if genotype is None and crow:
        genotype = getval(crow, "colony", "genotype", c_hdr)
        if genotype is not None:
            print("  [info] animals.genotype 空 → colony.genotype を使用")

    # line → strain/species（lines テーブル経由）。line は animals → colony.line_id の順
    line = getval(arow, "animals", "line", a_hdr)
    if line is None and crow:
        line = getval(crow, "colony", "line_id", c_hdr)
    strain = getval(arow, "animals", "strain", a_hdr)
    species = getval(arow, "animals", "species", a_hdr)
    if (strain is None or species is None) and line and lines:
        lrow = index_by(lines, "lines", "line_id", l_hdr).get(line.lower())
        if lrow:
            strain = strain or getval(lrow, "lines", "strain", l_hdr)
            species = species or getval(lrow, "lines", "species", l_hdr)

    age_weeks = compute_age_weeks(dob, acq_date)
    if age_weeks is None and acq_date:
        warn(f"age_weeks 計算不可（dob={dob!r} acquisition_date={acq_date!r}）。", fatal=False)
    elif acq_date is None:
        print("  [info] acquisition_date 未指定 → age_weeks は計算しない（metadata から補える）")

    subj = {
        "species": species or DEFAULT_SPECIES,
        # strain は lines.background 由来。未解決なら None（手入力）。
        # line ラベル自体は subject に専用 field が無く genotype に含意されるため strain 代用にしない。
        "strain": strain,
        "genotype": genotype,
        "sex": getval(arow, "animals", "sex", a_hdr),
        "age_weeks": age_weeks,
    }
    return {k: v for k, v in subj.items() if v is not None}


# --- metadata.yaml 充填（非破壊）---------------------------------------------
def load_metadata(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def plan_merge(meta: dict, subj: dict, force: bool):
    """(更新計画 list[(key, old, new, action)], 反映後 subject dict) を返す。"""
    cur = (meta.get("subject") or {})
    plan = []
    merged = dict(cur)
    for k in SUBJECT_FIELDS:
        if k not in subj:
            continue
        old = cur.get(k)
        new = subj[k]
        empty = old in (None, "", [])
        if empty:
            action = "fill"
        elif str(old) == str(new):
            action = "same"
        elif force:
            action = "overwrite"
        else:
            action = "keep(existing≠registry; --force で上書き)"
        plan.append((k, old, new, action))
        if action in ("fill", "overwrite"):
            merged[k] = new
    return plan, merged


def print_plan(plan):
    if not plan:
        print("  (registry から充填できる subject フィールドが無い)")
        return
    w = max(len(k) for k, *_ in plan)
    for k, old, new, action in plan:
        print(f"  {k:<{w}}  current={old!r:<18} registry={new!r:<18} -> {action}")


def write_metadata(path: Path, meta: dict, merged_subject: dict):
    """ruamel.yaml があれば round-trip（コメント保持）、無ければ PyYAML 全書き換え（警告）。"""
    try:
        from ruamel.yaml import YAML
        yml = YAML()
        yml.preserve_quotes = True
        with path.open(encoding="utf-8") as f:
            doc = yml.load(f)
        if doc.get("subject") is None:
            doc["subject"] = {}
        for k, v in merged_subject.items():
            doc["subject"][k] = v
        with path.open("w", encoding="utf-8") as f:
            yml.dump(doc, f)
        print(f"[write] {path} を更新（ruamel.yaml round-trip・コメント保持）")
    except ImportError:
        print("[warn] ruamel.yaml が無い → PyYAML で書き換え（コメント/順序が失われる）。"
              "コメントを残したいなら subject フラグメントを手で貼るか ruamel.yaml を入れる。")
        meta["subject"] = merged_subject
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
        print(f"[write] {path} を更新（PyYAML）")


# --- main ---------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshots", required=True, type=Path,
                    help="tshino_group_mouse_registry/snapshots ディレクトリ")
    ap.add_argument("--project-id", required=True, help="例: 2025_brain_water_dynamics")
    ap.add_argument("--metadata", type=Path, help="充填先 dataset の raw/metadata.yaml")
    ap.add_argument("--mouse-id", help="metadata 未指定 or sub_id を上書きしたいとき")
    ap.add_argument("--acquisition-date", help="ISO 日付。未指定なら metadata から取得")
    ap.add_argument("--write", action="store_true", help="実書き込み（既定は dry-run）")
    ap.add_argument("--force", action="store_true", help="既存の非空 subject も上書き")
    ap.add_argument("--strict", action="store_true",
                    help="enroll 無し・個体不在・主要列未解決を fatal にする（exit 1）")
    args = ap.parse_args(argv)

    if not args.snapshots.is_dir():
        sys.exit(f"snapshots ディレクトリが無い: {args.snapshots}")

    _failed = {"v": False}

    def warn(msg, fatal=False):
        tag = "ERROR" if fatal else "warn"
        print(f"  [{tag}] {msg}")
        if fatal:
            _failed["v"] = True

    # mouse_id / acquisition_date を決める
    meta = None
    if args.metadata:
        if not args.metadata.exists():
            sys.exit(f"metadata.yaml が無い: {args.metadata}")
        meta = load_metadata(args.metadata)
    mouse_id = args.mouse_id or (meta or {}).get("subject", {}).get("sub_id")
    if not mouse_id:
        sys.exit("mouse_id を決められない（--mouse-id か metadata.subject.sub_id が要る）")
    acq_date = args.acquisition_date or (meta or {}).get("acquisition_date")

    print(f"[registry_to_metadata] mouse_id={mouse_id} project_id={args.project_id} "
          f"acquisition_date={acq_date}")
    subj = build_subject(mouse_id, args.project_id, acq_date, args.snapshots,
                         args.strict, warn)

    if args.strict and _failed["v"]:
        print("[FAIL] strict モードで未充足あり。")
        return 1

    print("[subject] registry から得た値:")
    for k in SUBJECT_FIELDS:
        if k in subj:
            print(f"  {k}: {subj[k]}")

    if meta is not None:
        print("[merge plan] (非破壊・空欄のみ。--force で上書き):")
        plan, merged = plan_merge(meta, subj, args.force)
        print_plan(plan)
        if args.write:
            write_metadata(args.metadata, meta, merged)
        else:
            print("  (dry-run。書き込むには --write)")
    else:
        print("[fragment] metadata.yaml に貼れる subject ブロック:")
        print(yaml.safe_dump({"subject": {**{"sub_id": mouse_id}, **subj}},
                             allow_unicode=True, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
