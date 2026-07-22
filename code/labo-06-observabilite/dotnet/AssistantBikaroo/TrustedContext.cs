namespace AssistantBikaroo;

/// <summary>
/// Contexte de confiance : la SOURCE DE VÉRITÉ de la session (qui est
/// l'utilisateur authentifié, et ce qu'il a le droit de faire).
///
/// Règle fondamentale du labo : ce contexte est établi par l'application (ici une
/// authentification simulée) et ne peut JAMAIS être modifié par une donnée non
/// fiable — ni message utilisateur, ni document RAG, ni résultat de tool.
/// </summary>
public sealed record TrustedContext(
    string AuthenticatedMemberId,
    IReadOnlyList<string> AllowedActions,
    string SessionId)
{
    public const string ReadTrip = "read_trip";
    public const string CreateRevision = "create_revision";

    public bool IsAllowed(string action) => AllowedActions.Contains(action);

    /// <summary>Crée le contexte de la session (authentification simulée).</summary>
    public static TrustedContext New(string authenticatedMemberId = "MBR-1042") =>
        new(authenticatedMemberId,
            new[] { ReadTrip, CreateRevision },
            Guid.NewGuid().ToString("N")[..12]);
}
