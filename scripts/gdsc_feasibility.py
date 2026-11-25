"""Inspect GDSC 8.5 and join exact protein substitutions to fitted dose responses."""

import argparse
import csv
import io
import json
import math
import statistics
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile

from python_calamine import CalamineWorkbook

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/gdsc"
OUTPUT = ROOT / "data/processed/gdsc"
GDSC = "https://cog.sanger.ac.uk/cancerrxgene/GDSC_release8.5/"
CMP = "https://cog.sanger.ac.uk/cmp/download/"
RESPONSE_FILES = {
    dataset: f"{dataset}_fitted_dose_response_27Oct23.xlsx"
    for dataset in ("GDSC1", "GDSC2")
}
CELL_FILE = "Cell_Lines_Details.xlsx"
COMPOUND_FILE = "screened_compounds_rel_8.5.csv"
MODEL_FILE = "model_list_20261013.csv"
MUTATION_FILE = "mutations_summary_20260724.zip"
SOURCES = {
    **dict.fromkeys((*RESPONSE_FILES.values(), CELL_FILE, COMPOUND_FILE,
                     "GDSC_Fitted_Data_Description.pdf"), GDSC),
    MODEL_FILE: CMP,
    MUTATION_FILE: CMP,
}
TARGETS = (
    ("BRAF", "p.V600E", "Vemurafenib"),
    ("BRAF", "p.V600E", "Dabrafenib"),
    ("BRAF", "p.V600E", "PLX-4720"),
    ("PIK3CA", "p.H1047R", "Alpelisib"),
    ("PIK3CA", "p.E545K", "Alpelisib"),
    ("PIK3CA", "p.H1047R", "GNE-317"),
)
VEMURAFENIB_ALIASES = {"vemurafenib", "plx4032", "rg7204", "zelboraf", "ro5185426", "r05185426"}


def download(raw_dir):
    raw_dir.mkdir(parents=True, exist_ok=True)
    for filename, base in SOURCES.items():
        path = raw_dir / filename
        if path.is_file():
            continue
        partial = path.with_suffix(path.suffix + ".part")
        subprocess.run(
            ["curl", "-fsSL", "--retry", "2", "--max-time", "300", base + filename,
             "-o", str(partial)],
            check=True,
        )
        partial.replace(path)


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def excel_rows(path, sheet_name):
    workbook = CalamineWorkbook.from_path(path)
    iterator = workbook.get_sheet_by_name(sheet_name).iter_rows()
    fields = next(iterator)
    for values in iterator:
        yield dict(zip(fields, values, strict=True))


def mutation_index(path):
    targets = {(gene, variant) for gene, variant, _ in TARGETS}
    index = defaultdict(dict)
    count = 0
    all_models = set()
    with ZipFile(path) as archive:
        name = path.stem + ".csv"
        with archive.open(name) as zipped, io.TextIOWrapper(zipped, encoding="utf-8-sig") as source:
            for row in csv.DictReader(source):
                count += 1
                model_id = row["model_id"]
                all_models.add(model_id)
                key = (row["gene_symbol"], row["protein_mutation"])
                if key in targets and row["cancer_driver"] == "t":
                    index[model_id].setdefault(key, []).append(row)
    return index, count, len(all_models)


def normalise_alias(value):
    return "".join(char for char in str(value).lower() if char.isalnum())


def compound_codes(row):
    names = [row["DRUG_NAME"]]
    names.extend(row.get("SYNONYMS", "").split(","))
    return {normalise_alias(name) for name in names}


