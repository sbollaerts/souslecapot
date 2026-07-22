using McpServer;

var builder = WebApplication.CreateBuilder(args);

// Données synthétiques : ressources du labo, deux niveaux au-dessus du projet.
// Le projet est dans .../dotnet/McpServer/ ; les données dans
// .../labo-04-orchestration/ressources/.
var ressourcesDir = Path.GetFullPath(
    Path.Combine(builder.Environment.ContentRootPath, "..", "..", "ressources"));
builder.Services.AddSingleton(new BikarooData(ressourcesDir));

// Base des demandes de révision (à côté du serveur), réinitialisée au démarrage.
// Exclue de Git (*.db). Voir le README, section « Choix techniques ».
var revisionDbPath = Path.Combine(builder.Environment.ContentRootPath, "revision_requests.db");
builder.Services.AddSingleton(new RevisionStore(revisionDbPath));

// Serveur MCP avec transport Streamable HTTP (et non stdio) : ce choix évite le
// conflit entre le flux stdio (réservé au protocole) et les logs de débogage,
// et permet d'inspecter le serveur directement (curl) avant de le relier au modèle.
builder.Services
    .AddMcpServer()
    .WithHttpTransport()
    .WithTools<BikarooTools>();

var app = builder.Build();

// Endpoint MCP exposé sur http://localhost:8000/mcp (même URL que côté Python).
app.MapMcp("/mcp");

var data = app.Services.GetRequiredService<BikarooData>();
Console.WriteLine($"Serveur MCP Bikaroo — {data.MemberCount} membres, {data.TripCount} trajets ; "
    + "base des demandes réinitialisée.");
Console.WriteLine("Écoute sur http://localhost:8000/mcp (Streamable HTTP)");

app.Run("http://localhost:8000");
