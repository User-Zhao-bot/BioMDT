"""Aggregate official grades, option scores, evidence audits and observed costs."""
from collections import Counter
import csv
import json
import re
from statistics import mean, median

from benchmark import DATA, case_result, option_scores, write_json
from deepevidence_data import TASK_FILES, evaluate_predictions, read_jsonl

IDENTIFIERS = re.compile(
    r"\b(?:PMCID?[:\s]*PMC\d+|PMC\d+|PMID[\s:*#]*(?:\d+)|"
    r"10\.\d{4,9}/[-.\w()/]+|[A-Za-z]{2,4}:\d+|R-[A-Z]{3}-\d+|CHEMBL\d+|"
    r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2}))\b",
    re.I,
)


def identifiers(text):
    values = {re.sub(r"[\s:*#]", "", match.group()).upper().rstrip(".")
              if match.group().upper().startswith(("PMID", "PMCID")) else match.group().upper().rstrip(".")
              for match in IDENTIFIERS.finditer(text)}
    return {value.removeprefix("PMCID") for value in values}


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def observed_mean(rows, key):
    values = [row[key] for row in rows if row.get(key) is not None]
    return mean(values) if values else None


def evidence_metrics(run, review):
    if run.get("method") == "direct" or run.get("prediction_status") not in {"completed", "abstention"}:
        return {}
    graph = run.get("evidence_graph", {})
    citations = set()
    direct_citations = set()
    sources = {}
    cited_evidence = []
    eligible_tools = []
    if run["method"] == "biomdt":
        explanation = " ".join([run.get("explanation") or "", run.get("biological_interpretation") or "",
                                json.dumps(run.get("key_paths") or [])])
        direct_citations = identifiers(explanation)
        evidence_ids = set(re.findall(r"\bE\d{4}\b", explanation))
        for first, last in re.findall(r"\bE(\d{4})\s*[–-]\s*E(\d{4})\b", explanation):
            evidence_ids.update(f"E{n:04d}" for n in range(int(first), int(last) + 1))
        evidence = {row["evidence_id"]: row for row in graph.get("evidence", [])}
        for evidence_id in sorted(evidence_ids):
            record = evidence.get(evidence_id)
            cited_evidence.append({"id": evidence_id, "record": record})
            citations.add((record or {}).get("source_id") or evidence_id)
        eligible_tools = [call for call in run.get("tool_calls", []) if not call.get("error")
                          and call.get("operation") != "search" and call.get("records")]
        for index, call in enumerate(run.get("tool_calls", [])):
            if call not in eligible_tools:
                continue
            for source in call.get("source_ids", []):
                sources.setdefault(source, []).append({"database": call["database"], "tool_index": index,
                                                        "operation": call["operation"],
                                                        "query_params": call["query_params"]})
            for source in identifiers(json.dumps(call["records"])):
                if source.startswith(("10.", "PMC")):
                    sources.setdefault(source, []).append({"database": call["database"], "tool_index": index,
                                                            "query_params": call["query_params"]})
    else:
        explanation = run.get("final_response") or ""
        citations.update(identifiers(explanation))
        for call in run.get("retrieval_log", []):
            if call.get("error"):
                continue
            eligible_tools.append(call)
            # Official tool wrappers may echo request parameters in a code block.
            raw = call["output"]
            output = raw.partition("### Output:")[2] if "### Executed Code:" in raw else raw
            returned = identifiers(output)
            if call["tool"] == "search_papers":
                # PubTator's formatted search response labels the identifier PubMedID.
                returned.update("PMID" + code for code in re.findall(r"PubMedID:\s*(\d+)", output, re.I))
            for source in returned:
                sources.setdefault(source, []).append({"database": call["database"], "tool": call["tool"],
                                                        "tool_call_id": call["tool_call_id"]})
    citations.update(direct_citations)
    traces = {source: sources.get(source, sources.get(source.upper(), [])) for source in sorted(citations)}
    # A source identifier can appear in a summary without the original record.
    traceable = sum(bool(value) for value in traces.values())
    review_rows = review.get("claims", [])
    if review_rows and any(row.get("verdict") not in {"supported", "partial", "contradicted",
                                                      "context_mismatch", "unverifiable"}
                           or not row.get("claim") or not row.get("source")
                           or not row.get("excerpt") or not row.get("context_assessment") for row in review_rows):
        raise ValueError("Evidence review requires a verdict, claim, source, excerpt and context assessment")
    cited_databases = sorted({match["database"] for matches in traces.values() for match in matches})
    activation = Counter(row["agent"] for row in run.get("agent_outputs", []))
    contributions = Counter(row.get("agent") for row in graph.get("evidence", []) if row.get("agent"))
    messages = [row for row in run.get("collaboration_messages", []) if row["sender"] != "Coordinator"]
    state_transitions = []
    previous = {}
    for snapshot in run.get("graph_snapshots", []):
        states = {key: state["status"] for key, state in snapshot["graph"]["claim_states"].items()}
        for claim, state in states.items():
            if claim in previous and previous[claim] != state:
                state_transitions.append({"claim": claim, "before": previous[claim], "after": state,
                                          "agent": snapshot.get("agent"), "round": snapshot["round"]})
        previous = states
    return {
        "traceability": (ratio(traceable, len(citations))
                         if run["method"] == "biomdt" or "retrieval_log" in run else None),
        "traceable_citations": traceable, "citations": len(citations), "traces": traces,
        "support_rate": ratio(sum(row["verdict"] == "supported" for row in review_rows), len(review_rows)),
        "reviewed_claims": len(review_rows), "review": review,
        "cross_source_integration": review.get("cross_source_integration"),
        "retrieved_databases": sorted({call["database"] for call in eligible_tools}),
        "cited_databases": cited_databases, "cited_evidence": cited_evidence,
        "paths": run.get("key_paths") or run.get("official_execution", {}).get("evidence_graph_data"),
        "agent_activations": dict(activation), "agent_evidence": dict(contributions),
        "collaborations": dict(Counter(f"{m['sender']} → {m['recipient']}" for m in messages)),
        "transferred_evidence": sum(len(m["existing_evidence_ids"]) for m in messages),
        "inapplicable_claim_evidence_links": (sum(s["context_mismatches"] for s in graph.get("claim_states", {}).values())
                                             if graph else None),
        "state_transitions": state_transitions,
        "resolved_gaps": sorted({r["claim"] for r in state_transitions
                                 if r["before"] in {"Missing", "Conflicting"} and r["after"] == "Supported"}),
    }


