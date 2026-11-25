import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from biomdt.entity_index import BiomedicalEntityIndex


def test_cross_database_gene_aliases_resolve_to_one_gene_node_with_external_ids():
    index = BiomedicalEntityIndex()
    index.add_retrieval({
        "database": "uniprot",
        "records": [{"id": "P38398", "gene": "BRCA1",
                     "protein_name": "Breast cancer type 1 susceptibility protein"}],
    })
    index.add_retrieval({
        "database": "open_targets",
        "records": [{"id": "ENSG00000012048", "approvedSymbol": "BRCA1",
                     "approvedName": "BRCA1 DNA repair associated"}],
    })

    gene = index.resolve("BRCA1", "Gene")
    protein = index.resolve("P38398", "Protein")

    assert gene["id"] == "Gene:BRCA1"
    assert gene["identifiers"] == ["ENSG00000012048"]
    assert protein["id"] == "UniProt:P38398"
    assert any(edge["type"] == "encodes" for edge in index.edges)


def test_pathway_and_drug_ids_are_preserved_as_distinct_entity_types():
    index = BiomedicalEntityIndex()
    index.add_retrieval({
        "database": "kegg",
        "records": [{"id": "hsa:672", "symbol": "BRCA1", "pathways": [
            {"id": "hsa05224", "name": "Breast cancer"},
        ]}],
    })
    index.add_retrieval({
        "database": "chembl",
        "records": [{"molecule_chembl_id": "CHEMBL521686", "pref_name": "OLAPARIB"}],
    })

    gene = index.resolve("BRCA1", "Gene")
    pathway = index.resolve("Breast cancer", "Pathway")
    drug = index.resolve("OLAPARIB", "Drug")

    assert "hsa:672" in gene["identifiers"]
    assert pathway["id"] == "KEGG:hsa05224"
    assert drug["id"] == "ChEMBL:CHEMBL521686"
