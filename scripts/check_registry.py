#!/usr/bin/env python3
"""check_registry.py — integrity gate for the lab-wide colony + experiment registry (v1.1).

Reads an .xlsx (tabs) OR a directory of <table>.csv and validates PK format &
uniqueness, referential integrity (incl. cross-layer animals.birth_id->colony and
the enrollments mouse_id/project links), controlled vocab, and breeding/procedure
semantics. Exits non-zero on ERROR so it can gate the analysis/metadata step.

Tables (any subset): lines, colony, matings, animals, enrollments, projects, procedures, vocab
Note: colony.sire/dam are preserved free-text from legacy ledgers (cross-line, non-uniform)
      and are NOT enforced as FKs in v1.1. Structured pedigree lives in matings.
Usage: python check_registry.py registry.xlsx [--strict]
"""
from __future__ import annotations
import os, re, sys
from collections import defaultdict, Counter
import pandas as pd

KNOWN = ["lines","colony","matings","litters","animals","enrollments","projects","procedures","vocab"]
PK = {"lines":"line_id","colony":"birth_id","matings":"mating_id","animals":"mouse_id",
      "projects":"project_id","procedures":"procedure_id","litters":"litter_id"}
FKS = [
    ("colony","line_id","lines","line_id"),
    ("colony","litter_id","litters","litter_id"),
    ("litters","mating_id","matings","mating_id"),
    ("litters","line_id","lines","line_id"),
    ("animals","birth_id","colony","birth_id"),          # cross-layer
    ("enrollments","mouse_id","animals","mouse_id"),
    ("enrollments","project_id","projects","project_id"),
    ("matings","line_id","lines","line_id"),
    ("matings","sire_id","colony","birth_id"),
    ("matings","dam_id","colony","birth_id"),
    ("procedures","mouse_id","animals","mouse_id"),
]
VOCAB = [
    ("colony","sex","sex"),("colony","source","source"),
    ("colony","genotype_status","genotype_status"),("colony","status","animal_status"),
    ("colony","gt_app","genotype_call"),("colony","gt_ps1","genotype_call"),("colony","gt_aqp4","genotype_call"),("colony","gt_cagegfp","genotype_call"),
    ("matings","status","mating_status"),
    ("animals","fixation","fixation"),("animals","sex","sex"),("animals","cohort","cohort"),
    ("enrollments","exp_status","exp_status"),("enrollments","role","role"),
    ("procedures","procedure_type","procedure_type"),("procedures","operator","operator"),
    ("procedures","anesthesia","anesthesia"),("procedures","anesthesia_route","route"),("procedures","analgesia_route","route"),
    ("procedures","injection_route","injection_route"),
    ("procedures","site1_hemi","hemisphere"),("procedures","site2_hemi","hemisphere"),
]
MOUSE_ID_RE = re.compile(r"^(ts|sk)[0-9]+$")
BIRTH_ID_RE = re.compile(r"^[a-z0-9_]+-[0-9]+$")

class Report:
    def __init__(self): self.errors,self.warns,self.infos=[],[],[]
    def err(self,m): self.errors.append(m)
    def warn(self,m): self.warns.append(m)
    def info(self,m): self.infos.append(m)

def _missing(v):
    if v is None: return True
    if isinstance(v,float) and pd.isna(v): return True
    return str(v).strip().lower() in ("","nan","none","nat")
def _val(v): return str(v).strip()
def _cells(df,col):
    if col not in df.columns: return
    for i,v in enumerate(df[col].tolist(),start=2):
        if not _missing(v): yield i,_val(v)
def _date(v):
    if _missing(v): return None
    try: return pd.to_datetime(v).date()
    except Exception: return None

def load(path):
    t={}
    if os.path.isdir(path):
        for k in KNOWN:
            fp=os.path.join(path,f"{k}.csv")
            if os.path.exists(fp): t[k]=pd.read_csv(fp,dtype=str,keep_default_na=False)
    elif path.lower().endswith((".xlsx",".xlsm")):
        for n,df in pd.read_excel(path,sheet_name=None,dtype=str).items():
            if n.strip().lower() in KNOWN: t[n.strip().lower()]=df.fillna("")
    else: raise SystemExit(f"unsupported: {path}")
    return t