def efficiency(run):
    runtime = run.get("runtime", {})
    calls = runtime.get("llm_calls", run.get("tool_calls", []) if run["method"] == "deepevidence" else [])
    failures = run.get("http_failures")
    bio_tools = run.get("tool_calls", []) if run["method"] == "biomdt" else []
    cache_checks = [call for call in bio_tools if "cached" in call and not call.get("error")]
    row = {key: runtime.get(key) for key in ("input_tokens", "output_tokens", "total_tokens",
                                           "llm_call_count", "tool_call_count")}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        if row[key] is None and calls and all(key in call for call in calls):
            row[key] = sum(call[key] for call in calls)
    if row["llm_call_count"] is None and calls:
        row["llm_call_count"] = len(calls)
    return row | {"wall_seconds": run.get("wall_seconds"), "returned_model": runtime.get("model"),
                  "model_retries": sum(call.get("gateway_retries", 0) for call in calls) if failures is not None else None,
                  "model_http_failures": len(failures) if failures is not None else None,
                  "failed_requests_observed": (len(failures) if failures is not None else 0)
                    + sum(bool(call.get("error")) for call in bio_tools)
                    + sum(bool(call.get("error")) for call in run.get("retrieval_log", []))
                    + int(run.get("prediction_status") in {"model_error", "interface_error"}
                          and not failures),
                  "database_errors": (sum(bool(call.get("error")) for call in bio_tools)
                                      if "tool_calls" in run and run["method"] == "biomdt"
                                      else sum(bool(x.get("error")) for x in run["retrieval_log"])
                                      if "retrieval_log" in run else 0 if run["method"] == "direct" else None),
                  "cache_hits": sum(call["cached"] for call in cache_checks) if cache_checks else None,
                  "cache_checks": len(cache_checks) if cache_checks else None}


