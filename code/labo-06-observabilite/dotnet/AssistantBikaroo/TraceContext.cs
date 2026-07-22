using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace AssistantBikaroo;

/// <summary>
/// Une interaction métier complète, corrélée par un trace_id unique.
///
/// Contient les spans (opérations mesurées), les événements (application et
/// sécurité), les transitions du workflow et les métriques dérivées.
/// </summary>
public class TraceContext
{
    public string TraceId { get; init; } = "";
    public string StartedAt { get; init; } = "";
    public string UserRequestSummary { get; init; } = "";
    public string EndedAt { get; set; } = "";
    public long DurationMs { get; set; }
    public string Status { get; set; } = TraceStatus.Running;
    public string FinalOutcome { get; set; } = "";
    public string Error { get; set; } = "";

    public List<TraceSpan> Spans { get; } = new();
    public List<TraceEvent> Events { get; } = new();
    public List<TraceEvent> SecurityEvents { get; } = new();
    public List<WorkflowTransition> WorkflowTransitions { get; } = new();

    [JsonIgnore] public Stopwatch Clock { get; } = Stopwatch.StartNew();

    public TraceMetrics Metrics() => TraceMetrics.From(this);

    /// <summary>Export JSON — même structure que côté Python, en UTF-8 lisible.</summary>
    public string ToJson()
    {
        var payload = new Dictionary<string, object?>
        {
            ["trace_id"] = TraceId,
            ["started_at"] = StartedAt,
            ["ended_at"] = EndedAt,
            ["duration_ms"] = DurationMs,
            ["status"] = Status,
            ["final_outcome"] = FinalOutcome,
            ["user_request_summary"] = UserRequestSummary,
            ["error"] = Error,
            ["metrics"] = Metrics(),
            ["spans"] = Spans.Select(s => new Dictionary<string, object?>
            {
                ["span_id"] = s.SpanId, ["name"] = s.Name, ["category"] = s.Category,
                ["started_at"] = s.StartedAt, ["offset_ms"] = s.OffsetMs,
                ["ended_at"] = s.EndedAt, ["duration_ms"] = s.DurationMs,
                ["status"] = s.Status, ["attributes"] = s.Attributes, ["error"] = s.Error,
            }),
            ["events"] = Events.Select(EventToDict),
            ["security_events"] = SecurityEvents.Select(EventToDict),
            ["workflow_transitions"] = WorkflowTransitions.Select(t => new Dictionary<string, object?>
            {
                ["timestamp"] = t.Timestamp, ["step_before"] = t.StepBefore,
                ["step_after"] = t.StepAfter, ["reason"] = t.Reason, ["status"] = t.Status,
            }),
        };
        return JsonSerializer.Serialize(payload, new JsonSerializerOptions
        {
            WriteIndented = true,
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        });
    }

    private static Dictionary<string, object?> EventToDict(TraceEvent e) => new()
    {
        ["timestamp"] = e.Timestamp, ["event_type"] = e.EventType, ["source"] = e.Source,
        ["severity"] = e.Severity, ["details"] = e.Details, ["attributes"] = e.Attributes,
    };
}
