using System.Text.Json;
using System.Text.RegularExpressions;
using OllamaSharp;
using OllamaSharp.Models;
using OllamaSharp.Models.Chat;

namespace AssistantBikaroo;

/// <summary>État d'un processus de révision en cours (mutable, porté par la page).</summary>
public class RevisionProcess
{
    public bool Active { get; set; } = true;
    public int Step { get; set; } = 1;
    public string MemberId { get; set; } = "";
    public string? TripId { get; set; }
    public Dictionary<string, string> Collected { get; } = new();
    public int FieldIndex { get; set; }
    public int Attempts { get; set; }
    public string? Outcome { get; set; }              // created | cancelled | aborted | not_eligible
    public bool NeedConfirmation { get; set; }
    public ToolCallLog? LastToolCall { get; set; }    // appel à create_revision_request, pour l'UI
}

/// <summary>
/// Orchestration d'un processus métier en 5 étapes. Point clé : le contrôle des
/// étapes est DÉTERMINISTE (dans ce service). Le LLM ne décide jamais de changer
/// d'étape ni de déclencher l'écriture ; il contribue seulement à comprendre
/// l'utilisateur (intention, jugement des réponses) et à formuler les messages.
///
///   1. Identification  2. Diagnostic  3. Collecte  4. Confirmation  5. Création
/// </summary>
public partial class OrchestrationService
{
    // Informations à collecter (issues de 02-procedure-trajet-reste-ouvert.md).
    private static readonly (string Name, string Label)[] CollectFields =
    {
        ("heure_restitution", "l'heure approximative à laquelle le vélo a été restitué"),
        ("emplacement_restitution", "l'emplacement (station ou zone) où le vélo a été laissé"),
        ("description_probleme", "une description du problème et du message affiché dans l'application"),
    };
    private const int MaxAttempts = 3;

    public static readonly Dictionary<int, string> StepLabels = new()
    {
        [1] = "Identification du trajet",
        [2] = "Diagnostic",
        [3] = "Collecte des informations",
        [4] = "Confirmation",
        [5] = "Création de la demande",
    };

    [GeneratedRegex(@"TRP-\d+", RegexOptions.IgnoreCase)]
    private static partial Regex TripRegex();

    private readonly OllamaApiClient _ollama;
    private readonly McpToolService _mcp;
    private readonly RagService _rag;
    private readonly string _model;

    public OrchestrationService(OllamaApiClient ollama, McpToolService mcp, RagService rag, string model)
    {
        _ollama = ollama;
        _mcp = mcp;
        _rag = rag;
        _model = model;
    }

    public static RevisionProcess NewProcess(string memberId) => new() { MemberId = memberId };

    /// <summary>Extraction déterministe d'un identifiant de trajet (format TRP-XXXXX).</summary>
    public static string? FindTripId(string text)
    {
        var match = TripRegex().Match(text ?? "");
        return match.Success ? match.Value.ToUpperInvariant() : null;
    }

    // --- Contributions du LLM : comprendre et formuler (jamais décider) -------

    public async Task<bool> DetectRevisionIntentAsync(string text)
    {
        const string schema =
            """{"type":"object","properties":{"wants_revision":{"type":"boolean"}},"required":["wants_revision"]}""";
        const string system =
            "Tu analyses le message d'un membre Bikaroo. Renvoie wants_revision=true s'il "
            + "veut CONTESTER des frais ou DEMANDER une révision/correction pour un trajet ; "
            + "false pour une simple question d'information ou de procédure. JSON uniquement.";
        var json = await ChatJsonAsync(system, text, schema);
        return ReadBool(json, "wants_revision");
    }

