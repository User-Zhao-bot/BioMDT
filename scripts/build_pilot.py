"""Build the Phase 1 evidence graph and separate case/reference snapshots."""
import csv
import json
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw"
QUERY = RAW / "queries"
OUTPUT = ROOT / "results/pilot"
SNAPSHOT = RAW / "civic/01-Nov-2026-ClinicalEvidenceSummaries.tsv"

cases = [
    ("BM-P01", "BRAF", "P15056", "V600E", "Vemurafenib", "CHEMBL1229517",
     "Skin Melanoma", "8923", "previously untreated metastatic melanoma",
     "clinical", [1409]),
    ("BM-P02", "BRAF", "P15056", "V600E", "Vemurafenib", "CHEMBL1229517",
     "Colorectal Cancer", "9256", "metastatic CRC, mostly previously treated",
     "clinical", [1405, 99, 5960]),
    ("BM-P03", "BRAF", "P15056", "V600E", "Vemurafenib", "CHEMBL1229517",
     "Papillary Thyroid Carcinoma", "3969", "recurrent/metastatic radioiodine-refractory PTC",
     "clinical", [1591, 9018]),
    ("BM-P04", "PIK3CA", "P42336", "E542K", "PI-103", "CHEMBL573339",
     "HER2 Positive Breast Cancer", "0060079", "HCC202; variant call under review",
     "cell line", [2058]),
    ("BM-P05", "PIK3CA", "P42336", "E542K", "PI-103", "CHEMBL573339",
     "Breast Cancer", "1612", "KPL-1, luminal-like as reported in CIViC; variant call under review",
     "cell line", [8007]),
]

edges = []


def json_raw(file):
    return json.loads((QUERY / file).read_text(encoding="utf-8"))


def edge(identifier, case_ids, subject, relation, obj, context, source, file,
         locator, excerpt, kind="fact", premises=()):
    if kind == "inference":
        source = [entry["source_id"] for entry in edges if entry["id"] in premises]
        locator = "premises"
        excerpt = [{"edge": entry["id"], "evidence": entry["original_evidence"]}
                   for entry in edges if entry["id"] in premises]
    edges.append({
        "id": identifier, "cases": case_ids, "subject": subject, "relation": relation,
        "object": obj, "context": context, "source_id": source,
        "raw_file": (f"data/raw/{file}" if file and file.startswith("civic/")
                     else f"data/raw/queries/{file}" if file else None),
        "locator": locator, "original_evidence": excerpt, "kind": kind,
        "premises": list(premises),
    })


def before_period(text):
    return text.split(". ", 1)[0].rstrip(".") + "."


def pubmed_edge(identifier, case_ids, subject, relation, obj, context, pmid, excerpt):
    abstract = abstracts[str(pmid)]
    if excerpt not in abstract:
        raise ValueError(f"PMID {pmid}: excerpt missing: {excerpt}")
    edge(identifier, case_ids, subject, relation, obj, context, f"PMID:{pmid}",
         "pubmed/pilot.xml", "MedlineCitation/Article/Abstract", excerpt)


