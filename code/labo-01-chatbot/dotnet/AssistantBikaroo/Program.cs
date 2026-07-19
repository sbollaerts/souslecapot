using AssistantBikaroo.Components;
using OllamaSharp;

var builder = WebApplication.CreateBuilder(args);

// Composants Blazor rendus côté serveur (Blazor Server).
builder.Services.AddRazorComponents()
    .AddInteractiveServerComponents();

// Client Ollama partagé, pointant vers l'instance locale par défaut.
// Une seule instance suffit pour tout le labo (pas de configuration avancée).
builder.Services.AddSingleton(new OllamaApiClient(new Uri("http://localhost:11434")));

var app = builder.Build();

app.UseAntiforgery();

app.MapRazorComponents<App>()
    .AddInteractiveServerRenderMode();

app.Run();
