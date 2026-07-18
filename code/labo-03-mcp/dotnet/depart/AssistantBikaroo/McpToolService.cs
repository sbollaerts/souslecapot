using System.Text.Json;
using ModelContextProtocol.Client;
using OllamaSharp;
using OllamaSharp.Models;
using OllamaSharp.Models.Chat;

namespace AssistantBikaroo;

/// <summary>Trace d'un appel de tool, pour l'affichage dans l'UI.</summary>
public record ToolCallLog(string Name, string Arguments, string Result);

/// <summary>Résultat d'un échange : réponse finale, appels de tools, disponibilité MCP.</summary>
public record ToolAnswer(string Text, List<ToolCallLog> ToolCalls, bool McpAvailable);

/// <summary>
/// Relie le modèle (via OllamaSharp) au serveur MCP. Squelette de départ : la
/// connexion (ListToolNamesAsync) et les aides (conversion de schéma, appel au
/// modèle) sont fournies. À vous d'écrire la boucle d'appel de tools dans
/// AnswerAsync (voir les « TODO »).
/// </summary>
public class McpToolService
{
    // Garde-fou contre les boucles d'appels de tools.
    private const int MaxToolRounds = 5;

    private readonly OllamaApiClient _ollama;
    private readonly string _mcpUrl;
    private readonly string _model;

    public McpToolService(OllamaApiClient ollama, string mcpUrl, string model)
    {
        _ollama = ollama;
        _mcpUrl = mcpUrl;
        _model = model;
    }

    /// <summary>Nom du modèle de génération (pour l'affichage).</summary>
    public string Model => _model;

    private IClientTransport CreateTransport() => new HttpClientTransport(
        new HttpClientTransportOptions
        {
            Endpoint = new Uri(_mcpUrl),
            TransportMode = HttpTransportMode.StreamableHttp,
            Name = "assistant-bikaroo",
        });

    /// <summary>Noms des tools exposés (connexion déjà câblée).</summary>
    public async Task<List<string>> ListToolNamesAsync()
    {
        await using var client = await McpClient.CreateAsync(CreateTransport());
        var tools = await client.ListToolsAsync();
        return tools.Select(t => t.Name).ToList();
    }

    /// <summary>
    /// Répond à la conversation en donnant au modèle l'accès aux tools MCP.
    ///
    /// TODO (étape 4) — Implémenter la boucle d'appel de tools :
    ///   * ouvrir une connexion MCP (McpClient.CreateAsync(CreateTransport())) et
    ///     récupérer les tools (ListToolsAsync), convertis avec ToOllamaTool ;
    ///   * appeler le modèle (ChatMessageAsync) en lui passant ces tools ;
    ///   * tant qu'il renvoie des ToolCalls (dans la limite de MaxToolRounds) :
    ///     exécuter chaque appel via client.CallToolAsync(name, arguments),
    ///     journaliser un ToolCallLog, et réinjecter le résultat dans la
    ///     conversation avec le rôle ChatRole.Tool ;
    ///   * dès qu'il n'y a plus d'appel, renvoyer sa réponse + le journal ;
    ///   * en cas d'échec de connexion, se replier sur une génération sans tools
    ///     (ToolAnswer avec McpAvailable=false).
    ///
    /// En attendant, on répond SANS tools (le chat et le RAG fonctionnent déjà).
    /// </summary>
    public async Task<ToolAnswer> AnswerAsync(List<Message> messages, RequestOptions options)
    {
        var text = await ChatAsync(messages, tools: null, options);
        return new ToolAnswer(text, new List<ToolCallLog>(), McpAvailable: false);
    }

    // --- Aides fournies ------------------------------------------------------

    // Appelle le modèle et renvoie le message complet (avec d'éventuels ToolCalls).
    private async Task<Message> ChatMessageAsync(List<Message> messages, List<Tool>? tools, RequestOptions options)
    {
        var request = new ChatRequest
        {
            Model = _model,
            Stream = false,
            Messages = messages,
            Tools = tools,
            Options = options,
        };
        Message? message = null;
        await foreach (var chunk in _ollama.ChatAsync(request))
        {
            message = chunk?.Message;
        }
        return message ?? new Message { Role = ChatRole.Assistant, Content = string.Empty };
    }

    private async Task<string> ChatAsync(List<Message> messages, List<Tool>? tools, RequestOptions options)
        => (await ChatMessageAsync(messages, tools, options)).Content ?? string.Empty;

    // Convertit un tool MCP (schéma JSON) en Tool OllamaSharp.
    private static Tool ToOllamaTool(McpClientTool tool)
    {
        var properties = new Dictionary<string, Property>();
        var required = new List<string>();
        var schema = tool.JsonSchema;

        if (schema.TryGetProperty("properties", out var props))
        {
            foreach (var prop in props.EnumerateObject())
            {
                var type = prop.Value.TryGetProperty("type", out var t) ? t.GetString() : "string";
                var description = prop.Value.TryGetProperty("description", out var d) ? d.GetString() : null;
                properties[prop.Name] = new Property { Type = type, Description = description };
            }
        }
        if (schema.TryGetProperty("required", out var req))
        {
            required.AddRange(req.EnumerateArray().Select(item => item.GetString()!));
        }

        return new Tool
        {
            Type = "function",
            Function = new Function
            {
                Name = tool.Name,
                Description = tool.Description,
                Parameters = new Parameters { Type = "object", Properties = properties, Required = required },
            },
        };
    }
}
