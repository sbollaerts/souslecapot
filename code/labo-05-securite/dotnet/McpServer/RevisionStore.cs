using System.Text.Json;
using Microsoft.Data.Sqlite;

namespace McpServer;

/// <summary>
/// Stocke les demandes de révision dans une base SQLite (même principe que le RAG
/// au labo 2 : SQLite pour rester simple, sans service supplémentaire). La base
/// est réinitialisée au démarrage du serveur.
/// </summary>
public class RevisionStore
{
    private readonly string _dbPath;
    private readonly Random _random = new();

    public RevisionStore(string dbPath)
    {
        _dbPath = dbPath;
        using var connection = Open();
        Execute(connection, "DROP TABLE IF EXISTS revision_requests");
        Execute(connection,
            "CREATE TABLE revision_requests ("
            + "id TEXT PRIMARY KEY, member_id TEXT, trip_id TEXT, description TEXT, "
            + "informations_complementaires TEXT, status TEXT, created_at TEXT)");
    }

    /// <summary>Crée une demande et renvoie son résultat en JSON (id, statut, date).</summary>
    public string Create(string memberId, string tripId, string description, string infos)
    {
        var id = $"REV-{_random.Next(10000, 99999)}";
        var createdAt = DateTime.Now.ToString("s");

        using var connection = Open();
        using var command = connection.CreateCommand();
        command.CommandText =
            "INSERT INTO revision_requests VALUES ($id, $m, $t, $d, $i, $s, $c)";
        command.Parameters.AddWithValue("$id", id);
        command.Parameters.AddWithValue("$m", memberId);
        command.Parameters.AddWithValue("$t", tripId);
        command.Parameters.AddWithValue("$d", description);
        command.Parameters.AddWithValue("$i", infos);
        command.Parameters.AddWithValue("$s", "pending");
        command.Parameters.AddWithValue("$c", createdAt);
        command.ExecuteNonQuery();

        return JsonSerializer.Serialize(new
        {
            request_id = id,
            status = "pending",
            created_at = createdAt,
        });
    }

    private SqliteConnection Open()
    {
        var connection = new SqliteConnection($"Data Source={_dbPath}");
        connection.Open();
        return connection;
    }

    private static void Execute(SqliteConnection connection, string sql)
    {
        using var command = connection.CreateCommand();
        command.CommandText = sql;
        command.ExecuteNonQuery();
    }
}
