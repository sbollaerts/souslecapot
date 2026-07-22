using System.Diagnostics;

namespace AssistantBikaroo;

/// <summary>
/// Observabilité locale — Labo 6.
///
/// Crée les traces, ouvre et ferme les spans, journalise les événements et les
/// transitions. Aucune infrastructure externe (ni OpenTelemetry, ni Jaeger…) :
/// tout reste en mémoire de session.
///
/// Confidentialité : on n'enregistre pas les prompts complets ni les embeddings,
/// seulement des résumés, des tailles et des scores.
/// </summary>
public class ObservabilityService
{
    public const int MaxTraces = 20;

    private readonly LinkedList<TraceContext> _traces = new();

    public IEnumerable<TraceContext> Traces => _traces;
    public TraceContext? Current { get; private set; }

    /// <summary>Latences simulées par catégorie, en ms (contrôle pédagogique).</summary>
    public Dictionary<string, int> Latency { get; } = new()
    {
        [SpanCategory.Llm] = 0, [SpanCategory.Rag] = 0, [SpanCategory.Mcp] = 0,
    };

    // --- Cycle de vie d'une trace --------------------------------------------

    public TraceContext StartTrace(string userRequestSummary)
    {
        var trace = new TraceContext
        {
            TraceId = "trc-" + Guid.NewGuid().ToString("N")[..8],
            StartedAt = DateTime.Now.ToString("o"),
            UserRequestSummary = (userRequestSummary ?? "").Length > 160
                ? userRequestSummary![..160] : userRequestSummary ?? "",
        };
        _traces.AddLast(trace);
        while (_traces.Count > MaxTraces)
        {
            _traces.RemoveFirst();
        }
        Current = trace;
        return trace;
    }

    public TraceContext? FinishTrace(string status, string finalOutcome = "")
    {
        var trace = Current;
        if (trace is null)
        {
            return null;
        }
        trace.EndedAt = DateTime.Now.ToString("o");
        trace.DurationMs = trace.Clock.ElapsedMilliseconds;
        trace.Status = status;
        if (finalOutcome.Length > 0)
        {
            trace.FinalOutcome = finalOutcome;
        }
        return trace;
    }

    // --- Spans -----------------------------------------------------------------

    /// <summary>
    /// Ouvre un span. À utiliser avec « using » : le span est fermé quoi qu'il
    /// arrive. En cas d'erreur, appeler scope.Fail(ex) avant de sortir.
    /// </summary>
    public SpanScope StartSpan(string name, string category,
        params (string Key, object? Value)[] attributes)
    {
        var trace = Current;
        if (trace is null)
        {
            return new SpanScope(null, null, 0);
        }

        var span = new TraceSpan
        {
            SpanId = "spn-" + Guid.NewGuid().ToString("N")[..6],
            TraceId = trace.TraceId,
            Name = name,
            Category = category,
            StartedAt = DateTime.Now.ToString("o"),
            OffsetMs = trace.Clock.ElapsedMilliseconds,
        };
        foreach (var (key, value) in attributes)
        {
            span.Attributes[key] = value;
        }
        trace.Spans.Add(span);

        var delay = Latency.TryGetValue(category, out var ms) ? ms : 0;
        if (delay > 0)
        {
            Thread.Sleep(delay);
            span.Attributes["simulated_latency_ms"] = delay;
        }
        return new SpanScope(span, this, delay);
    }

    // --- Événements et transitions ---------------------------------------------

    public void RecordEvent(string eventType, string source, string severity, string details,
        Dictionary<string, object?>? attributes = null)
    {
        if (Current is null) { return; }
        Current.Events.Add(new TraceEvent
        {
            Timestamp = DateTime.Now.ToString("HH:mm:ss.fff"),
            TraceId = Current.TraceId, EventType = eventType, Source = source,
            Severity = severity, Details = details,
            Attributes = attributes ?? new Dictionary<string, object?>(),
        });
    }

    /// <summary>Rattache un SecurityEvent (labo 5) à la trace courante.</summary>
    public void RecordSecurityEvent(SecurityEvent securityEvent)
    {
        if (Current is null) { return; }
        Current.SecurityEvents.Add(new TraceEvent
        {
            Timestamp = securityEvent.Timestamp, TraceId = Current.TraceId,
            EventType = securityEvent.EventType, Source = securityEvent.Source,
            Severity = securityEvent.Severity, Details = securityEvent.Details,
            Attributes = new Dictionary<string, object?> { ["action"] = securityEvent.Action },
        });
    }

    public void RecordTransition(string stepBefore, string stepAfter, string reason, string status = "ok")
    {
        if (Current is null) { return; }
        Current.WorkflowTransitions.Add(new WorkflowTransition
        {
            Timestamp = DateTime.Now.ToString("HH:mm:ss.fff"), TraceId = Current.TraceId,
            StepBefore = stepBefore, StepAfter = stepAfter, Reason = reason, Status = status,
        });
    }

    public void RecordError(string eventType, string source, string details)
    {
        RecordEvent(eventType, source, "critical", details);
        if (Current is not null)
        {
            Current.Error = details.Length > 300 ? details[..300] : details;
        }
    }

    // --- Export -----------------------------------------------------------------

    public string ExportJson(TraceContext trace)
    {
        var payload = trace.ToJson();
        RecordEvent(AppEventType.TraceExported, "application", "info",
            $"Trace {trace.TraceId} exportée ({payload.Length} caractères).");
        return payload;
    }
}

/// <summary>Portée d'un span : ferme et mesure automatiquement à la sortie.</summary>
public sealed class SpanScope : IDisposable
{
    private readonly Stopwatch _stopwatch = Stopwatch.StartNew();
    private readonly int _simulatedLatencyMs;

    public TraceSpan? Span { get; }

    internal SpanScope(TraceSpan? span, ObservabilityService? _, int simulatedLatencyMs)
    {
        Span = span;
        _simulatedLatencyMs = simulatedLatencyMs;
    }

    public SpanScope Set(string key, object? value)
    {
        Span?.Set(key, value);
        return this;
    }

    /// <summary>Marque le span en échec (erreur technique ou validation refusée).</summary>
    public void Fail(string error)
    {
        if (Span is null) { return; }
        Span.Status = TraceStatus.Failed;
        Span.Error = error.Length > 300 ? error[..300] : error;
    }

    public void Fail(Exception exception) => Fail($"{exception.GetType().Name}: {exception.Message}");

    public void Dispose()
    {
        if (Span is null) { return; }
        Span.EndedAt = DateTime.Now.ToString("o");
        // La latence simulée est déjà incluse dans le temps écoulé.
        Span.DurationMs = _stopwatch.ElapsedMilliseconds + _simulatedLatencyMs;
        if (Span.Status == TraceStatus.Running)
        {
            Span.Status = TraceStatus.Success;
        }
    }
}