    private async Task<(bool Answered, bool WantsToCancel)> JudgeAnswerAsync(string question, string reply)
    {
        const string schema =
            """{"type":"object","properties":{"answered":{"type":"boolean"},"wants_to_cancel":{"type":"boolean"}},"required":["answered","wants_to_cancel"]}""";
        var system =
            $"Un membre Bikaroo répond à cette question : « {question} ». Renvoie "
            + "answered=true si sa réponse fournit l'information demandée (même approximative), "
            + "false si absente, incompréhensible, hors sujet ou s'il dit ne pas savoir. Renvoie "
            + "wants_to_cancel=true UNIQUEMENT s'il exprime clairement vouloir arrêter la démarche "
            + "(pas une simple réponse hors sujet). JSON uniquement.";
        var json = await ChatJsonAsync(system, reply, schema);
        return (ReadBool(json, "answered"), ReadBool(json, "wants_to_cancel"));
    }

    private async Task<string> FormulateAsync(string instruction, string context = "", string fallback = "")
    {
        var messages = new List<Message>
        {
            new() { Role = ChatRole.System,
                    Content = "Tu es l'Assistant Bikaroo. Réponds en français, brièvement et poliment." },
        };
        if (context.Length > 0)
        {
            messages.Add(new Message { Role = ChatRole.System, Content = context });
        }
        messages.Add(new Message { Role = ChatRole.User, Content = instruction });

        var request = new ChatRequest
        {
            Model = _model, Stream = false, Messages = messages,
            Options = new RequestOptions { Temperature = 0.3f, NumPredict = 220 },
        };
        Message? message = null;
        await foreach (var chunk in _ollama.ChatAsync(request))
        {
            message = chunk?.Message;
        }
        var text = message?.Content?.Trim();
        return string.IsNullOrEmpty(text) ? fallback : text;
    }

    // --- Étape 1 : identification --------------------------------------------

    public async Task<string> AdvanceAfterStartAsync(RevisionProcess process)
    {
        if (process.TripId is not null)
        {
            return await DiagnoseAsync(process);
        }
        process.Step = 1;
        return "Je peux vous aider à contester un trajet. Quel est l'identifiant du "
             + "trajet concerné (format TRP-XXXXX) ?";
    }

    private async Task<string> Step1Async(RevisionProcess process, string userText)
    {
        var tripId = FindTripId(userText);
        if (tripId is null)
        {
            var (_, wantsCancel) = await JudgeAnswerAsync("l'identifiant du trajet à contester", userText);
            if (wantsCancel)
            {
                return Cancel(process);
            }
            return "Je n'ai pas repéré d'identifiant de trajet (format TRP-XXXXX). "
                 + "Pouvez-vous me le communiquer ?";
        }
        process.TripId = tripId;
        return await DiagnoseAsync(process);
    }

    // --- Étape 2 : diagnostic (règles déterministes d'éligibilité) ------------

    private async Task<string> DiagnoseAsync(RevisionProcess process)
    {
        process.Step = 2;
        var tripJson = await _mcp.CallToolAsync("get_trip_status", new() { ["trip_id"] = process.TripId });
        var (found, memberId, status) = ParseTrip(tripJson);

        if (!found)
        {
            return Finish(process, "not_eligible",
                $"Je ne trouve aucun trajet {process.TripId} dans le système. "
                + "Vérifiez l'identifiant ou contactez le service à la clientèle.");
        }
        if (memberId is not null && memberId != process.MemberId)
        {
            return Finish(process, "not_eligible",
                $"Le trajet {process.TripId} n'est pas associé à votre compte "
                + $"({process.MemberId}). Je ne peux pas ouvrir de révision à votre nom.");
        }
        // Règle DÉTERMINISTE : un trajet déjà clôturé sans anomalie n'est pas éligible.
        if (status == "closed")
        {
            return Finish(process, "not_eligible",
                $"Le trajet {process.TripId} est déjà clôturé. Un trajet clôturé sans anomalie "
                + "signalée n'est pas éligible à une demande de révision. Si vous constatez tout "
                + "de même un problème, contactez le service à la clientèle.");
        }

        // Éligible (ouvert) : RAG pour la procédure, puis collecte.
        var chunks = await _rag.SearchAsync(
            "procédure trajet resté ouvert après restitution, contestation et révision de frais", 4);
        var context = RagService.BuildContext(chunks);
        process.Step = 3;
        process.FieldIndex = 0;
        process.Attempts = 0;
        var diagnostic = await FormulateAsync(
            $"Le trajet {process.TripId} est toujours ouvert (statut « open »). En une ou deux "
            + "phrases, explique au membre que tu vas ouvrir une demande de révision et que tu as "
            + "besoin de quelques informations, en t'appuyant sur la procédure fournie.",
            context: context.Length > 0 ? "Procédure applicable :\n\n" + context : "",
            fallback: $"Le trajet {process.TripId} est effectivement toujours ouvert. Je vais "
                    + "ouvrir une demande de révision ; j'ai besoin de quelques informations.");
        return diagnostic + "\n\n" + await AskCurrentFieldAsync(process);
    }

