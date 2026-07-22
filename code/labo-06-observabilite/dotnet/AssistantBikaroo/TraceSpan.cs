namespace AssistantBikaroo;

/// <summary>Catégories de spans (identiques côté Python).</summary>
public static class SpanCategory
{
    public const string Llm = "llm";
    public const string Rag = "rag";
    public const string Mcp = "mcp";
    public const string Security = "security";
    public const string Workflow = "workflow";
    public const string Application = "application";
}

/// <summary>Statuts de trace et de span (identiques côté Python).</summary>
public static class TraceStatus
{
    public const string Running = "running";
    public const string Success = "success";
    public const string Completed = "completed";
    public const string Failed = "failed";
    public const string Cancelled = "cancelled";
    public const string Refused = "refused";
}

/// <summary>Résultats finaux possibles (identiques côté Python).</summary>
public static class TraceOutcome
{
    public const string Created = "created";
    public const string Cancelled = "cancelled";
    public const string Aborted = "aborted";
    public const string NotEligible = "not_eligible";
    public const string Refused = "refused";
    public const string Failed = "failed";
    public const string Answered = "answered";
}

/// <summary>Une opération mesurée à l'intérieur d'une trace.</summary>
public class TraceSpan
{
    public string SpanId { get; init; } = "";
    public string TraceId { get; init; } = "";
    public string Name { get; init; } = "";
    public string Category { get; init; } = "";
    public string StartedAt { get; init; } = "";
    public long OffsetMs { get; init; }
    public string EndedAt { get; set; } = "";
    public long DurationMs { get; set; }
    public string Status { get; set; } = TraceStatus.Running;
    public Dictionary<string, object?> Attributes { get; } = new();
    public string Error { get; set; } = "";

    public TraceSpan Set(string key, object? value)
    {
        Attributes[key] = value;
        return this;
    }
}
