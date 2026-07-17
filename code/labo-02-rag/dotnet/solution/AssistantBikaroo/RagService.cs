using System.Text.Json;
using Microsoft.Data.Sqlite;
using OllamaSharp;
using OllamaSharp.Models;

namespace AssistantBikaroo;

/// <summary>Un chunk du corpus, avec son score de similarité pour une question donnée.</summary>
public record Chunk(string Document, string Heading, string Content, double Score);

/// <summary>
/// Chaîne RAG minimale : découpe le corpus en chunks, calcule un embedding par
/// chunk (bge-m3), stocke le tout dans SQLite, et effectue une recherche par
/// similarité cosinus en mémoire. Volontairement simple : la recherche parcourt
/// tous les chunks, ce qui suffit au corpus du labo mais ne passe pas à l'échelle.
/// </summary>
public class RagService
{
    public const string EmbeddingModel = "bge-m3";

    private readonly OllamaApiClient _ollama;
    private readonly string _corpusDir;
    private readonly string _dbPath;

    public int IndexSize { get; private set; }

    /// <param name="corpusDir">Dossier contenant les documents Markdown du corpus.</param>
    /// <param name="dbPath">Fichier SQLite où mettre en cache l'index vectoriel.</param>
    public RagService(OllamaApiClient ollama, string corpusDir, string dbPath)
    {
        // Les emplacements sont décidés par l'application (voir Program.cs) :
        // le service RAG ne fait que les recevoir.
        _ollama = ollama;
        _corpusDir = corpusDir;
        _dbPath = dbPath;
    }

    // --- 1. Découpage du corpus en chunks ------------------------------------

    private List<(string Document, string Heading, string Content)> LoadChunks()
    {
        var chunks = new List<(string, string, string)>();
        // Le motif « 0*.md » ne sélectionne que les documents 01→06 du corpus.
        foreach (var path in Directory.GetFiles(_corpusDir, "0*.md").OrderBy(p => p))
        {
            var body = StripFrontmatter(File.ReadAllText(path));
            var (title, sections) = SplitSections(body);
            foreach (var (heading, content) in sections)
            {
                // On préfixe chaque chunk du titre du document et de la section :
                // cela ancre l'extrait dans son contexte et améliore le retrieval.
                var chunkText = $"{title} — {heading}\n\n{content}";
                chunks.Add((Path.GetFileName(path), heading, chunkText));
            }
        }
        return chunks;
    }

    private static string StripFrontmatter(string text)
    {
        if (text.StartsWith("---"))
        {
            var end = text.IndexOf("\n---", 3, StringComparison.Ordinal);
            if (end != -1)
            {
                return text[(end + 4)..];
            }
        }
        return text;
    }

    private static (string Title, List<(string Heading, string Content)> Sections) SplitSections(string body)
    {
        var title = "";
        var sections = new List<(string, string)>();
        var currentHeading = "Introduction";
        var currentLines = new List<string>();

        void Flush()
        {
            if (currentLines.Any(l => l.Trim().Length > 0))
            {
                sections.Add((currentHeading, string.Join("\n", currentLines).Trim()));
            }
        }

        foreach (var line in body.Split('\n'))
        {
            if (line.StartsWith("## "))
            {
                Flush();
                currentHeading = line[3..].Trim();
                currentLines = new List<string>();
            }
            else if (line.StartsWith("# "))
            {
                title = line[2..].Trim(); // titre H1 du document
            }
            else
            {
                currentLines.Add(line);
            }
        }
        Flush();

        return (title, sections);
    }

    // --- 2. Embeddings -------------------------------------------------------

    public async Task<float[]> EmbedAsync(string text)
    {
        var response = await _ollama.EmbedAsync(new EmbedRequest
        {
            Model = EmbeddingModel,
            Input = new List<string> { text },
        });
        return response.Embeddings[0];
    }

    // --- 3. Indexation SQLite ------------------------------------------------

    public async Task<int> BuildIndexAsync()
    {
        var chunks = LoadChunks();

        using var connection = new SqliteConnection($"Data Source={_dbPath}");
        connection.Open();
        Execute(connection, "DROP TABLE IF EXISTS chunks");
        Execute(connection,
            "CREATE TABLE chunks (id INTEGER PRIMARY KEY, document TEXT, heading TEXT, content TEXT, embedding TEXT)");

        foreach (var (document, heading, content) in chunks)
        {
            var embedding = await EmbedAsync(content);
            using var command = connection.CreateCommand();
            command.CommandText =
                "INSERT INTO chunks (document, heading, content, embedding) VALUES ($d, $h, $c, $e)";
            command.Parameters.AddWithValue("$d", document);
            command.Parameters.AddWithValue("$h", heading);
            command.Parameters.AddWithValue("$c", content);
            command.Parameters.AddWithValue("$e", JsonSerializer.Serialize(embedding)); // embedding en JSON
            command.ExecuteNonQuery();
        }

        IndexSize = chunks.Count;
        return chunks.Count;
    }

    /// <summary>
    /// Construit l'index seulement s'il est absent (mise en cache sur disque).
    /// Supprimer le fichier .db force une reconstruction au prochain démarrage.
    /// </summary>
    public async Task<int> EnsureIndexAsync()
    {
        long count = 0;
        using (var connection = new SqliteConnection($"Data Source={_dbPath}"))
        {
            connection.Open();
            using var command = connection.CreateCommand();
            command.CommandText =
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='chunks'";
            var hasTable = (long)command.ExecuteScalar()! > 0;
            if (hasTable)
            {
                command.CommandText = "SELECT COUNT(*) FROM chunks";
                count = (long)command.ExecuteScalar()!;
            }
        }

        if (count > 0)
        {
            IndexSize = (int)count;
            return IndexSize;
        }

        return await BuildIndexAsync();
    }

    // --- 4. Recherche sémantique ---------------------------------------------

    public async Task<List<Chunk>> SearchAsync(string question, int topK = 4)
    {
        var questionEmbedding = await EmbedAsync(question);
        var scored = new List<Chunk>();

        using var connection = new SqliteConnection($"Data Source={_dbPath}");
        connection.Open();
        using var command = connection.CreateCommand();
        command.CommandText = "SELECT document, heading, content, embedding FROM chunks";
        using var reader = command.ExecuteReader();
        while (reader.Read())
        {
            var embedding = JsonSerializer.Deserialize<float[]>(reader.GetString(3))!;
            var score = CosineSimilarity(questionEmbedding, embedding);
            scored.Add(new Chunk(reader.GetString(0), reader.GetString(1), reader.GetString(2), score));
        }

        return scored.OrderByDescending(c => c.Score).Take(topK).ToList();
    }

    private static double CosineSimilarity(float[] a, float[] b)
    {
        double dot = 0, normA = 0, normB = 0;
        for (var i = 0; i < a.Length; i++)
        {
            dot += a[i] * b[i];
            normA += a[i] * a[i];
            normB += b[i] * b[i];
        }
        if (normA == 0 || normB == 0)
        {
            return 0;
        }
        return dot / (Math.Sqrt(normA) * Math.Sqrt(normB));
    }

    // --- 5. Construction du contexte RAG -------------------------------------

    public static string BuildContext(IEnumerable<Chunk> chunks)
    {
        return string.Join("\n\n",
            chunks.Select(c => $"[Source : {c.Document} — {c.Heading}]\n{c.Content}"));
    }

    private static void Execute(SqliteConnection connection, string sql)
    {
        using var command = connection.CreateCommand();
        command.CommandText = sql;
        command.ExecuteNonQuery();
    }
}
