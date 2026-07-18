using AssistantBikaroo;
using AssistantBikaroo.Components;
using OllamaSharp;

var builder = WebApplication.CreateBuilder(args);

// Composants Blazor rendus côté serveur (Blazor Server).
builder.Services.AddRazorComponents()
    .AddInteractiveServerComponents();

// Client Ollama partagé (génération + embeddings), pointant vers l'instance locale.
builder.Services.AddSingleton(new OllamaApiClient(new Uri("http://localhost:11434")));

// Modèle de génération. Ce labo demande un appel de tools fiable : on utilise
// qwen2.5:3b, léger (~2 Go) et le plus régulier de notre comparatif pour décider
// d'appeler un tool. Sur une machine plus confortable, « qwen2.5:7b » est encore
// plus stable. (mistral, utilisé aux labos 1-2, n'appelle pas les tools de façon
// fiable en présence d'un contexte RAG — voir la section « Choix techniques ».)
const string generationModel = "qwen2.5:3b";

// URL du serveur MCP (à démarrer AVANT le client — voir le README).
const string mcpUrl = "http://localhost:8000/mcp";

// Emplacements : c'est l'application qui décide où lire le corpus et où écrire
// l'index ; le service RAG les reçoit en paramètre.
// Le projet est dans .../dotnet/solution/AssistantBikaroo/ ; le corpus est
// partagé, trois niveaux au-dessus, dans .../labo-03-mcp/ressources/.
var contentRoot = builder.Environment.ContentRootPath;
var corpusDir = Path.GetFullPath(Path.Combine(contentRoot, "..", "..", "..", "ressources"));
var dbPath = Path.Combine(contentRoot, "bikaroo_rag.db");

// Service RAG : chunking, embeddings, index SQLite et recherche sémantique.
builder.Services.AddSingleton(sp =>
    new RagService(sp.GetRequiredService<OllamaApiClient>(), corpusDir, dbPath));

// Service MCP : connexion au serveur, transmission des tools au modèle, boucle
// d'appel de tools et réinjection des résultats.
builder.Services.AddSingleton(sp =>
    new McpToolService(sp.GetRequiredService<OllamaApiClient>(), mcpUrl, generationModel));

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
