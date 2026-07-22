namespace AssistantBikaroo;

/// <summary>
/// Métriques dérivées d'une trace. Les noms sont identiques côté Python pour que
/// l'export JSON des deux implémentations ait la même structure.
/// </summary>
public class TraceMetrics
{
    public long total_duration_ms { get; set; }
    public int llm_calls { get; set; }
    public long llm_duration_ms { get; set; }
    public int rag_searches { get; set; }
    public long rag_duration_ms { get; set; }
    public int mcp_calls { get; set; }
    public long mcp_duration_ms { get; set; }
    public int security_event_count { get; set; }
    public int workflow_transition_count { get; set; }
    public int error_count { get; set; }
    public string final_outcome { get; set; } = "";
    public int estimated_input_tokens { get; set; }
    public int estimated_output_tokens { get; set; }
    public int retrieved_chunks { get; set; }
    public int context_chars { get; set; }

    /// <summary>Estimation volontairement approximative : ~4 caractères par token.</summary>
    public static int EstimateTokens(string? text) => (text?.Length ?? 0) / 4;

    public static TraceMetrics From(TraceContext trace)
    {
        List<TraceSpan> ByCategory(string category) =>
            trace.Spans.Where(s => s.Category == category).ToList();

        var llm = ByCategory(SpanCategory.Llm);
        var rag = ByCategory(SpanCategory.Rag);
        var mcp = ByCategory(SpanCategory.Mcp);

        int SumAttr(List<TraceSpan> spans, string key) => spans.Sum(s =>
            s.Attributes.TryGetValue(key, out var v) && v is int i ? i : 0);

        return new TraceMetrics
        {
            total_duration_ms = trace.DurationMs,
            llm_calls = llm.Count,
            llm_duration_ms = llm.Sum(s => s.DurationMs),
            rag_searches = rag.Count,
            rag_duration_ms = rag.Sum(s => s.DurationMs),
            mcp_calls = mcp.Count,
            mcp_duration_ms = mcp.Sum(s => s.DurationMs),
            security_event_count = trace.SecurityEvents.Count,
            workflow_transition_count = trace.WorkflowTransitions.Count,
            error_count = trace.Spans.Count(s => s.Status == TraceStatus.Failed),
            final_outcome = trace.FinalOutcome,
            estimated_input_tokens = SumAttr(llm, "estimated_input_tokens"),
            estimated_output_tokens = SumAttr(llm, "estimated_output_tokens"),
            retrieved_chunks = SumAttr(rag, "result_count"),
            context_chars = SumAttr(rag, "context_chars"),
        };
    }
}
