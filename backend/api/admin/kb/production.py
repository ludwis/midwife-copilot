"""GET /api/admin/kb/production/query — Test query against the production Vertex AI Search index.

Implements queryProduction from kb-review.yaml.
Auth: inherited from /api/admin router (X-Admin-Token via main.py).

Env vars:
  GCP_PROJECT_ID                    — GCP project ID
  VERTEX_SEARCH_LOCATION            — Discovery Engine location; defaults to 'eu'
  VERTEX_SEARCH_ENGINE_ID           — Vertex AI Search engine/app ID (Enterprise Edition path)
  VERTEX_SEARCH_DATASTORE_PRODUCTION — fallback data store ID if engine ID not set; defaults to 'midwife-production'
"""
from __future__ import annotations

import os
from typing import Any

import core.audit
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/production/query")
async def query_production(q: str | None = None, limit: int = 5) -> dict[str, Any]:
    """Query the production Vertex AI Search index and return matching chunks with snippets.

    Raises:
        400 — missing or empty query
    """
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required and must not be empty.")

    limit = min(max(limit, 1), 10)

    from google.api_core.client_options import ClientOptions  # type: ignore[import]
    from google.cloud import discoveryengine_v1 as discoveryengine  # type: ignore[import]

    project = os.environ.get("GCP_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    location = os.environ.get("VERTEX_SEARCH_LOCATION") or os.environ.get("VERTEX_LOCATION", "eu")
    engine_id = (
        os.environ.get("VERTEX_SEARCH_ENGINE_ID")
        or os.environ.get("VERTEX_SEARCH_DATASTORE_PRODUCTION")
        or os.environ.get("VERTEX_PRODUCTION_DATA_STORE", "midwife-production")
    )

    # Regional endpoint required for non-global locations (eu, us).
    # See: https://cloud.google.com/generative-ai-app-builder/docs/locations#limitations
    api_endpoint = f"{location}-discoveryengine.googleapis.com" if location != "global" else "discoveryengine.googleapis.com"

    # Enterprise Edition requires the engine/app path, not dataStores path.
    # See: https://cloud.google.com/generative-ai-app-builder/docs/enterprise-edition
    serving_config = (
        f"projects/{project}/locations/{location}"
        f"/collections/default_collection"
        f"/engines/{engine_id}/servingConfigs/default_config"
    )

    client = discoveryengine.SearchServiceClient(
        client_options=ClientOptions(api_endpoint=api_endpoint)
    )
    request = discoveryengine.SearchRequest(
        serving_config=serving_config,
        query=q,
        page_size=limit,
        content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
            extractive_content_spec=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                max_extractive_answer_count=1,
            ),
        ),
    )

    response = client.search(request)

    results: list[dict[str, Any]] = []
    for result in response.results:
        doc = result.document

        # Vertex AI Search returns document fields as either struct_data (protobuf Struct)
        # or json_data (JSON string), depending on data store type. Try both.
        struct_data: dict[str, Any] = {}
        try:
            fields = doc.struct_data.fields
            if fields:
                struct_data = {k: v.string_value for k, v in fields.items()}
        except AttributeError:
            pass

        if not struct_data and doc.json_data:
            import json as _json
            try:
                struct_data = _json.loads(doc.json_data)
            except (ValueError, TypeError):
                pass

        # Extract snippet from extractive answers (Enterprise Edition feature)
        snippet = ""
        try:
            derived_fields = result.document.derived_struct_data.fields
            if "extractive_answers" in derived_fields:
                answers = derived_fields["extractive_answers"].list_value.values
                if answers:
                    content_field = answers[0].struct_value.fields.get("content")
                    if content_field is not None:
                        snippet = content_field.string_value
        except (AttributeError, KeyError):
            pass

        results.append(
            {
                "chunk_id": doc.id,
                "question": struct_data.get("question", ""),
                "answer": struct_data.get("answer", ""),
                "snippet": snippet,
                "promoted_at": struct_data.get("promoted_at"),
            }
        )

    core.audit.write_event(
        "kb_query_test",
        actor="admin",
        query_text=q,
        result_count=len(results),
    )

    return {
        "query": q,
        "results": results,
        "total_results": len(results),
    }
