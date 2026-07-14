using Microsoft.Data.Sqlite;
using OllamaSharp;
using OllamaSharp.Models;

namespace AssistantBikaroo;

/// <summary>Un chunk du corpus, avec son score de similarité pour une question donnée.</summary>
public record Chunk(string Document, string Heading, string Content, double Score);

/// <summary>
/// Chaîne RAG de l'Assistant Bikaroo (squelette de départ). La plomberie est en
/// place : accès au corpus, chemin de la base SQLite, et EmbedAsync() déjà câblé
/// sur Ollama. À vous d'implémenter le cœur du RAG en suivant les « TODO » :
/// découpage en chunks, indexation SQLite, recherche cosinus et contexte.
/// </summary>
public class RagService
{
    public const string EmbeddingModel = "bge-m3";

    private readonly OllamaApiClient _ollama;
    private readonly string _corpusDir;
    private readonly string _dbPath;

    public int IndexSize { get; private set; }

    public RagService(OllamaApiClient ollama, string contentRootPath)
    {
        _ollama = ollama;
        // Le corpus est partagé : .../labo-02-rag/ressources/, trois niveaux
        // au-dessus du dossier du projet (.../dotnet/depart/AssistantBikaroo/).
        _corpusDir = Path.GetFullPath(Path.Combine(contentRootPath, "..", "..", "..", "ressources"));
        // L'index SQLite sera mis en cache à côté de l'application.
        _dbPath = Path.Combine(contentRootPath, "bikaroo_rag.db");
    }

    // --- 1. Découpage du corpus en chunks ------------------------------------

    // TODO (étape 1) — Charger les documents 01→06 du corpus et les découper en
    // chunks. Piste :
    //   * Directory.GetFiles(_corpusDir, "0*.md") (ne sélectionne que 01→06) ;
    //   * retirer l'éventuel bloc de métadonnées YAML en tête (lignes « --- ») ;
    //   * découper le corps sur les titres de section « ## » ;
    //   * renvoyer une liste de (document, heading, content).
    private List<(string Document, string Heading, string Content)> LoadChunks()
    {
        // TODO : à implémenter
        return new List<(string, string, string)>();
    }

    // --- 2. Embeddings (déjà câblé) ------------------------------------------

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

    // TODO (étape 3) — Construire l'index : appeler LoadChunks(), créer une table
    // SQLite « chunks » (document, heading, content, embedding), calculer
    // EmbedAsync(content) pour chaque chunk et l'insérer (embedding sérialisé en
    // JSON, par ex. System.Text.Json.JsonSerializer.Serialize). Renseigner IndexSize.
    public async Task<int> BuildIndexAsync()
    {
        // TODO : à implémenter
        await Task.CompletedTask;
        return 0;
    }

    // TODO (étape 3) — Ne (re)construire l'index que s'il est absent : tester la
    // présence et le contenu de la table « chunks », sinon appeler BuildIndexAsync().
    public async Task<int> EnsureIndexAsync()
    {
        // TODO : à implémenter (pour l'instant : aucun index construit)
        await Task.CompletedTask;
        return 0;
    }

    // --- 4. Recherche sémantique ---------------------------------------------

    // TODO (étape 4) — Rechercher les top_k chunks les plus proches :
    //   * calculer EmbedAsync(question) ;
    //   * charger tous les chunks + embeddings depuis SQLite ;
    //   * calculer la similarité cosinus pour chacun ;
    //   * trier par score décroissant et renvoyer les topK premiers.
    public async Task<List<Chunk>> SearchAsync(string question, int topK = 4)
    {
        // TODO : à implémenter
        await Task.CompletedTask;
        return new List<Chunk>();
    }

    // --- 5. Construction du contexte RAG -------------------------------------

    // TODO (étape 5) — Assembler les chunks retrouvés en un bloc de contexte
    // lisible, en indiquant la source de chaque extrait (document + section).
    public static string BuildContext(IEnumerable<Chunk> chunks)
    {
        // TODO : à implémenter
        return string.Empty;
    }
}