def build_vocab(t):
    voc={}; df=t.get("vocab")
    if df is None: return voc
    for c in df.columns:
        vals={str(x).strip() for x in df[c].tolist() if not _missing(x)}
        if vals: voc[c.strip()]=vals
    return voc

def check(t,rep):
    voc=build_vocab(t)
    lines_ids={v for _,v in _cells(t["lines"],"line_id")} if t.get("lines") is not None else set()
    # PK uniqueness + format
    for tab,pk in PK.items():
        df=t.get(tab)
        if df is None: continue
        if pk not in df.columns: rep.err(f"[{tab}] missing PK '{pk}'"); continue
        seen={}
        for r,vv in _cells(df,pk):
            if vv in seen: rep.err(f"[{tab}] duplicate {pk}='{vv}' (rows {seen[vv]},{r})")
            else: seen[vv]=r
        if tab=="animals":
            for r,vv in _cells(df,pk):
                if not MOUSE_ID_RE.match(vv):
                    fix=f" -> '{vv.lower()}'" if MOUSE_ID_RE.match(vv.lower()) else ""
                    rep.err(f"[animals] mouse_id '{vv}' (row {r}) violates ^(ts|sk)[0-9]+$ lowercase{fix}")
        if tab=="colony":
            for r,vv in _cells(df,pk):
                if not BIRTH_ID_RE.match(vv): rep.err(f"[colony] birth_id '{vv}' (row {r}) violates <line_id>-<n> lowercase"); continue
                pre=vv.rsplit("-",1)[0]
                own=_val(df["line_id"].iloc[r-2]) if "line_id" in df.columns and not _missing(df["line_id"].iloc[r-2]) else ""
                if own and pre!=own: rep.err(f"[colony] birth_id '{vv}' prefix != line_id '{own}' (row {r})")
                if lines_ids and pre not in lines_ids: rep.err(f"[colony] birth_id '{vv}' prefix '{pre}' not in lines (row {r})")
    # enrollments composite PK (mouse_id, project_id)
    en=t.get("enrollments")
    if en is not None and {"mouse_id","project_id"}<=set(en.columns):
        seen={}
        for idx in range(len(en)):
            key=(_val(en.iloc[idx].get("mouse_id","")),_val(en.iloc[idx].get("project_id","")))
            if "" in key: continue
            if key in seen: rep.err(f"[enrollments] duplicate (mouse_id,project_id)={key} (rows {seen[key]},{idx+2})")
            else: seen[key]=idx+2
    # animals.birth_id uniqueness (non-blank): one physical mouse -> one animals row (re-use = enrollments, not new row)
    an=t.get("animals")
    if an is not None and "birth_id" in an.columns:
        seen={}
        for i,bid in _cells(an,"birth_id"):
            vv=_val(bid)
            if vv=="": continue
            if vv in seen: rep.err(f"[animals] duplicate birth_id='{vv}' (rows {seen[vv]},{i}) — one mouse should map to one mouse_id")
            else: seen[vv]=i
    # FK
    for tab,col,rt,rc in FKS:
        df,rdf=t.get(tab),t.get(rt)
        if df is None or rdf is None or col not in df.columns: continue
        ref={v for _,v in _cells(rdf,rc)}
        for r,vv in _cells(df,col):
            if vv not in ref: rep.err(f"[{tab}] {col}='{vv}' (row {r}) no match in {rt}.{rc} (dangling)")
    # vocab
    for tab,col,vn in VOCAB:
        df=t.get(tab)
        if df is None or col not in df.columns or vn not in voc: continue
        for r,vv in _cells(df,col):
            if vv not in voc[vn]: rep.err(f"[{tab}] {col}='{vv}' (row {r}) not in vocab[{vn}]")
    c,a,m,p=(t.get(x) for x in ("colony","animals","matings","procedures"))
    # matings semantics
    if m is not None and c is not None:
        sex={bid:_val(c["sex"].iloc[i-2]) for i,bid in _cells(c,"birth_id") if "sex" in c.columns and not _missing(c["sex"].iloc[i-2])}
        for idx in range(len(m)):
            row,r=m.iloc[idx],idx+2
            sire,dam,st=_val(row.get("sire_id","")),_val(row.get("dam_id","")),_val(row.get("status",""))
            if sire and dam and sire==dam: rep.err(f"[matings] row {r} sire_id==dam_id ('{sire}')")
            if sire in sex and sex[sire]!="M": rep.warn(f"[matings] sire '{sire}' (row {r}) sex={sex[sire]} (exp M)")
            if dam in sex and sex[dam]!="F": rep.warn(f"[matings] dam '{dam}' (row {r}) sex={sex[dam]} (exp F)")
            if st=="littered":
                np_,nm,nf=row.get("n_pups",""),row.get("n_male",""),row.get("n_female","")
                if not _missing(nm) and not _missing(nf) and not _missing(np_):
                    try:
                        if int(float(nm))+int(float(nf))!=int(float(np_)): rep.warn(f"[matings] row {r} n_male+n_female != n_pups")
                    except ValueError: pass
    # procedures: series consistency + date>=dob
    if p is not None:
        if {"series_id","mouse_id"}<=set(p.columns):
            grp=defaultdict(list)
            for idx in range(len(p)):
                sid=_val(p.iloc[idx].get("series_id",""))
                if sid: grp[sid].append((idx+2,_val(p.iloc[idx].get("mouse_id",""))))
            multi=sum(1 for rows in grp.values() if len(rows)>1)
            for sid,rows in grp.items():
                if len({mm for _,mm in rows})>1: rep.err(f"[procedures] series '{sid}' spans multiple mouse_id")
            if multi: rep.info(f"multi-session procedure series: {multi}")
        if a is not None and c is not None and "birth_id" in a.columns:
            ab={mid:_val(a["birth_id"].iloc[r-2]) for r,mid in _cells(a,"mouse_id")}
            cd={bid:_date(c["dob"].iloc[i-2]) for i,bid in _cells(c,"birth_id") if "dob" in c.columns}
            for idx in range(len(p)):
                mid=_val(p.iloc[idx].get("mouse_id","")); d=_date(p.iloc[idx].get("procedure_date",""))
                dob=cd.get(ab.get(mid))
                if d and dob and d<dob: rep.err(f"[procedures] row {idx+2} procedure_date {d} < dob {dob} ({mid})")
    # info
    if c is not None and "genotype_status" in c.columns:
        n=sum(1 for _,v in _cells(c,"genotype_status") if v=="pending")
        if n: rep.info(f"genotyping pending: {n}")
    if c is not None and "line_id" in c.columns:
        rep.info("colony per line: "+", ".join(f"{k}={n}" for k,n in sorted(Counter(v for _,v in _cells(c,'line_id')).items())))
    if en is not None and "project_id" in en.columns:
        rep.info("enrollments per project: "+", ".join(f"{k}={n}" for k,n in sorted(Counter(v for _,v in _cells(en,'project_id')).items())))
        mm=Counter(mid for _,mid in _cells(en,"mouse_id"))
        multi=[k for k,n in mm.items() if n>1]
        if multi: rep.info(f"multi-project animals: {len(multi)} ({', '.join(multi)})")

def main(argv):
    strict="--strict" in argv; args=[a for a in argv if not a.startswith("--")]
    if len(args)!=1: print(__doc__); return 2
    t=load(args[0])
    if not t: print("no known tables"); return 2
    rep=Report(); check(t,rep)
    print(f"check_registry: {args[0]}")
    print(f"  tables: {', '.join(k for k in KNOWN if k in t)}")
    for x in rep.infos: print(f"  [INFO]  {x}")
    for x in rep.warns: print(f"  [WARN]  {x}")
    for x in rep.errors[:40]: print(f"  [ERROR] {x}")
    if len(rep.errors)>40: print(f"  ... +{len(rep.errors)-40} more errors")
    print(f"summary: {len(rep.errors)} error(s), {len(rep.warns)} warning(s)")
    failed=len(rep.errors)>0 or (strict and len(rep.warns)>0)
    print("RESULT:","FAIL" if failed else "PASS")
    return 1 if failed else 0

if __name__=="__main__": sys.exit(main(sys.argv[1:]))