def csv_write(path, rows):
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def aggregate(rows):
    n = len(rows)
    quality_keys = ("precision", "recall", "f1")
    trace_rows = [r["evidence"] for r in rows if r["evidence"].get("traceability") is not None]
    review_rows = [r["evidence"] for r in rows if r["evidence"].get("support_rate") is not None]
    times = [r["wall_seconds"] for r in rows if r.get("wall_seconds") is not None]
    return {
        "expected": n, "attempted": sum(r["status"] != "not_run" for r in rows),
        "exact_match": ratio(sum(r["exact_match"] for r in rows), n),
        "coverage": ratio(sum(r["status"] in {"correct", "wrong"} for r in rows), n),
        **{key: ratio(sum(r[key] for r in rows), n) for key in quality_keys},
        "status_counts": dict(Counter(r["status"] for r in rows)),
        "runtime_median": median(times) if times else None,
        **{key: observed_mean(rows, key) for key in ("input_tokens", "output_tokens", "total_tokens",
                                                   "llm_call_count", "tool_call_count", "wall_seconds",
                                                   "database_errors", "model_retries", "model_http_failures",
                                                   "failed_requests_observed",
                                                   "cache_hits", "cache_checks")},
        "traceability": ratio(sum(e["traceable_citations"] for e in trace_rows),
                              sum(e["citations"] for e in trace_rows)),
        "support_rate": ratio(sum(e["support_rate"] * e["reviewed_claims"] for e in review_rows),
                              sum(e["reviewed_claims"] for e in review_rows)),
        "cross_source_integration": observed_mean([r["evidence"] for r in rows], "cross_source_integration"),
    }


def summarize(directory, plan):
    references = {row["id"]: row for row in read_jsonl(DATA / "references.jsonl")}
    inputs = plan["cases"]
    review_file = directory / "evidence_reviews.jsonl"
    reviews = {(row["method"], row["id"]): row for row in read_jsonl(review_file)} if review_file.exists() else {}
    review_plan_path = directory / "evidence_review_plan.json"
    if review_plan_path.exists():
        audit_ids = json.loads(review_plan_path.read_text())
        selected_tasks = {item["id"]: item["task_type"] for item in inputs}
        if (len(set(audit_ids)) != 9 or len(audit_ids) != 9
                or set(audit_ids) - selected_tasks.keys()
                or Counter(selected_tasks[key] for key in audit_ids) != Counter(dict.fromkeys(TASK_FILES, 3))):
            raise ValueError("Evidence review plan requires three scheduled cases in each task")
        if any(item not in audit_ids for _, item in reviews):
            raise ValueError("Evidence review includes cases outside the configured audit selection")
    output = {}
    per_case = []
    official = {}
    for method in plan["methods"]:
        runs = {}
        for item in inputs:
            path = case_result(directory, method, item["id"])
            if path.exists():
                runs[item["id"]] = json.loads(path.read_text())
        ref = [references[item["id"]] for item in inputs]
        grades = evaluate_predictions(inputs, ref, list(runs.values()))
        official[method] = grades
        method_cases = []
        for grade in grades["items"]:
            item = grade["item_id"]
            run = runs.get(item)
            score = grade["score"] or 0
            status = run["prediction_status"] if run else "not_run"
            if status == "completed":
                pred = run.get("prediction") or []
                valid_options = {o.split(".", 1)[0] for o in next(r["options"] for r in inputs if r["id"] == item)}
                if (not isinstance(pred, list) or not pred
                        or any(not isinstance(option, str) for option in pred)
                        or len(set(pred)) != len(pred) or not set(pred) <= valid_options):
                    status = "invalid_prediction"
                else:
                    status = "correct" if score else "wrong"
            prediction = run["prediction"] if status in {"correct", "wrong"} else []
            precision, recall, f1 = option_scores(prediction, references[item]["answers"])
            row = {"id": item, "method": method, "task_type": grade["task_type"], "status": status,
                   "exact_match": score, "precision": precision, "recall": recall, "f1": f1,
                   "evidence": evidence_metrics(run, reviews.get((method, item), {})) if run else {}}
            if run:
                row.update(efficiency(run))
            method_cases.append(row)
        per_case.extend(method_cases)
        output[method] = {}
        for protocol, rows in (("all_selected", method_cases),
                               ("unexposed_selected", [r for r in method_cases if r["id"] not in plan["exposed"]])):
            output[method][protocol] = {"overall": aggregate(rows)}
            output[method][protocol].update({key: aggregate([r for r in rows if r["task_type"] == key])
                                             for key in TASK_FILES})
    write_json(directory / "official_scores.json", official)
    write_json(directory / "summary.json", {"mode": plan["mode"], "methods": output, "cases": per_case})
    csv_write(directory / "cases.csv", [{k: v for k, v in row.items() if k != "evidence"} for row in per_case])
    summaries = []
    for method, protocols in output.items():
        for protocol, tasks in protocols.items():
            for task, values in tasks.items():
                summaries.append({"method": method, "protocol": protocol, "task": task,
                                  **{k: v for k, v in values.items() if k != "status_counts"}})
    csv_write(directory / "aggregates.csv", summaries)
    tables(directory, plan, output)


