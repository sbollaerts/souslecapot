using System.Text.Json;

namespace McpServer;

/// <summary>
/// Charge en mémoire les données synthétiques (membres, trajets) depuis les
/// fichiers JSON du corpus, au démarrage. Le chargement est déjà en place ;
/// à vous d'implémenter la recherche (voir les « TODO »).
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
    public string GetMember(string memberId)
    {
        // TODO (étape 2) — Renvoyer, en JSON, le membre dont "member_id" vaut
        // memberId (l'aide Find ci-dessous le fait), sinon NotFound(...).
        return NotFound("get_member n'est pas encore implémenté.");
    }

    /// <summary>Renvoie le trajet (JSON) ou une absence de résultat si inconnu.</summary>
    public string GetTripStatus(string tripId)
    {
        // TODO (étape 2) — Renvoyer, en JSON, le trajet dont "trip_id" vaut
        // tripId, sinon NotFound(...).
        return NotFound("get_trip_status n'est pas encore implémenté.");
    }

    private static List<JsonElement> Load(string path) =>
        JsonSerializer.Deserialize<List<JsonElement>>(File.ReadAllText(path))!;

    // Aide fournie : recherche d'un élément par clé/valeur, renvoyé en JSON brut.
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
