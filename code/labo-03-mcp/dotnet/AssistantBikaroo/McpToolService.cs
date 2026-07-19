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
/// Relie le modèle (via OllamaSharp) au serveur MCP :
///   1. se connecte au serveur et récupère la liste des tools ;
///   2. les transmet au modèle, qui décide seul d'en appeler ;
///   3. exécute l'appel demandé, réinjecte le résultat, puis laisse le modèle
///      formuler sa réponse finale.
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

    /// <summary>Noms des tools exposés (vérification de disponibilité au démarrage).</summary>
    public async Task<List<string>> ListToolNamesAsync()
    {
        await using var client = await McpClient.CreateAsync(CreateTransport());
        var tools = await client.ListToolsAsync();
        return tools.Select(t => t.Name).ToList();
    }

    /// <summary>
    /// Répond à la conversation en donnant au modèle l'accès aux tools MCP. En cas
    /// d'échec de connexion, se replie sur une génération sans tools (McpAvailable=false).
    /// </summary>
    public async Task<ToolAnswer> AnswerAsync(List<Message> messages, RequestOptions options)
    {
        try
        {
            return await AnswerWithToolsAsync(messages, options);
        }
        catch
        {
            // Serveur MCP injoignable : repli sans tools (le chat et le RAG marchent).
            var text = await ChatAsync(messages, tools: null, options);
            return new ToolAnswer(text, new List<ToolCallLog>(), McpAvailable: false);
        }
    }

    private async Task<ToolAnswer> AnswerWithToolsAsync(List<Message> messages, RequestOptions options)
    {
        await using var client = await McpClient.CreateAsync(CreateTransport());
        var tools = (await client.ListToolsAsync()).Select(ToOllamaTool).ToList();

        var conversation = new List<Message>(messages);
        var toolLog = new List<ToolCallLog>();

        for (var round = 0; round < MaxToolRounds; round++)
        {
            var assistant = await ChatMessageAsync(conversation, tools, options);
            conversation.Add(assistant);

            var calls = assistant.ToolCalls?.ToList();
            if (calls is null || calls.Count == 0)
            {
                // Plus d'appel de tool : c'est la réponse finale.
                return new ToolAnswer(assistant.Content ?? string.Empty, toolLog, McpAvailable: true);
            }

            foreach (var call in calls)
            {
                var name = call.Function!.Name!;
                var arguments = call.Function.Arguments!
                    .ToDictionary(kv => kv.Key, kv => (object?)kv.Value?.ToString());
                var result = await client.CallToolAsync(name, arguments);
                var text = (result.Content.FirstOrDefault()
                    as ModelContextProtocol.Protocol.TextContentBlock)?.Text ?? string.Empty;

                toolLog.Add(new ToolCallLog(name, JsonSerializer.Serialize(arguments), text));
                // On réinjecte le résultat du tool dans la conversation.
                conversation.Add(new Message { Role = ChatRole.Tool, Content = text });
            }
        }

        // Garde-fou atteint : réponse finale sans nouveaux tools.
        var final = await ChatAsync(conversation, tools: null, options);
        return new ToolAnswer(final, toolLog, McpAvailable: true);
    }

    // --- Appels au modèle ----------------------------------------------------

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

    // --- Conversion du schéma MCP vers un Tool OllamaSharp -------------------

    private static Tool ToOllamaTool(McpClientTool tool)
    {
        var properties = new Dictionary<string, Property>();
        var required = new List<string>();
        var schema = tool.JsonSchema; // schéma JSON fourni par le serveur MCP

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
