"""Extract CIViC candidates and keep evidence and response labels in evaluator-only files."""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from download_civic import CIVIC_RELEASE, ROOT

LABELS = ("Sensitivity/Response", "Resistance", "Reduced Sensitivity")
# Observed ambiguous/generic or non-malignant disease records in the released export.
EXCLUDED_DISEASE_NAMES = {"cancer", "solid tumor", "solid tumors, advanced", "chuvash polycythemia"}
DRUG_NAMES = {
    "imatinib mesylate": "Imatinib",
    "pi103": "PI-103",
    "regorafenib anhydrous": "Regorafenib",
}
# Names used in this release that indicate classes, regimens, mixtures or non-drug modalities.
NON_SINGLE_DRUGS = {
    "aromatase inhibitor",
    "braf inhibitor",
    "eap protocol",
    "epidermal growth factor receptor tyrosine kinase inhibitor",
    "folfox regimen",
    "futuximab/modotuximab mixture",
    "hormone therapy",
    "mtor inhibitor",
    "radioactive iodine",
    "therapeutic tumor infiltrating lymphocytes",
}


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def dump_jsonl(path, records):
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def dump_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def variant_ids(profile):
    return [value.strip() for value in profile["variant_ids"].split(",") if value.strip()]


def specific_allele(variant):
    if re.fullmatch(r"CA[0-9]+", variant["allele_registry_id"]):
        return True
    if re.fullmatch(r"[ACDEFGHIKLMNPQRSTVWY][0-9]+[ACDEFGHIKLMNPQRSTVWY*]", variant["variant"]):
        return bool({"missense_variant", "stop_gained"} & set(variant["variant_types"].split(",")))
    return False


def single_drug(row):
    therapy = row["therapies"].strip()
    return bool(therapy and "," not in therapy and not row["therapy_interaction_type"])


def specified_disease(row):
    disease = row["disease"].strip()
    return bool(row["doid"].isdigit() and disease and disease.casefold() not in EXCLUDED_DISEASE_NAMES)


def specific_drug(row):
    return row["therapies"].strip().casefold() not in NON_SINGLE_DRUGS


