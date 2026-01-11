#!/usr/bin/env python
"""
Evaluate search quality using Average Precision (AP) and Mean Average Precision (MAP).

Usage:
    python evaluate_search.py --queries test_queries.json --top-k 20 --scope all
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Any, List, Dict

import requests

from settings import ELASTICSEARCH_URL, INDEX_NAME
from settings import USE_COCCOC_TOKENIZER
from tokenizer_client import tokenize

# Override index for testing - change this to test different indices
INDEX_NAME = "test-stories-50"  # Uncomment to use test index


def search_elasticsearch(
    query: str,
    scope: str = "all",
    top_k: int = 20,
    index_name: str = INDEX_NAME,
    es_url: str = ELASTICSEARCH_URL,
) -> List[str]:
    """
    Search Elasticsearch and return list of document IDs in ranked order.
    Mimics the web_app.py search logic but returns just doc IDs.
    """
    # Mirror production behavior: if the index stores pre-tokenized text
    # (e.g. compound words joined by underscores), then the query needs to be
    # tokenized the same way for a fair evaluation.
    if USE_COCCOC_TOKENIZER:
        query = tokenize(query, use_coccoc=True)

    # Build a simple multi_match query that mirrors the web app behavior
    search_title = scope in {"all", "title"}
    search_content = scope in {"all", "content"}

    fields: List[str] = []
    if search_title:
        fields.extend(["title^6", "title.autocomplete^3"])
    if search_content:
        fields.extend(["content^6"])

    if not fields:
        fields = ["title^6", "content^6"]

    es_query = {
        "query": {
            "function_score": {
                "query": {
                    "bool": {
                        "should": [
                            {"multi_match": {"query": query, "fields": fields, "type": "best_fields"}},
                            {"multi_match": {"query": query, "fields": fields, "type": "phrase", "slop": 3}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "functions": [
                    {"filter": {"term": {"doc_type.keyword": "story"}}, "weight": 6.0},
                    {"filter": {"term": {"doc_type.keyword": "chapter"}}, "weight": 0.2},
                ],
                "score_mode": "first",
                "boost_mode": "multiply",
            }
        },
        "size": top_k,
        "_source": False,
    }

    try:
        resp = requests.post(
            f"{es_url}/{index_name}/_search",
            json=es_query,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        return [hit["_id"] for hit in hits]
    except Exception as e:
        print(f"Error searching for '{query}': {e}", file=sys.stderr)
        return []


def calculate_average_precision(ranked_docs: List[str], relevant_docs: set[str]) -> float:
    """
    Calculate Average Precision (AP) for a single query.

    AP = (1/R) * sum(P(k) * rel(k)) for k=1 to n

    Where:
    - R = total number of relevant documents
    - P(k) = precision at position k (# relevant in top k / k)
    - rel(k) = 1 if doc at position k is relevant, else 0
    """
    if not relevant_docs or not ranked_docs:
        return 0.0

    R = len(relevant_docs)
    precision_sum = 0.0
    num_relevant_found = 0

    for k, doc_id in enumerate(ranked_docs, start=1):
        if doc_id in relevant_docs:
            num_relevant_found += 1
            precision_at_k = num_relevant_found / k
            precision_sum += precision_at_k

    return precision_sum / R if R > 0 else 0.0


def evaluate_queries(
    test_queries: List[Dict[str, Any]],
    scope: str = "all",
    top_k: int = 20,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Evaluate all test queries and return detailed results.
    """
    results = []
    ap_scores = []

    for i, test_case in enumerate(test_queries, start=1):
        query_text = test_case["query"]
        query_scope = test_case.get("scope", scope)
        relevant_docs = set(test_case["relevant_docs"])
        description = test_case.get("description", "")

        if verbose:
            print(f"\n[{i}/{len(test_queries)}] Query: '{query_text}'")
            print(f"  Description: {description}")
            print(f"  Relevant docs: {relevant_docs}")

        ranked_docs = search_elasticsearch(query_text, scope=query_scope, top_k=top_k)

        if verbose:
            print(f"  Retrieved {len(ranked_docs)} docs")

        ap = calculate_average_precision(ranked_docs, relevant_docs)
        ap_scores.append(ap)

        # Find positions of relevant docs in the ranking
        relevant_positions = []
        for pos, doc_id in enumerate(ranked_docs, start=1):
            if doc_id in relevant_docs:
                relevant_positions.append((pos, doc_id))

        result = {
            "query": query_text,
            "description": description,
            "scope": query_scope,
            "ap": ap,
            "relevant_docs": list(relevant_docs),  # Add this for table display
            "relevant_count": len(relevant_docs),
            "retrieved_count": len(ranked_docs),
            "found_count": len(relevant_positions),
            "relevant_positions": relevant_positions,
            "top_5_docs": ranked_docs[:5],
            "all_docs": ranked_docs,  # Add full ranking for table display
        }
        results.append(result)

        if verbose:
            print(f"  AP: {ap:.4f}")
            if relevant_positions:
                print(f"  Relevant docs found at positions: {[pos for pos, _ in relevant_positions]}")
            else:
                print("  No relevant docs found in top-k results")

    map_score = sum(ap_scores) / len(ap_scores) if ap_scores else 0.0

    return {
        "map": map_score,
        "num_queries": len(test_queries),
        "scope": scope,
        "top_k": top_k,
        "per_query_results": results,
    }


def print_table_report(eval_results: Dict[str, Any], top_n: int = 10) -> None:
    """
    Print evaluation results in a table format showing binary relevance at each position.
    Similar to academic IR evaluation tables.
    """
    print("\n" + "=" * 120)
    print("SEARCH EVALUATION - TABLE FORMAT")
    print("=" * 120)
    print(f"Scope: {eval_results['scope']} | Top-K: {eval_results['top_k']} | Queries: {eval_results['num_queries']}")
    print(f"Mean Average Precision (MAP): {eval_results['map']:.4f}")
    print("=" * 120)

    # Create header
    header = ["Truy vấn (Query)"]
    for i in range(1, top_n + 1):
        header.append(f"d{i}")
    header.append("AP")
    
    # Calculate column widths
    query_width = 40
    doc_width = 4
    ap_width = 7
    
    # Print header
    header_line = f"{'Truy vấn':<{query_width}}"
    for i in range(1, top_n + 1):
        header_line += f" | {'d' + str(i):^{doc_width}}"
    header_line += f" | {'AP':^{ap_width}}"
    print("\n" + header_line)
    print("-" * len(header_line))
    
    # Print each query result
    for result in eval_results["per_query_results"]:
        query_text = result["query"]
        if len(query_text) > query_width - 3:
            query_text = query_text[:query_width - 3] + "..."
        
        # Build relevance vector (1 if relevant at position i, 0 otherwise)
        relevance_vector = [0] * top_n
        relevant_docs_set = set(result["relevant_docs"])
        
        # Use all_docs if available, otherwise fall back to top_5_docs
        retrieved_docs = result.get("all_docs", result["top_5_docs"])
        
        for pos, doc_id in enumerate(retrieved_docs[:top_n], start=1):
            if doc_id in relevant_docs_set:
                relevance_vector[pos - 1] = 1
        
        # Print row
        row = f"{query_text:<{query_width}}"
        for rel in relevance_vector:
            row += f" | {rel:^{doc_width}}"
        row += f" | {result['ap']:^{ap_width}.3f}"
        print(row)
    
    print("-" * len(header_line))
    print(f"{'MAP':<{query_width}}" + " " * (len(header_line) - query_width - ap_width - 3) + f" | {eval_results['map']:^{ap_width}.3f}")
    print("=" * 120)
    
    # Summary statistics
    ap_scores = [r["ap"] for r in eval_results["per_query_results"]]
    perfect_queries = sum(1 for ap in ap_scores if ap == 1.0)
    zero_queries = sum(1 for ap in ap_scores if ap == 0.0)
    
    print(f"\nSummary: Perfect (AP=1.0): {perfect_queries}/{len(ap_scores)} | "
          f"Failed (AP=0.0): {zero_queries}/{len(ap_scores)} | "
          f"Min: {min(ap_scores):.3f} | Max: {max(ap_scores):.3f}")
    print("=" * 120)


def export_table_csv(eval_results: Dict[str, Any], filename: str, top_n: int = 10) -> None:
    """
    Export evaluation results to CSV file in table format.
    """
    with open(filename, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        
        # Write header
        header = ["Query"]
        for i in range(1, top_n + 1):
            header.append(f"d{i}")
        header.append("AP")
        writer.writerow(header)
        
        # Write each query result
        for result in eval_results["per_query_results"]:
            row = [result["query"]]
            
            # Build relevance vector
            relevance_vector = [0] * top_n
            relevant_docs_set = set(result["relevant_docs"])
            retrieved_docs = result.get("all_docs", result["top_5_docs"])
            
            for pos, doc_id in enumerate(retrieved_docs[:top_n], start=1):
                if doc_id in relevant_docs_set:
                    relevance_vector[pos - 1] = 1
            
            row.extend(relevance_vector)
            row.append(f"{result['ap']:.3f}")
            writer.writerow(row)
        
        # Write MAP row
        map_row = ["MAP"] + [""] * top_n + [f"{eval_results['map']:.3f}"]
        writer.writerow(map_row)
    
    print(f"\nTable exported to CSV: {filename}")


def print_report(eval_results: Dict[str, Any]) -> None:
    """
    Print a formatted evaluation report.
    """
    print("\n" + "=" * 80)
    print("SEARCH EVALUATION REPORT")
    print("=" * 80)
    print(f"Scope: {eval_results['scope']}")
    print(f"Top-K: {eval_results['top_k']}")
    print(f"Number of queries: {eval_results['num_queries']}")
    print(f"\nMean Average Precision (MAP): {eval_results['map']:.4f}")
    print("=" * 80)

    print("\nPer-Query Results:")
    print("-" * 80)

    for i, result in enumerate(eval_results["per_query_results"], start=1):
        print(f"\n{i}. Query: '{result['query']}'")
        print(f"   Description: {result['description']}")
        print(f"   Scope: {result['scope']}")
        print(f"   AP: {result['ap']:.4f}")
        print(f"   Relevant docs: {result['relevant_count']} | Found: {result['found_count']}/{result['retrieved_count']}")

        if result["relevant_positions"]:
            positions_str = ", ".join([f"#{pos} ({doc_id})" for pos, doc_id in result["relevant_positions"]])
            print(f"   Relevant at: {positions_str}")
        else:
            print("   ⚠ No relevant docs found in top-k")

        print(f"   Top 5 results: {result['top_5_docs'][:5]}")

    print("\n" + "=" * 80)

    # Summary statistics
    ap_scores = [r["ap"] for r in eval_results["per_query_results"]]
    perfect_queries = sum(1 for ap in ap_scores if ap == 1.0)
    zero_queries = sum(1 for ap in ap_scores if ap == 0.0)

    print("\nSummary:")
    print(f"  Perfect queries (AP=1.0): {perfect_queries}/{len(ap_scores)}")
    print(f"  Failed queries (AP=0.0): {zero_queries}/{len(ap_scores)}")
    if ap_scores:
        print(f"  Min AP: {min(ap_scores):.4f}")
        print(f"  Max AP: {max(ap_scores):.4f}")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate search quality using AP and MAP metrics"
    )
    parser.add_argument(
        "--queries",
        type=str,
        default="test_queries.json",
        help="Path to test queries JSON file (default: test_queries.json)",
    )
    parser.add_argument(
        "--scope",
        type=str,
        default="all",
        choices=["all", "title", "content"],
        help="Search scope: all, title, or content (default: all)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=20,
        help="Number of top results to retrieve (default: 20)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed progress during evaluation",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Save results to JSON file",
    )
    parser.add_argument(
        "--table",
        action="store_true",
        help="Use table format for output (like academic IR papers)",
    )
    parser.add_argument(
        "--table-cols",
        type=int,
        default=10,
        help="Number of document columns to show in table (default: 10)",
    )
    parser.add_argument(
        "--export-csv",
        type=str,
        help="Export table format to CSV file (e.g., results_table.csv)",
    )

    args = parser.parse_args()

    # Load test queries
    try:
        with open(args.queries, "r", encoding="utf-8") as f:
            test_queries = json.load(f)
    except Exception as e:
        print(f"Error loading test queries from '{args.queries}': {e}", file=sys.stderr)
        sys.exit(1)

    if not test_queries:
        print("No test queries found.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(test_queries)} test queries from {args.queries}")

    # Run evaluation
    eval_results = evaluate_queries(
        test_queries,
        scope=args.scope,
        top_k=args.top_k,
        verbose=args.verbose,
    )

    # Print report in chosen format
    if args.table:
        print_table_report(eval_results, top_n=args.table_cols)
    else:
        print_report(eval_results)

    # Export to CSV if requested
    if args.export_csv:
        export_table_csv(eval_results, args.export_csv, top_n=args.table_cols)

    # Save to file if requested
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(eval_results, f, ensure_ascii=False, indent=2)
            print(f"\nResults saved to: {args.output}")
        except Exception as e:
            print(f"Error saving results: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