def tables(directory, plan, output):
    title = f"# {plan['mode']} results"
    markdown = [title, "", "Smoke and pilot results describe development runs. Unattempted rows count in the scheduled denominator.", ""]
    for protocol in ("all_selected", "unexposed_selected"):
        markdown.extend([f"## {protocol}", ""])
        groups = {
            "accuracy": ["Target ID", "MoA", "Metabolic Flux", "Overall Exact Match"],
            "options": ["Precision", "Recall", "F1", "Coverage"],
            "evidence": ["Evidence Traceability", "Evidence Support Rate", "Cross-source Integration"],
            "efficiency": ["Mean Input Tokens", "Mean Output Tokens", "Mean LLM Calls", "Mean Tool Calls", "Mean Runtime (s)"],
        }
        for table, columns in groups.items():
            rows = []
            for method, protocols in output.items():
                block = protocols[protocol]
                overall = block["overall"]
                label = "DeepEvidence (Adapted)" if method == "deepevidence" else {"direct": "Direct LLM", "biomdt": "BioMDT"}[method]
                values = {
                    "accuracy": [block[task]["exact_match"] if block[task]["attempted"] else None for task in TASK_FILES]
                                + [overall["exact_match"] if overall["attempted"] else None],
                    "options": [overall[key] if overall["attempted"] else None
                                for key in ("precision", "recall", "f1", "coverage")],
                    "evidence": [overall[key] for key in ("traceability", "support_rate", "cross_source_integration")],
                    "efficiency": [overall[key] for key in ("input_tokens", "output_tokens", "llm_call_count",
                                                          "tool_call_count", "wall_seconds")],
                }[table]
                rows.append(dict(zip(["Method", *columns], [label, *values])))
            csv_write(directory / f"{protocol}_{table}.csv", rows)
            markdown.extend([f"### {table}", "", "| Method | " + " | ".join(columns) + " |",
                             "| --- | " + " | ".join("---" for _ in columns) + " |"])
            for row in rows:
                cells = [str(v) if isinstance(v, str) else f"{v:.3f}" if v is not None else "—"
                         for v in row.values()]
                markdown.append("| " + " | ".join(cells) + " |")
            markdown.append("")
    (directory / "tables.md").write_text("\n".join(markdown), encoding="utf-8")
