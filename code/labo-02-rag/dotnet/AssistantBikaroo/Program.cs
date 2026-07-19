using AssistantBikaroo;
using AssistantBikaroo.Components;
using OllamaSharp;

var builder = WebApplication.CreateBuilder(args);

// Composants Blazor rendus côté serveur (Blazor Server).
builder.Services.AddRazorComponents()
    .AddInteractiveServerComponents();

// Client Ollama partagé (génération + embeddings), pointant vers l'instance locale.
builder.Services.AddSingleton(new OllamaApiClient(new Uri("http://localhost:11434")));

// Emplacements : c'est l'application qui décide où lire le corpus et où écrire
// l'index ; le service RAG les reçoit en paramètre.
// Le projet est dans .../dotnet/AssistantBikaroo/ ; le corpus est partagé, deux
// niveaux au-dessus, dans .../labo-02-rag/ressources/.
var contentRoot = builder.Environment.ContentRootPath;
var corpusDir = Path.GetFullPath(Path.Combine(contentRoot, "..", "..", "ressources"));
var dbPath = Path.Combine(contentRoot, "bikaroo_rag.db");

// Service RAG : chunking, embeddings, index SQLite et recherche sémantique.
builder.Services.AddSingleton(sp =>
    new RagService(sp.GetRequiredService<OllamaApiClient>(), corpusDir, dbPath));

var app = builder.Build();

app.UseAntiforgery();

app.MapRazorComponents<App>()
    .AddInteractiveServerRenderMode();

// Indexation du corpus au démarrage (seulement si l'index n'existe pas encore).
// En cas d'échec (Ollama non lancé, modèle bge-m3 absent), l'application démarre
// quand même : l'erreur sera visible lors de la première question en mode RAG.
try
{
    var size = await app.Services.GetRequiredService<RagService>().EnsureIndexAsync();
    Console.WriteLine($"[RAG] Corpus indexé : {size} chunks.");
}
catch (Exception ex)
{
    Console.WriteLine($"[RAG] Indexation impossible au démarrage : {ex.Message}");
}

app.Run();