    // --- Étape 3 : collecte ---------------------------------------------------

    private async Task<string> AskCurrentFieldAsync(RevisionProcess process)
    {
        var label = CollectFields[process.FieldIndex].Label;
        return await FormulateAsync(
            $"Pose au membre une question courte et polie pour lui demander {label}. Écris "
            + "UNIQUEMENT la question, ne réponds pas à sa place et n'ajoute pas d'explication.",
            fallback: $"Pouvez-vous m'indiquer {label} ?");
    }

    private async Task<string> Step3Async(RevisionProcess process, string userText)
    {
        var (name, label) = CollectFields[process.FieldIndex];
        var (answered, wantsCancel) = await JudgeAnswerAsync(label, userText);

        if (wantsCancel)
        {
            return Cancel(process);
        }
        if (answered)
        {
            process.Collected[name] = userText.Trim();
            process.FieldIndex++;
            process.Attempts = 0;
            if (process.FieldIndex >= CollectFields.Length)
            {
                return ToConfirmation(process);
            }
            return await AskCurrentFieldAsync(process);
        }

        process.Attempts++;
        if (process.Attempts >= MaxAttempts)
        {
            return Finish(process, "aborted",
                "Je n'ai pas réussi à recueillir cette information après plusieurs tentatives, "
                + "je préfère m'arrêter là plutôt que de vous faire tourner en rond. Contactez "
                + "directement le service à la clientèle, qui finalisera votre demande. Aucune "
                + "demande n'a été créée.");
        }
        return await FormulateAsync(
            $"Le membre n'a pas fourni {label}. Repose la question autrement, en une phrase "
            + "courte et polie. Écris UNIQUEMENT la question, ne réponds pas à sa place.",
            fallback: $"Je n'ai pas bien compris. Pouvez-vous préciser {label} ?");
    }

    // --- Étape 4 : confirmation ----------------------------------------------

    private static string ToConfirmation(RevisionProcess process)
    {
        process.Step = 4;
        process.NeedConfirmation = true;
        var c = process.Collected;
        return "Voici le récapitulatif de la demande de révision qui va être créée :\n\n"
            + $"- **Membre** : {process.MemberId}\n"
            + $"- **Trajet** : {process.TripId}\n"
            + $"- **Heure de restitution** : {Get(c, "heure_restitution")}\n"
            + $"- **Emplacement** : {Get(c, "emplacement_restitution")}\n"
            + $"- **Problème** : {Get(c, "description_probleme")}\n\n"
            + "Confirmez-vous la création de cette demande ? Utilisez les boutons "
            + "« Confirmer » ou « Annuler » ci-dessous.";
    }

    // --- Étape 5 : création (déclenchée UNIQUEMENT par le bouton « Confirmer ») -

