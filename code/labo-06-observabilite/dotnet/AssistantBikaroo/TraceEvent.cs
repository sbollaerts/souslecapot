namespace AssistantBikaroo;

/// <summary>Types d'événements d'application (les types de sécurité viennent du labo 5).</summary>
public static class AppEventType
{
    public const string McpUnavailable = "mcp_unavailable";
    public const string RagNoResult = "rag_no_result";
    public const string LlmError = "llm_error";
    public const string WorkflowAborted = "workflow_aborted";
    public const string TraceExported = "trace_exported";
}

/// <summary>Un événement rattaché à une trace (application ou sécurité).</summary>
public class TraceEvent
{
    public string Timestamp { get; init; } = "";
    public string TraceId { get; init; } = "";
    public string EventType { get; init; } = "";
    public string Source { get; init; } = "";
    public string Severity { get; init; } = "";
    public string Details { get; init; } = "";
    public Dictionary<string, object?> Attributes { get; init; } = new();
}
