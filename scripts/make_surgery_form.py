#!/usr/bin/env python3
"""make_surgery_form.py — pre-fill the IBL SurgeryInformation form from the registry (v1.0).

Joins procedures + animals + colony (birth facts via birth_id), renders the {{...}}
merge fields of the template, and writes a printable form. As-performed fields
(times/weights/checklist/analgesia detail/coordinate confirmation) stay blank for
handwriting; afterwards transcribe structured deltas back to procedures.

Usage:
  python make_surgery_form.py registry.xlsx template.docx <procedure_id> [--pdf]
"""
import sys, os, datetime as dt
import pandas as pd
from docxtpl import DocxTemplate

def val(x):
    if x is None or (isinstance(x, float) and pd.isna(x)): return ""
    s = str(x).strip(); return "" if s.lower() in ("nan","none","nat") else s
def as_date(x):
    if val(x) == "": return None
    return x.date() if isinstance(x, dt.datetime) else (x if isinstance(x, dt.date) else pd.to_datetime(x).date())

def main(argv):
    pdf = "--pdf" in argv; a = [x for x in argv if not x.startswith("--")]
    if len(a) != 3: print(__doc__); return 2
    xlsx, template, pid = a
    P = pd.read_excel(xlsx, sheet_name="procedures", dtype=str)
    A = pd.read_excel(xlsx, sheet_name="animals", dtype=str)
    C = pd.read_excel(xlsx, sheet_name="colony", dtype=str)
    prow = P[P["procedure_id"].astype(str).str.strip() == pid]
    if prow.empty: raise SystemExit(f"procedure_id '{pid}' not found")
    s = prow.iloc[0]; mouse_id = val(s["mouse_id"])
    arow = A[A["mouse_id"].astype(str).str.strip() == mouse_id]
    if arow.empty: raise SystemExit(f"mouse_id '{mouse_id}' not in animals")
    birth_id = val(arow.iloc[0]["birth_id"])
    crow = C[C["birth_id"].astype(str).str.strip() == birth_id]
    sex = val(crow.iloc[0]["sex"]) if not crow.empty else ""
    dob = as_date(crow.iloc[0]["dob"]) if not crow.empty else None
    genotype = val(crow.iloc[0]["genotype"]) if not crow.empty else ""
    sdate = as_date(s["procedure_date"])
    age_w = round((sdate - dob).days / 7, 1) if (dob and sdate) else ""
    ctx = {"mouse_id": mouse_id, "sex": sex, "age_weeks": age_w, "genotype": genotype,
           "surgery_date": sdate.isoformat() if sdate else "",
           "surgery_type": val(s["procedure_type"]), "construct": val(s.get("construct","")),
           "route": val(s.get("route","")), "anesthesia": val(s.get("anesthesia",""))}
    for site in ("site1", "site2"):
        for f in ("hemi", "region", "ap", "ml", "dv"):
            ctx[f"{site}_{f}"] = val(s.get(f"{site}_{f}", ""))
    doc = DocxTemplate(template); doc.render(ctx)
    out = f"surgery_form_{pid}_{mouse_id}.docx"; doc.save(out)
    print(f"wrote {out}")
    print("  context:", {k: ctx[k] for k in ("mouse_id","sex","age_weeks","surgery_date","surgery_type","construct","route","site1_hemi","site1_region","site1_ap","site1_ml","site1_dv")})
    if pdf:
        os.system(f'python3 /mnt/skills/public/docx/scripts/office/soffice.py --headless --convert-to pdf "{out}" >/dev/null 2>&1')
        print(f"  pdf: {os.path.splitext(out)[0]}.pdf")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
