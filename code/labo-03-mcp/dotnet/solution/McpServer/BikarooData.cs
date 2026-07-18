using System.Text.Json;

namespace McpServer;

/// <summary>
/// Charge en mémoire les données synthétiques (membres, trajets) depuis les
/// fichiers JSON du corpus, au démarrage. Pas de base de données pour ce labo.
/// </summary>
public class BikarooData
{
    private readonly List<JsonElement> _members;
    private readonly List<JsonElement> _trips;

    public BikarooData(string ressourcesDir)
    {
        _members = Load(Path.Combine(ressourcesDir, "members.json"));
        _trips = Load(Path.Combine(ressourcesDir, "trips.json"));
    }

    public int MemberCount => _members.Count;
    public int TripCount => _trips.Count;

    /// <summary>Renvoie le membre (JSON) ou une absence de résultat si inconnu.</summary>
    public string GetMember(string memberId) => Find(_members, "member_id", memberId)
        ?? NotFound($"Aucun membre avec l'identifiant {memberId}.");

    /// <summary>Renvoie le trajet (JSON) ou une absence de résultat si inconnu.</summary>
    public string GetTripStatus(string tripId) => Find(_trips, "trip_id", tripId)
        ?? NotFound($"Aucun trajet avec l'identifiant {tripId}.");

    private static List<JsonElement> Load(string path) =>
        JsonSerializer.Deserialize<List<JsonElement>>(File.ReadAllText(path))!;

    private static string? Find(List<JsonElement> items, string key, string value)
    {
        foreach (var item in items)
        {
            if (item.TryGetProperty(key, out var prop) && prop.GetString() == value)
            {
                return item.GetRawText();
            }
        }
        return null;
    }

    private static string NotFound(string message) =>
        JsonSerializer.Serialize(new { found = false, message });
}
