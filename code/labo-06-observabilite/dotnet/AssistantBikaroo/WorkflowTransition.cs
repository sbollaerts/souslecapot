namespace AssistantBikaroo;

/// <summary>Une transition d'étape, enregistrée AU MOMENT où elle se produit.</summary>
public class WorkflowTransition
{
    public string Timestamp { get; init; } = "";
    public string TraceId { get; init; } = "";
    public string StepBefore { get; init; } = "";
    public string StepAfter { get; init; } = "";
    public string Reason { get; init; } = "";
    public string Status { get; init; } = "ok";
}
