from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from biomedical_evidence import (
    BioKnowledgeTools,
    SQLiteEvidenceCache,
)


def test_sqlite_cache_keys_include_database_operation_and_query_parameters(tmp_path):
    cache = SQLiteEvidenceCache(tmp_path / "cache.sqlite")
    first = {
        "database": "uniprot",
        "operation": "entry",
        "query_params": {"accession": "P15056"},
        "raw_result": {"primaryAccession": "P15056"},
        "records": [{"id": "P15056"}],
        "source_ids": ["P15056"],
        "database_version": "2026_04",
    }
    cache.put(first)

    assert cache.get("uniprot", "entry", {"accession": "P15056"}) == first
    assert cache.get("uniprot", "entry", {"accession": "P42336"}) is None
    assert cache.get("reactome", "entry", {"accession": "P15056"}) is None


def test_query_uses_cached_original_response_without_calling_transport(tmp_path):
    calls = []

    def transport(method, url, params=None, json_body=None):
        calls.append((method, url, params, json_body))
        return {
            "body": {"primaryAccession": "P15056", "entryType": "UniProtKB reviewed"},
            "headers": {"x-uniprot-release": "2026_04"},
            "status": 200,
        }

    cache = SQLiteEvidenceCache(tmp_path / "cache.sqlite")
    tools = BioKnowledgeTools(cache, transport=transport)
    first = tools.query("uniprot", "entry", accession="P15056")
    second = tools.query("uniprot", "entry", accession="P15056")

    assert len(calls) == 1
    assert first["raw_result"] == second["raw_result"]
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert first["source_ids"] == ["P15056"]
    assert first["database_version"] == "2026_04"
    assert first["raw_result"]["primaryAccession"] == "P15056"


def test_pubmed_record_normalization_preserves_pmid_and_doi(tmp_path):
    def transport(method, url, params=None, json_body=None):
        return {
            "body": {
                "esearchresult": {
                    "count": "1",
                    "idlist": ["12345678"],
                }
            },
            "headers": {"date": "Wed, 25 Nov 2026 00:00:00 GMT"},
            "status": 200,
        }

    tools = BioKnowledgeTools(
        SQLiteEvidenceCache(tmp_path / "cache.sqlite"), transport=transport
    )
    result = tools.query("pubmed", "search", term="TP53", limit=5)

    assert result["source_ids"] == ["12345678"]
    assert result["records"][0]["id"] == "12345678"


def test_kegg_gene_search_keeps_all_hits_for_exact_id_resolution(tmp_path):
    body = (
        "hsa:9577\tBABAM2; BRCA1-A complex member\n"
        "hsa:672\tBRCA1; breast cancer type 1 susceptibility protein\n"
    )

    def transport(method, url, params=None, json_body=None):
        return {"body": body, "headers": {}, "status": 200}

    tools = BioKnowledgeTools(
        SQLiteEvidenceCache(tmp_path / "cache.sqlite"), transport=transport
    )
    result = tools.query("kegg", "find_gene", query="BRCA1")

    assert result["source_ids"] == ["hsa:9577", "hsa:672"]
    assert result["records"][1]["name"].startswith("BRCA1")


def test_kegg_flat_gene_records_parse_symbol_and_pathway_fields(tmp_path):
    body = (
        "ENTRY       672               CDS       T01001\n"
        "SYMBOL      BRCA1, BRCAI, BRCC1\n"
        "NAME        breast cancer type 1 susceptibility protein\n"
        "ORGANISM    hsa  Homo sapiens (human)\n"
        "PATHWAY     hsa03440  Homologous recombination\n"
        "            hsa05224  Breast cancer\n"
    )

    def transport(method, url, params=None, json_body=None):
        return {"body": body, "headers": {}, "status": 200}

    tools = BioKnowledgeTools(
        SQLiteEvidenceCache(tmp_path / "cache.sqlite"), transport=transport
    )
    result = tools.query("kegg", "gene", identifier="hsa:672")

    assert result["source_ids"] == ["hsa:672"]
    assert result["records"][0]["symbol"] == "BRCA1"
    assert result["records"][0]["pathways"] == [
        {"id": "hsa03440", "name": "Homologous recombination"},
        {"id": "hsa05224", "name": "Breast cancer"},
    ]


