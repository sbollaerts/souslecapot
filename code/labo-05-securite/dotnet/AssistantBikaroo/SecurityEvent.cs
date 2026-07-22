namespace AssistantBikaroo;

/// <summary>Types d'événements de sécurité journalisés par la politique.</summary>
public static class SecurityEventType
{
    public const string WriteAttemptWithoutConfirmation = "write_attempt_without_confirmation";
    public const string IdentityMismatch = "identity_mismatch";
    public const string PromptInjectionDetected = "prompt_injection_detected";
    public const string UnexpectedToolField = "unexpected_tool_field";
    public const string InvalidToolResult = "invalid_tool_result";
    public const string InvalidWriteParameters = "invalid_write_parameters";
    public const string UntrustedMemberOverride = "untrusted_member_override";
}

/// <summary>Une décision de sécurité, journalisée et affichée dans l'interface.</summary>
public sealed record SecurityEvent(
    string EventType,
    string Severity,   // info | warning | critical
    string Source,     // user_message | rag_document | tool_result | workflow
    string Details,
    string Action)     // REFUSED | DETECTED | IGNORED | ALLOWED
{
    public string Timestamp { get; } = DateTime.Now.ToString("HH:mm:ss");
}

/// <summary>Résultat de get_trip_status APRÈS validation (seuls les champs attendus).</summary>
public sealed record TripInfo(string TripId, string MemberId, string Status);
