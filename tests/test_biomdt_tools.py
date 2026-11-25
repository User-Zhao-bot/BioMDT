import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from biomdt.tools import BiomedicalToolExecutor


class StubKnowledgeTools:
    def __init__(self):
        self.calls = []

    def query(self, database, operation, **params):
        self.calls.append((database, operation, params))
        if database == "uniprot":
            records = [{"id": "P38398", "gene": "BRCA1", "protein_name": "BRCA1 protein",
                        "function": "DNA repair", "organism": "Homo sapiens"}]
            source_ids = ["P38398"]
        elif database == "open_targets":
            records = [{"id": "ENSG00000012048", "approvedSymbol": "BRCA1",
                        "functionDescriptions": ["DNA repair"]}]
            source_ids = ["ENSG00000012048"]
        else:
            records, source_ids = [], []
        return {"database": database, "operation": operation, "query_params": params,
                "records": records, "source_ids": source_ids, "request": {"status": 200},
                "cache_hit": False}


def test_genomics_role_uses_uniprot_and_open_targets_and_returns_compact_function_data():
    tools = StubKnowledgeTools()
    executor = BiomedicalToolExecutor(tools)
    results = executor.retrieve("genomics", {"genes": ["BRCA1"]}, [])

    assert [(database, operation) for database, operation, _ in tools.calls] == [
        ("uniprot", "search_gene"), ("open_targets", "search_target"),
    ]
    assert results[0]["records"][0]["function"] == "DNA repair"
    assert results[1]["records"][0]["functionDescriptions"] == ["DNA repair"]
    assert all("answers" not in result for result in results)


def test_literature_search_uses_short_entity_queries_and_pmid_prefixed_sources():
    class PubMedTools:
        def __init__(self):
            self.calls = []

        def query(self, database, operation, **params):
            self.calls.append((database, operation, params))
            if operation == "search":
                return {"database": database, "operation": operation,
                        "query_params": params, "records": [{"id": "42939506"}],
                        "source_ids": ["42939506"], "request": {"status": 200}}
            return {"database": database, "operation": operation,
                    "query_params": params, "records": [], "source_ids": [],
                    "request": {"status": 200}}

    tools = PubMedTools()
    results = BiomedicalToolExecutor(tools).retrieve(
        "literature",
        {"genes": [], "proteins": [], "diseases": [], "drugs": [],
         "uniprot_ids": [], "keywords": ["CYH33"]},
        [{"claim_id": "C1", "text": "CYH33 inhibits PI3Kalpha signaling.",
          "required_evidence_types": ["literature"]}],
    )

    assert tools.calls[0][2]["term"] == "CYH33[All Fields]"
    assert results[0]["source_ids"] == ["PMID:42939506"]


def test_literature_lookup_uses_numeric_pmids_at_database_boundary():
    from unittest.mock import Mock
    service = Mock()
    service.query.side_effect = lambda db, op, **params: {
        "records": [{"id": "40533463"}], "source_ids": ["40533463"],
    }
    calls = BiomedicalToolExecutor(service).retrieve("literature", {"keywords": ["CYH33"]}, [])
    assert calls[0]["source_ids"] == ["PMID:40533463"]
    assert [call["query_params"]["pmids"] for call in calls[1:]] == [["40533463"], ["40533463"]]


def test_literature_reserves_query_for_intervention_and_disease():
    tools = StubKnowledgeTools()
    BiomedicalToolExecutor(tools).retrieve("literature", {
        "drugs": ["TrialDrug"], "diseases": ["test cancer"],
        "keywords": ["TrialDrug cancer phosphorylation immune glucose marker response"],
    }, [])
    assert tools.calls[0][2]["term"] == '"TrialDrug"[All Fields] AND "test cancer"[All Fields]'
    assert any(call[2].get("term") == "TrialDrug[All Fields]" for call in tools.calls)


def test_literature_fetches_open_access_results_for_focused_paper():
    from unittest.mock import Mock

    service = Mock()

    def query(database, operation, **params):
        records = {
            ("pubmed", "search"): [{"id": "40533463"}],
            ("pubtator", "annotations"): [{
                "pmid": 40533463,
                "passages": [{"infons": {"article-id_pmc": "PMC12177050"}}],
            }],
            ("pubmed", "full_text"): [{
                "id": "40533463", "offset": "200", "text": "The treatment changed phosphorylation.",
            }],
        }.get((database, operation), [])
        return {"source_ids": ["40533463"] if records else [], "records": records}

    service.query.side_effect = query
    calls = BiomedicalToolExecutor(service).retrieve(
        "literature", {"drugs": ["CYH33"], "diseases": ["HNSCC"]},
        [{"text": "Does treatment change phosphorylation?"}],
    )
    result = calls[-1]
    assert result["operation"] == "full_text"
    assert result["query_params"]["pmcid"] == "PMC12177050"
    assert result["source_ids"] == ["PMID:40533463"]
    assert result["records"][0]["offset"] == "200"


def test_target_ranking_allocates_a_fetched_article_to_each_candidate():
    from unittest.mock import Mock
    service = Mock()
    candidates = ["GENE1", "GENE2", "GENE3", "GENE4", "GENE5"]

    def query(database, operation, **params):
        if operation == "search":
            symbol = params["term"].split('"')[1]
            pmid = str(candidates.index(symbol) + 1)
            return {"records": [{"id": pmid}], "source_ids": [pmid]}
        return {"records": [], "source_ids": []}

    service.query.side_effect = query
    calls = BiomedicalToolExecutor(service).retrieve("literature", {
        "target_candidates": candidates, "genes": candidates, "diseases": ["test disease"],
    }, [])
    assert [pmid for call in calls if call["operation"] == "fetch"
            for pmid in call["query_params"]["pmids"]] == ["1", "2", "3", "4", "5"]