def test_reactome_pathway_release_date_is_not_database_version(tmp_path):
    def transport(method, url, params=None, json_body=None):
        return {
            "body": [{
                "stId": "R-HSA-6802912",
                "stIdVersion": "R-HSA-6802912.4",
                "displayName": "High kinase activity BRAF mutants bind MAP2Ks and MAPKs",
                "speciesName": "Homo sapiens",
                "releaseDate": "2016-09-19",
            }],
            "headers": {},
            "status": 200,
        }

    tools = BioKnowledgeTools(
        SQLiteEvidenceCache(tmp_path / "cache.sqlite"), transport=transport
    )
    result = tools.query(
        "reactome", "pathways_by_uniprot", accession="P15056"
    )

    assert result["database_version"] is None
    assert result["records"][0]["stIdVersion"] == "R-HSA-6802912.4"


def test_open_targets_search_respects_requested_record_limit(tmp_path):
    def transport(method, url, params=None, json_body=None):
        return {
            "body": {
                "data": {
                    "search": {
                        "hits": [{"id": f"ENSG{i}", "name": f"Target {i}"} for i in range(5)]
                    }
                }
            },
            "headers": {},
            "status": 200,
        }

    tools = BioKnowledgeTools(
        SQLiteEvidenceCache(tmp_path / "cache.sqlite"), transport=transport
    )
    result = tools.query("open_targets", "search_target", query="BRCA1", limit=2)

    assert len(result["raw_result"]["data"]["search"]["hits"]) == 5
    assert result["source_ids"] == ["ENSG0", "ENSG1"]
    assert len(result["records"]) == 2


def test_open_targets_target_details_preserve_function_descriptions(tmp_path):
    def transport(method, url, params=None, json_body=None):
        return {"body": {"data": {"target": {
            "id": "ENSG00000157764", "approvedSymbol": "BRAF",
            "functionDescriptions": ["Protein kinase involved in MAPK signaling."],
            "proteinIds": [{"id": "P15056", "source": "uniprot"}],
        }}}, "headers": {}, "status": 200}

    tools = BioKnowledgeTools(SQLiteEvidenceCache(tmp_path / "cache.sqlite"), transport=transport)
    result = tools.query("open_targets", "target_details", ensembl_id="ENSG00000157764")

    assert result["records"][0]["functionDescriptions"] == [
        "Protein kinase involved in MAPK signaling."
    ]


def test_uniprot_entry_preserves_function_annotation(tmp_path):
    def transport(method, url, params=None, json_body=None):
        return {"body": {
            "primaryAccession": "P15056", "entryType": "UniProtKB reviewed",
            "genes": [{"geneName": {"value": "BRAF"}}],
            "proteinDescription": {"recommendedName": {"fullName": {"value": "B-Raf"}}},
            "comments": [{"commentType": "FUNCTION", "texts": [
                {"value": "Serine/threonine-protein kinase."}
            ]}],
        }, "headers": {}, "status": 200}

    tools = BioKnowledgeTools(SQLiteEvidenceCache(tmp_path / "cache.sqlite"), transport=transport)
    result = tools.query("uniprot", "entry", accession="P15056")

    assert result["records"][0]["function"] == "Serine/threonine-protein kinase."


def test_chembl_target_details_expose_uniprot_components(tmp_path):
    def transport(method, url, params=None, json_body=None):
        return {
            "body": {
                "target_chembl_id": "CHEMBL3390820",
                "pref_name": "Poly [ADP-ribose] polymerase 1",
                "target_components": [
                    {"accession": "P09874", "component_type": "PROTEIN"}
                ],
            },
            "headers": {},
            "status": 200,
        }

    tools = BioKnowledgeTools(
        SQLiteEvidenceCache(tmp_path / "cache.sqlite"), transport=transport
    )
    result = tools.query(
        "chembl", "target_details", target_id="CHEMBL3390820"
    )

    assert result["source_ids"] == ["CHEMBL3390820"]
    assert result["records"][0]["target_components"][0]["accession"] == "P09874"


def test_pubmed_fetch_retries_once_after_tls_eof(monkeypatch):
    from io import BytesIO
    from ssl import SSLEOFError
    from urllib.error import URLError
    from unittest.mock import Mock
    from biomedical_evidence import _default_transport

    response = BytesIO(b"<PubmedArticleSet/>")
    response.status = 200
    response.url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    response.headers = {"content-type": "application/xml"}
    fetch = Mock(side_effect=[URLError(SSLEOFError("unexpected EOF")), response])
    monkeypatch.setattr("biomedical_evidence.urlopen", fetch)

    assert _default_transport("GET", response.url, {"db": "pubmed"})["status"] == 200
    assert fetch.call_count == 2