def cell_groups(records):
    groups = defaultdict(list)
    for row in records:
        key = tuple(row[field] for field in (
            "DATASET", "DRUG_ID", "DRUG_NAME", "gene", "protein_mutation",
            "MIN_CONC", "MAX_CONC", "TCGA_DESC", "cancer_type",
        ))
        groups[key].append(row)
    summaries = []
    for key, rows in sorted(groups.items()):
        ids = {row["SANGER_MODEL_ID"] for row in rows}
        patients = {row["patient_id"] for row in rows if row["patient_id"]}
        measured = defaultdict(list)
        for row in rows:
            if row["LN_IC50"] != "":
                measured[row["SANGER_MODEL_ID"]].append(row["LN_IC50"])
        ln_ic50 = [statistics.median(values) for values in measured.values()]
        auc = [row["AUC"] for row in rows if row["AUC"] != ""]
        summaries.append(dict(
            zip(("dataset", "drug_id", "drug_name", "gene", "variant", "min_conc_uM",
                 "max_conc_uM", "tcga", "cmp_cancer_type"), key, strict=True),
            nlme_result_ids="|".join(str(value) for value in sorted({int(row["NLME_RESULT_ID"]) for row in rows})),
            n_rows=len(rows),
            n_models=len(ids),
            n_patient_ids=len(patients),
            n_models_without_patient_id=len({row["SANGER_MODEL_ID"] for row in rows
                                             if not row["patient_id"]}),
            n_models_ln_ic50=len(measured),
            n_rows_auc=len(auc),
            auc_median=round(statistics.median(auc), 6) if auc else "",
            n_rows_ln_ic50_above_max=sum(row["LN_IC50"] > math.log(row["MAX_CONC"])
                                        for row in rows if row["LN_IC50"] != ""),
            n_rows_ln_ic50_below_min=sum(row["LN_IC50"] < math.log(row["MIN_CONC"])
                                        for row in rows if row["LN_IC50"] != ""),
            ln_ic50_median=round(statistics.median(ln_ic50), 6) if ln_ic50 else "",
            ln_ic50_min=min(ln_ic50) if ln_ic50 else "",
            ln_ic50_max=max(ln_ic50) if ln_ic50 else "",
        ))
    return summaries