    public async Task<string> ConfirmAsync(RevisionProcess process)
    {
        process.NeedConfirmation = false;
        process.Step = 5;
        var c = process.Collected;
        var description = Get(c, "description_probleme");
        var infos = $"Heure de restitution : {Get(c, "heure_restitution")}. "
                  + $"Emplacement : {Get(c, "emplacement_restitution")}.";

        var arguments = new Dictionary<string, object?>
        {
            ["member_id"] = process.MemberId,
            ["trip_id"] = process.TripId,
            ["description"] = description,
            ["informations_complementaires"] = infos,
        };
        var resultJson = await _mcp.CallToolAsync("create_revision_request", arguments);
        process.LastToolCall = new ToolCallLog(
            "create_revision_request", JsonSerializer.Serialize(arguments), resultJson);

        var (requestId, status) = ParseCreateResult(resultJson);
        var message =
            $"Votre demande de révision a été créée : identifiant **{requestId}**, statut "
            + $"« {status} ». Elle sera examinée par le service à la clientèle ; aucun "
            + "remboursement n'est garanti avant analyse.";
        return Finish(process, "created", message);
    }

    public string Cancel(RevisionProcess process) => Finish(process, "cancelled",
        "Démarche annulée. Aucune demande n'a été créée. N'hésitez pas à la reprendre quand "
        + "vous le souhaitez.");

    // --- Routage des messages utilisateur pendant le processus ---------------

    public async Task<string> HandleMessageAsync(RevisionProcess process, string userText)
    {
        return process.Step switch
        {
            1 => await Step1Async(process, userText),
            3 => await Step3Async(process, userText),
            // À l'étape 4, on ne valide jamais une écriture sur du texte libre.
            4 => await Step4TextAsync(process, userText),
            _ => "Le processus est terminé.",
        };
    }

    private async Task<string> Step4TextAsync(RevisionProcess process, string userText)
    {
        var (_, wantsCancel) = await JudgeAnswerAsync("la confirmation de la demande", userText);
        if (wantsCancel)
        {
            return Cancel(process);
        }
        return "Pour créer la demande, utilisez le bouton « Confirmer » ci-dessous "
             + "(ou « Annuler » pour abandonner).";
    }

    // --- Aides ---------------------------------------------------------------

    private static string Finish(RevisionProcess process, string outcome, string message)
    {
        process.Active = false;
        process.Outcome = outcome;
        process.NeedConfirmation = false;
        return message;
    }

    private async Task<string> ChatJsonAsync(string system, string user, string schemaJson)
    {
        var request = new ChatRequest
        {
            Model = _model,
            Stream = false,
            Format = JsonSerializer.Deserialize<JsonElement>(schemaJson),
            Options = new RequestOptions { Temperature = 0f },
            Messages = new List<Message>
            {
                new() { Role = ChatRole.System, Content = system },
                new() { Role = ChatRole.User, Content = user },
            },
        };
        Message? message = null;
        await foreach (var chunk in _ollama.ChatAsync(request))
        {
            message = chunk?.Message;
        }
        return message?.Content ?? "{}";
    }

    private static bool ReadBool(string json, string property)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            return doc.RootElement.TryGetProperty(property, out var value)
                   && value.ValueKind == JsonValueKind.True;
        }
        catch
        {
            return false;
        }
    }

    private static (bool Found, string? MemberId, string? Status) ParseTrip(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            if (root.TryGetProperty("found", out var f) && f.ValueKind == JsonValueKind.False)
            {
                return (false, null, null);
            }
            if (!root.TryGetProperty("status", out var status))
            {
                return (false, null, null);
            }
            var member = root.TryGetProperty("member_id", out var m) ? m.GetString() : null;
            return (true, member, status.GetString());
        }
        catch
        {
            return (false, null, null);
        }
    }

    private static (string RequestId, string Status) ParseCreateResult(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            var id = root.TryGetProperty("request_id", out var r) ? r.GetString() : "?";
            var status = root.TryGetProperty("status", out var s) ? s.GetString() : "?";
            return (id ?? "?", status ?? "?");
        }
        catch
        {
            return ("?", "?");
        }
    }

    private static string Get(Dictionary<string, string> collected, string key) =>
        collected.TryGetValue(key, out var value) ? value : "—";
}