def source_reference(row):
    return {
        "evidence_id": row["evidence_id"],
        "significance": row["significance"],
        "direction": row["evidence_direction"],
        "level": row["evidence_level"],
        "rating": row["rating"],
        "source_type": row["source_type"],
        "citation_id": row["citation_id"],
        "asco_abstract_id": row["asco_abstract_id"],
        "nct_ids": row["nct_ids"],
        "statement": row["evidence_statement"],
        "phenotypes": row["phenotypes"],
        "variant_origin": row["variant_origin"],
        "therapy_name_in_release": row["therapies"],
        "last_review_date": row["last_review_date"],
        "is_flagged": row["is_flagged"] == "true",
        "url": row["evidence_civic_url"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", default=CIVIC_RELEASE)
    parser.add_argument("--raw", type=Path, default=ROOT / "data/raw/civic")
    parser.add_argument("--out", type=Path, default=ROOT / "data/processed/civic")
    args = parser.parse_args()

    def source(name):
        return rows(args.raw / f"{args.release}-{name}.tsv")

    evidence = source("ClinicalEvidenceSummaries")
    profiles = {p["molecular_profile_id"]: p for p in source("MolecularProfileSummaries")}
    variants = {v["variant_id"]: v for v in source("VariantSummaries")}
    features = {f["feature_id"]: f for f in source("FeatureSummaries")}
    profile_members = {key: variant_ids(profile) for key, profile in profiles.items()}

    flow = {"raw": len(evidence)}

    def retain(name, predicate, candidates):
        retained = [row for row in candidates if predicate(row)]
        flow[name] = len(retained)
        return retained

    def get_variant(row):
        variant_id, = profile_members[row["molecular_profile_id"]]
        return variants[variant_id]

    def known_gene(row):
        variant = get_variant(row)
        feature = features[variant["feature_id"]]
        return feature["feature_type"] == "Gene" and feature["entrez_id"].isdigit()

    def positive_profile(row):
        variant = get_variant(row)
        return variant["single_variant_molecular_profile_id"] == row["molecular_profile_id"]

    predictive = retain("accepted", lambda r: r["evidence_status"] == "accepted", evidence)
    predictive = retain("predictive", lambda r: r["evidence_type"] == "Predictive", predictive)
    supports = retain("supports", lambda r: r["evidence_direction"] == "Supports", predictive)
    supports = retain("specified_disease", specified_disease, supports)
    supports = retain("single_profile_member", lambda r: len(profile_members[r["molecular_profile_id"]]) == 1, supports)
    supports = retain("positive_simple_profile", positive_profile, supports)
    supports = retain("single_gene", known_gene, supports)
    supports = retain("specific_allele", lambda r: specific_allele(get_variant(r)), supports)
    supports = retain("single_named_drug", single_drug, supports)
    supports = retain("specific_single_drug", specific_drug, supports)
    supports = retain("target_significance", lambda r: r["significance"] in LABELS, supports)

    def case_key(row):
        variant = get_variant(row)
        feature = features[variant["feature_id"]]
        name = row["therapies"].strip()
        drug = DRUG_NAMES.get(name.casefold(), name)
        allele = variant["allele_registry_id"]
        if not re.fullmatch(r"CA[0-9]+", allele):
            allele = f"CIViC:{variant['variant_id']}"
        return feature["entrez_id"], allele, row["doid"], drug.casefold()

    grouped = defaultdict(list)
    opposing = defaultdict(list)
    for row in supports:
        grouped[case_key(row)].append(row)
    for row in predictive:
        if (row["evidence_direction"] == "Does Not Support" and row["significance"] in LABELS
                and specified_disease(row) and len(profile_members[row["molecular_profile_id"]]) == 1
                and positive_profile(row) and known_gene(row) and specific_allele(get_variant(row))
                and single_drug(row) and specific_drug(row)):
            opposing[case_key(row)].append(row)

    inputs = []
    reference = []
    pairs_by_allele_drug = defaultdict(list)
    single_labels = Counter()
    conflicts = 0
    same_significance_opposition = 0
    both_conflict_types = 0
    unique_clinical_candidates = 0
    for index, (key, group) in enumerate(sorted(grouped.items()), 1):
        genes_id, allele, doid, drug_key = key
        rep = group[0]
        variant = get_variant(rep)
        feature = features[variant["feature_id"]]
        case_id = f"CIVIC-{index:04}"
        model_case = {
            "case_id": case_id,
            "gene": feature["name"],
            "entrez_id": genes_id,
            "variant": variant["variant"],
            "civic_variant_id": variant["variant_id"],
            "allele_key": allele,
            "hgvs_descriptions": [term.strip() for term in variant["hgvs_descriptions"].split(",") if term.strip()],
            "disease": rep["disease"],
            "doid": f"DOID:{doid}",
            "drug": DRUG_NAMES.get(rep["therapies"].strip().casefold(), rep["therapies"].strip()),
        }
        inputs.append(model_case)

        labels = sorted({row["significance"] for row in group})
        metadata_conflict = bool({row["significance"] for row in opposing[key]} & set(labels))
        if metadata_conflict:
            same_significance_opposition += 1

        if len(labels) > 1:
            conflicts += 1
            both_conflict_types += int(metadata_conflict)
        else:
            single_labels[labels[0]] += 1
            if not metadata_conflict and any(row["evidence_level"] in {"A", "B"} for row in group):
                unique_clinical_candidates += 1
            pairs_by_allele_drug[(genes_id, allele, drug_key)].append(
                {
                    "case_id": case_id,
                    "disease": rep["disease"],
                    "doid": model_case["doid"],
                    "label": labels[0],
                    "evidence_ids": [row["evidence_id"] for row in group],
                    "levels": sorted({row["evidence_level"] for row in group}),
                    "pubmed_ids": sorted({row["citation_id"] for row in group if row["source_type"] == "PubMed"}),
                    "exact_direction_opposition": metadata_conflict,
                }
            )

        reference.append(
            {
                "case_id": case_id,
                "civic_candidate_label": labels[0] if len(labels) == 1 else None,
                "all_supporting_labels": labels,
                "same_label_direction_opposition": metadata_conflict,
                "supporting_evidence": [source_reference(row) for row in group],
                "opposing_evidence": [source_reference(row) for row in opposing[key]],
            }
        )

    pairs = []
    for (gene_id, allele, drug), cases in sorted(pairs_by_allele_drug.items()):
        for left, right in combinations(cases, 2):
            if left["doid"] != right["doid"] and left["label"] != right["label"]:
                pairs.append({"entrez_id": gene_id, "allele_key": allele, "drug": drug, "left": left, "right": right})

    args.out.mkdir(parents=True, exist_ok=True)
    dump_jsonl(args.out / "model_inputs.jsonl", inputs)
    dump_jsonl(args.out / "references.jsonl", reference)
    dump_jsonl(args.out / "pair_candidates.jsonl", pairs)
    dump_json(
        args.out / "statistics.json",
        {
            "release": args.release,
            "raw_field_names": list(evidence[0]),
            "raw_rows_by_evidence_status": dict(Counter(row["evidence_status"] for row in evidence)),
            "raw_rows_by_evidence_type": dict(Counter(row["evidence_type"] for row in evidence)),
            "raw_rows_by_direction": dict(Counter(row["evidence_direction"] for row in evidence)),
            "cumulative_filters": flow,
            "single_named_drug_rows_by_label": dict(Counter(row["significance"] for row in supports)),
            "retained_rows_by_level": dict(Counter(row["evidence_level"] for row in supports)),
            "retained_rows_by_flag": dict(Counter(row["is_flagged"] for row in supports)),
            "deduplicated_case_keys": len(inputs),
            "cases_with_one_supporting_label": sum(single_labels.values()),
            "cases_with_multiple_supporting_labels": conflicts,
            "cases_with_support_and_does_not_support_for_same_label": same_significance_opposition,
            "cases_with_both_conflict_types": both_conflict_types,
            "single_label_cases_with_ab_evidence_and_no_same_label_opposition": unique_clinical_candidates,
            "single_case_keys_by_label": dict(single_labels),
            "distinct_diseases_by_doid": len({row["doid"] for row in inputs}),
            "distinct_genes_by_entrez": len({row["entrez_id"] for row in inputs}),
            "distinct_gene_alleles": len({(row["entrez_id"], row["allele_key"]) for row in inputs}),
            "distinct_drug_names": len({row["drug"].casefold() for row in inputs}),
            "cross_doid_pair_candidates": len(pairs),
        },
    )


if __name__ == "__main__":
    main()