def write(name, value):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    labels = {}
    with SNAPSHOT.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            labels[int(row["evidence_id"])] = row

    inputs = []
    references = []
    for case_id, gene, protein, change, drug, molecule, disease, doid, scope, setting, ids in cases:
        inputs.append({
            "case_id": case_id, "gene": gene, "protein": f"UniProt:{protein}",
            "protein_change": f"p.{change}", "drug": drug, "drug_id": f"ChEMBL:{molecule}",
            "disease": disease, "disease_id": f"DOID:{doid}", "context": scope,
            "setting": setting, "regimen": "monotherapy",
        })
        references.append({
            "case_id": case_id,
            "evidence_items": [{key: labels[number][key] for key in (
                "evidence_id", "evidence_direction", "evidence_level", "significance",
                "source_type", "citation_id", "nct_ids", "evidence_statement",
                "evidence_civic_url",
            )} for number in ids],
        })
    write("case_inputs.json", inputs)
    write("civic_references.json", references)

    braf = ["BM-P01", "BM-P02", "BM-P03"]
    pi = ["BM-P04", "BM-P05"]
    for prefix, ids, accession, variant_id, variant in [
        ("B", braf, "P15056", "VAR_018629", "p.Val600Glu"),
        ("P", pi, "P42336", "VAR_026173", "p.Glu542Lys"),
    ]:
        file = f"uniprot/{accession}.json"
        protein = json_raw(file)
        function = next(c["texts"][0]["value"] for c in protein["comments"]
                        if c["commentType"] == "FUNCTION")
        feature = next(f for f in protein["features"] if f.get("featureId") == variant_id)
        gene = protein["genes"][0]["geneName"]["value"]
        edge(prefix + "01", ids, f"UniProt:{accession}", "has_protein_function",
             "MAPK signal transduction" if prefix == "B" else "PIP3 production",
             "human reference protein", f"UniProt:{accession}", file,
             "comments[FUNCTION].texts[0]", before_period(function))
        edge(prefix + "02", ids, f"{gene} {variant}", "annotated_variant_of", f"UniProt:{accession}",
             "human protein sequence; disease and assay conditions in source annotation",
             f"UniProt:{accession}#{variant_id}", file, f"features[featureId={variant_id}]",
             feature["description"])
    for identifier, ids, event, subject, relation, obj in [
        ("B03", braf, "R-HSA-6802912", "BRAF p.Val600Glu", "constitutively_activates", "MAP2K/ERK"),
        ("P03", pi, "R-HSA-2219528", "UniProt:P42336", "can_encode_catalytic_subunit_of", "Class IA PI3K"),
    ]:
        file = f"reactome/{event}.json"
        record = json_raw(file)
        edge(identifier, ids, subject, relation, obj, "human pathway event; general mechanism",
             f"Reactome:{record['stIdVersion']}", file, "summation[0].text",
             before_period(record["summation"][0]["text"]))

    file = "chembl/CHEMBL1229517-mechanisms.json"
    mechanism = json_raw(file)["mechanisms"][0]
    target = json_raw("chembl/CHEMBL5145.json")["target_components"][0]["accession"]
    edge("B04", braf, "ChEMBL:CHEMBL1229517", "inhibits", f"UniProt:{target} p.Val600Glu",
         "human, target/variant annotation; no tumor response endpoint", "ChEMBL:mechanism/995",
         file, "mechanisms[mec_id=995]; target CHEMBL5145 → P15056",
         {key: mechanism[key] for key in ("mechanism_of_action", "mechanism_comment", "action_type")})
    for identifier, target_id, activity_id in [
        ("P04", "CHEMBL4005", 7990923), ("P05", "CHEMBL2842", 14972879),
    ]:
        file = f"chembl/CHEMBL573339-{target_id}-ic50.json"
        activity = next(a for a in json_raw(file)["activities"] if a["activity_id"] == activity_id)
        target = json_raw(f"chembl/{target_id}.json")["target_components"][0]["accession"]
        edge(identifier, pi, "ChEMBL:CHEMBL573339", "inhibits_in_assay", f"UniProt:{target}",
             "biochemical assay; target ID assignment; biochemical IC50",
             f"ChEMBL:activity/{activity_id}", file, f"activities[activity_id={activity_id}]",
             {key: activity[key] for key in ("assay_chembl_id", "assay_description",
                                              "standard_value", "standard_units", "document_chembl_id")})

    abstracts = {
        article.findtext("MedlineCitation/PMID"): " ".join(
            "".join(block.itertext()) for block in article.findall(".//Abstract/AbstractText")
        )
        for article in ET.parse(QUERY / "pubmed/pilot.xml").findall("PubmedArticle")
    }
    pubmed_edge("B05", ["BM-P01", "BM-P02"], "BRAF(V600E) inhibition",
                "rapid_feedback_activates", "EGFR", "colon cancer models; contrasting melanoma models",
                22281684, "BRAF(V600E) inhibition causes a rapid feedback activation of EGFR")
    pubmed_edge("B06", ["BM-P02"], "EGFR→RAS/CRAF", "reactivates", "ERK",
                "BRAF-mutant CRC cells treated with vemurafenib; transient initial pERK decrease",
                22448344, "rapid ERK re-activation occurred through EGFR-mediated activation of RAS and CRAF")
    pubmed_edge("B07", ["BM-P01"], "Melanoma cells", "show_low_expression_of", "EGFR",
                "melanoma models in this study", 22281684, "Melanoma cells express low levels of EGFR")
    pubmed_edge("B08", ["BM-P03"], "HER3 signaling with autocrine NRG1", "associated_with_rebound_of",
                "ERK", "vemurafenib-exposed BRAF-mutant thyroid cancer models", 23365119,
                "The rebound in extracellular signal-regulated kinase (ERK) in thyroid cells is accompanied by increased HER3 signaling")
    pubmed_edge("B09", ["BM-P01"], "Vemurafenib", "response_rate_compared_with", "48% vs 5%",
                "BRIM-3, 675 randomized; vemurafenib vs dacarbazine",
                21639808, "Response rates were 48% for vemurafenib and 5% for dacarbazine.")
    pubmed_edge("B10", ["BM-P02"], "Vemurafenib", "observed_confirmed_partial_response", "1/21",
                "metastatic BRAF V600E CRC; monotherapy; 20 previously treated; RECIST",
                26460303, "one patient had a confirmed partial response (5%; 95% CI, 1% to 24%)")
    pubmed_edge("B11", ["BM-P03"], "Vemurafenib", "observed_partial_response", "10/26",
                "radioiodine-refractory PTC without prior VEGFR multikinase inhibitor; single arm",
                27460442, "Partial responses were recorded in ten of 26 patients in cohort 1")
    pubmed_edge("B12", ["BM-P02"], "Vemurafenib", "inhibits_growth_of", "some BRAF V600E CRC xenografts",
                "selected preclinical models; growth endpoint", 22180495,
                "inhibiting tumor growth in BRAF(V600E) bearing xenograft models")
    pubmed_edge("P06", pi, "PI-103", "inhibits", "PI3Kα and mTOR",
                "biochemical and glioma experiments; no breast line response assigned", 16697955,
                "its ability to inhibit both PI3 kinase alpha and mTOR")
    for identifier, case_id, cell_line, accession in [
        ("P07", "BM-P04", "HCC202", "CVCL_2062"),
        ("P08", "BM-P05", "KPL-1", "CVCL_2094"),
    ]:
        file = f"cellosaurus/{accession}.json"
        entry = json_raw(file)["Cellosaurus"]["cell-line-list"][0]
        variant = next(record for record in entry["sequence-variation-list"]
                       if record.get("mutation-description", "").startswith("p.Glu545Lys"))
        edge(identifier, [case_id], cell_line, "reported_variant", "PIK3CA p.Glu545Lys",
             "reference cell line; stock identity and original assay genotype under review",
             f"Cellosaurus:{accession}", file, "sequence-variation-list", variant)
    for identifier, case_id, cell_line, row, readout in [
        ("P09", "BM-P04", "HCC202", 38, 0.426666666666666),
        ("P10", "BM-P05", "KPL-1", 33, 7.62333333333333),
    ]:
        edge(identifier, [case_id], cell_line, "pi103_viability_ic50_reported", readout,
             "breast cell viability; supplement header mM, CIViC uses µM",
             "PMID:20453058#SupplementaryTableS1",
             "civic/PMID20453058-SupplementaryTableS1.xls", f"Sheet1!D1,D{row}",
             {"PI-103 IC50 (mM)": readout})

    edge("I01", ["BM-P01"], "Vemurafenib in BRIM-3 context", "supports_response",
         "Sensitivity/Response", "specified metastatic skin melanoma", None, None,
         None, None, "inference", ["B02", "B03", "B04", "B07", "B09"])
    edge("I02", ["BM-P02"], "Vemurafenib in metastatic CRC", "shows_limited_activity",
         "Insufficient evidence for a strict three-class label", "specified previously treated cohort",
         None, None, None, None, "inference", ["B04", "B05", "B06", "B10", "B12"])
    edge("I03", ["BM-P03"], "Vemurafenib in radioiodine-refractory PTC", "supports_response",
         "Sensitivity/Response", "best supported in VEGFR inhibitor–naïve cohort", None, None,
         None, None, "inference", ["B04", "B08", "B11"])
    edge("I04", ["BM-P04", "BM-P05"], "PI-103 in the two breast models", "response_unresolved",
         "Insufficient evidence for an independently verified direction",
         "cell viability differs; independently reported alleles differ from the case inputs",
         None, None, None, None, "inference", ["P02", "P03", "P04", "P05", "P06", "P07", "P08", "P09", "P10"])

    write("evidence_graph.json", {
        "graph_type": "context-qualified evidence statements",
        "case_ids": [item["case_id"] for item in inputs],
        "edges": edges,
    })
