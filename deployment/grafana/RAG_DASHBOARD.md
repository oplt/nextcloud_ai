# Grafana: RAG & chat observability

Import a Prometheus data source pointing at your scraped `{{backend}}/metrics` endpoint (see `deployment/README.md`).

Suggested panels (time series, 5m–1h range):

## 1. Embedding latency (p95)

```promql
histogram_quantile(
  0.95,
  sum(rate(nextcloud_ai_rag_embedding_seconds_bucket[5m])) by (le, provider)
)
```

## 2. Retrieval source volume (avg observed)

```promql
sum(rate(nextcloud_ai_rag_retrieval_sources_returned_sum[5m]))
/
clamp_min(sum(rate(nextcloud_ai_rag_retrieval_sources_returned_count[5m])), 1e-9)
```

## 3. Verification outcomes (stacked rate)

```promql
sum(rate(nextcloud_ai_rag_verification_decisions_total[5m])) by (result)
```

## 4. RAG stage errors

```promql
sum(rate(nextcloud_ai_rag_stage_errors_total[5m])) by (stage)
```

## 5. Graph expansion (applied vs not)

```promql
sum(rate(nextcloud_ai_rag_graph_expand_events_total[5m])) by (phase, applied)
```

## 6. Citation filter outcomes

```promql
sum(rate(nextcloud_ai_rag_citation_filter_events_total[5m])) by (outcome)
```

## 7. Low-confidence answers

```promql
sum(rate(nextcloud_ai_rag_chat_low_confidence_answers_total[5m]))
```

## 8. Intelligence extraction failures

```promql
sum(rate(nextcloud_ai_intelligence_extraction_failures_total[15m]))
```

Pair with `deployment/prometheus/rules_rag.yml` for Alertmanager notifications.