def inspect(raw_dir):
    cmp_models = {row["model_id"]: row for row in csv_rows(raw_dir / MODEL_FILE)}
    details = list(excel_rows(raw_dir / CELL_FILE, "Cell line details"))
    cosmic_details = {int(row["COSMIC identifier"]): row for row in details if row["COSMIC identifier"]}
    mutants, mutation_rows, mutation_models = mutation_index(raw_dir / MUTATION_FILE)
    compounds = list(csv_rows(raw_dir / COMPOUND_FILE))
    candidates = defaultdict(list)
    for gene, variant, drug in TARGETS:
        candidates[normalise_alias(drug)].append((gene, variant))
    stats = {
        "release": "GDSC Release 8.5 (2023-10-27)",
        "sources": {name: link + name for name, link in SOURCES.items()},
        "model_metadata_rows": len(cmp_models),
        "driver_mutation_rows": mutation_rows,
        "driver_mutation_models": mutation_models,
        "cell_lines_details_rows": len(details),
        "screened_compound_rows": len(compounds),
        "driver_models_by_variant": {
            f"{gene} {variant}": sum((gene, variant) in calls for calls in mutants.values())
            for gene, variant, _ in TARGETS
        },
        "vemurafenib_compound_entries": [
            row for row in compounds if compound_codes(row) & VEMURAFENIB_ALIASES
        ],
        "screens": {},
    }
    selected = []
    for dataset, file in RESPONSE_FILES.items():
        keys = set()
        model_ids = set()
        drug_ids = set()
        coverage = defaultdict(set)
        found_drugs = Counter()
        counts = Counter()
        identity_discrepancies = set()
        webreleases = set()
        for row in excel_rows(raw_dir / file, "Sheet 1"):
            counts["response_rows"] += 1
            webreleases.add(row["WEBRELEASE"])
            model_id = row["SANGER_MODEL_ID"]
            model_ids.add(model_id)
            drug_id = int(row["DRUG_ID"])
            drug_ids.add(drug_id)
            keys.add((model_id, drug_id))
            cosmic = int(row["COSMIC_ID"]) if row["COSMIC_ID"] != "" else None
            model = cmp_models.get(model_id)
            if model:
                coverage["models_in_cmp"].add(model_id)
                if model_id in mutants:
                    coverage["models_with_any_target_driver"].add(model_id)
                cmp_cosmic = {int(value.strip()) for value in model["COSMIC_ID"].split(",")
                              if value.strip().isdigit()}
                if cmp_cosmic and cosmic is not None and cosmic not in cmp_cosmic:
                    identity_discrepancies.add((model_id, cosmic, model["COSMIC_ID"]))
            if cosmic in cosmic_details:
                coverage["models_in_cell_lines_details_via_cosmic"].add(model_id)
            code = normalise_alias(row["DRUG_NAME"])
            if code in VEMURAFENIB_ALIASES:
                code = "vemurafenib"
            if code not in candidates:
                continue
            found_drugs[f"{row['DRUG_NAME']} ({drug_id})"] += 1
            if not model or model["species"] != "Homo sapiens" or model["model_type"] != "Cell Line":
                continue
            for gene, variant in candidates[code]:
                calls = mutants.get(model_id, {}).get((gene, variant))
                if not calls:
                    continue
                selected.append({
                    **row,
                    "DRUG_ID": drug_id,
                    "COSMIC_ID": cosmic,
                    "gene": gene,
                    "protein_mutation": variant,
                    "ensembl_gene_ids": "|".join(sorted({call["ensembl_gene_id"] for call in calls})),
                    "cdna_mutations": "|".join(sorted({call["cdna_mutation"] for call in calls})),
                    "variant_sources": "|".join(sorted({call["source"] for call in calls})),
                    "patient_id": model["patient_id"],
                    "cmp_model_name": model["model_name"],
                    "cancer_type": model["cancer_type"],
                    "cancer_type_detail": model["cancer_type_detail"],
                    "cancer_type_ncit_id": model["cancer_type_ncit_id"],
                    "tissue": model["tissue"],
                    "cmp_cosmic_ids": model["COSMIC_ID"],
                })
        stats["screens"][dataset] = {
            **counts,
            "model_ids": len(model_ids - {""}),
            "drug_ids": len(drug_ids),
            "distinct_model_drug_id_pairs": len(keys),
            "coverage": {key: len(value) for key, value in sorted(coverage.items())},
            "selected_drug_response_rows_before_variant_filter": dict(sorted(found_drugs.items())),
            "cmp_cosmic_mismatches": [list(item) for item in sorted(identity_discrepancies)],
            "webrelease_values": sorted(webreleases),
        }
    stats["targets_after_join"] = {
        dataset: {
            f"{gene} {variant} + {drug}": len({
                row["SANGER_MODEL_ID"] for row in selected if row["DATASET"] == dataset
                and row["gene"] == gene and row["protein_mutation"] == variant
                and (normalise_alias(row["DRUG_NAME"]) in VEMURAFENIB_ALIASES
                     if drug == "Vemurafenib" else row["DRUG_NAME"] == drug)
            })
            for gene, variant, drug in TARGETS
        }
        for dataset in RESPONSE_FILES
    }
    return stats, sorted(selected, key=lambda row: (
        row["DATASET"], row["DRUG_ID"], row["gene"], row["protein_mutation"], row["SANGER_MODEL_ID"],
        row["NLME_CURVE_ID"],
    ))


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW)
    parser.add_argument("--out-dir", type=Path, default=OUTPUT)
    parser.add_argument("--download", action="store_true", help="Download missing official archives")
    args = parser.parse_args()
    if args.download:
        download(args.raw_dir)
    stats, rows = inspect(args.raw_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "joined_response_rows.csv", rows)
    write_csv(args.out_dir / "cross_cancer_cohorts.csv", cell_groups(rows))
    (args.out_dir / "summary.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
