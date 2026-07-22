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
    /// <summary>Identifiant de trajet APRÈS validation : seul utilisable pour l'écriture.</summary>
    public string? ValidatedTripId { get; set; }
    public Dictionary<string, string> Collected { get; } = new();
    public int FieldIndex { get; set; }
    public int Attempts { get; set; }
    public string? Outcome { get; set; }
    public bool NeedConfirmation { get; set; }
    public ToolCallLog? LastToolCall { get; set; }
}

/// <summary>
/// Orchestration du processus métier, sous contrôle de sécurité — Labo 5.
///
/// Reprend le processus en 5 étapes du labo 4 (contrôle déterministe ; le LLM ne
/// fait que comprendre et formuler) et le place derrière la SecurityPolicy :
/// identité issue du TrustedContext, validation stricte des résultats de tools,
/// contenus non fiables délimités, écriture autorisée par le seul clic sur
/// « Confirmer », paramètres reconstruits depuis l'état validé.
/// </summary>
public partial class OrchestrationService
{
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

    // On repère largement les identifiants cités (y compris mal formés) : c'est la
    // validation stricte, ensuite, qui décide de ce qui est acceptable.
    [GeneratedRegex(@"TR[PI]P?-[A-Z0-9]+", RegexOptions.IgnoreCase)]
    private static partial Regex TripRegex();

    [GeneratedRegex(@"MBR-\d+", RegexOptions.IgnoreCase)]
    private static partial Regex MemberRegex();

    // Formulations par lesquelles un utilisateur « affirme » une confirmation.
    // En mode protégé, elles ne déclenchent JAMAIS d'écriture.
    [GeneratedRegex(@"(je\s+confirme|c'?est\s+confirm[ée]|confirme\s+d[ée]j[àa]|cr[ée]e[sz]?\s+(imm[ée]diatement\s+)?(la\s+)?demande|valide\s+la\s+demande)",
        RegexOptions.IgnoreCase)]
    private static partial Regex TextConfirmationRegex();

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

    public static RevisionProcess NewProcess(TrustedContext context) =>
        new() { MemberId = context.AuthenticatedMemberId };

    public static string? FindTripId(string text)
    {
        var match = TripRegex().Match(text ?? "");
        return match.Success ? match.Value.ToUpperInvariant() : null;
    }

    public static string? FindMemberId(string text)
    {
        var match = MemberRegex().Match(text ?? "");
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
        return ReadBool(await ChatJsonAsync(system, text, schema), "wants_revision");
    }

    private async Task<(bool Answered, bool WantsToCancel)> JudgeAnswerAsync(string question, string reply)
    {
        const string schema =
            """{"type":"object","properties":{"answered":{"type":"boolean"},"wants_to_cancel":{"type":"boolean"}},"required":["answered","wants_to_cancel"]}""";
        var system =
            $"Un membre Bikaroo répond à cette question : « {question} ». Renvoie "
            + "answered=true si sa réponse fournit l'information demandée (même approximative), "
            + "false si absente, incompréhensible, hors sujet ou s'il dit ne pas savoir. Renvoie "
            + "wants_to_cancel=true UNIQUEMENT s'il exprime clairement vouloir arrêter la "
            + "démarche. JSON uniquement.";
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

    // --- Démarrage / étape 1 : identification ---------------------------------

    public async Task<string> AdvanceAfterStartAsync(
        RevisionProcess process, string userText, SecurityPolicy policy, TrustedContext context)
    {
        // Une identité affirmée dans un message est une donnée non fiable.
        var claimed = FindMemberId(userText);
        policy.NoteMemberOverride(claimed, context);
        if (claimed is not null && !policy.Protected)
        {
            // Défaut de conception (mode vulnérable) : on fait confiance au message.
            process.MemberId = claimed;
        }

        if (process.TripId is not null)
        {
            return await DiagnoseAsync(process, policy, context);
        }
        process.Step = 1;
        return "Je peux vous aider à contester un trajet. Quel est l'identifiant du "
             + "trajet concerné (format TRP-XXXXX) ?";
    }

    private async Task<string> Step1Async(
        RevisionProcess process, string userText, SecurityPolicy policy, TrustedContext context)
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
        return await DiagnoseAsync(process, policy, context);
    }

    // --- Étape 2 : diagnostic (validation stricte + identité + éligibilité) ---

    private async Task<string> DiagnoseAsync(
        RevisionProcess process, SecurityPolicy policy, TrustedContext context)
    {
        process.Step = 2;
        var raw = await _mcp.CallToolAsync("get_trip_status",
            new Dictionary<string, object?> { ["trip_id"] = process.TripId });

        // (a) Validation stricte du résultat de tool.
        var trip = policy.ValidateTripResult(raw);
        if (trip is null)
        {
            return Finish(process, "invalid_tool_result",
                $"Je ne peux pas exploiter les informations du trajet {process.TripId} : le "
                + "résultat reçu est incomplet ou invalide. Par précaution, je m'arrête ici. "
                + "Contactez le service à la clientèle.");
        }

        // (b) Contrôle d'identité AVANT toute autre règle (source de vérité : TrustedContext).
        if (!policy.CheckIdentity(trip, context))
        {
            return Finish(process, "identity_mismatch",
                $"Je ne peux pas ouvrir de demande de révision pour le trajet {trip.TripId} "
                + "avec le compte actuellement authentifié.");
        }

        // (c) Règle métier déterministe d'éligibilité (héritée du labo 4).
        if (trip.Status == "closed")
        {
            return Finish(process, "not_eligible",
                $"Le trajet {trip.TripId} est déjà clôturé. Un trajet clôturé sans anomalie "
                + "signalée n'est pas éligible à une demande de révision.");
        }

        // Trajet validé : c'est CETTE valeur qui servira à l'écriture.
        process.ValidatedTripId = trip.TripId;
        process.Step = 3;
        process.FieldIndex = 0;
        process.Attempts = 0;

        var chunks = await _rag.SearchAsync(
            "procédure trajet resté ouvert après restitution, contestation et révision de frais", 4);
        var rawContext = RagService.BuildContext(chunks);
        policy.ScanForInjection(rawContext, "rag_document");
        var wrapped = policy.WrapUntrusted(rawContext, SecurityPolicy.UntrustedDocumentsTag);

        var diagnostic = await FormulateAsync(
            $"Le trajet {trip.TripId} est toujours ouvert (statut « open »). En une ou deux "
            + "phrases, explique au membre que tu vas ouvrir une demande de révision et que tu "
            + "as besoin de quelques informations, en t'appuyant sur la procédure fournie.",
            context: wrapped.Length > 0 ? "Procédure applicable :\n\n" + wrapped : "",
            fallback: $"Le trajet {trip.TripId} est effectivement toujours ouvert. Je vais "
                    + "ouvrir une demande de révision ; j'ai besoin de quelques informations.");
        return diagnostic + "\n\n" + await AskCurrentFieldAsync(process);
    }

    // --- Étape 3 : collecte ----------------------------------------------------

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
                "Je n'ai pas réussi à recueillir cette information après plusieurs tentatives. "
                + "Contactez directement le service à la clientèle. Aucune demande n'a été créée.");
        }
        return await FormulateAsync(
            $"Le membre n'a pas fourni {label}. Repose la question autrement, en une phrase "
            + "courte et polie. Écris UNIQUEMENT la question, ne réponds pas à sa place.",
            fallback: $"Je n'ai pas bien compris. Pouvez-vous préciser {label} ?");
    }

    // --- Étape 4 : confirmation ------------------------------------------------

    private static string ToConfirmation(RevisionProcess process)
    {
        process.Step = 4;
        process.NeedConfirmation = true;
        var c = process.Collected;
        return "Voici le récapitulatif de la demande de révision qui va être créée :\n\n"
            + $"- **Membre** : {process.MemberId}\n"
            + $"- **Trajet** : {process.ValidatedTripId ?? process.TripId}\n"
            + $"- **Heure de restitution** : {Get(c, "heure_restitution")}\n"
            + $"- **Emplacement** : {Get(c, "emplacement_restitution")}\n"
            + $"- **Problème** : {Get(c, "description_probleme")}\n\n"
            + "Confirmez-vous la création de cette demande ? Utilisez les boutons "
            + "« Confirmer » ou « Annuler » ci-dessous.";
    }

    // --- Étape 5 : création ----------------------------------------------------

    private async Task<string> CreateAsync(
        RevisionProcess process, string confirmationEvent, SecurityPolicy policy, TrustedContext context)
    {
        if (!policy.AuthorizeWrite(process, confirmationEvent, context))
        {
            return "Je ne peux pas créer la demande : une confirmation explicite est "
                 + "nécessaire. Utilisez le bouton « Confirmer » à l'étape de confirmation. "
                 + "Aucune écriture n'a été effectuée.";
        }

        // Paramètres RECONSTRUITS depuis l'état validé et le contexte de confiance.
        var parameters = policy.BuildWriteParameters(process, context);
        if (parameters is null)
        {
            return Finish(process, "refused",
                "Les paramètres de la demande n'ont pas pu être validés. Aucune écriture "
                + "n'a été effectuée.");
        }

        process.NeedConfirmation = false;
        process.Step = 5;
        var resultJson = await _mcp.CallToolAsync("create_revision_request", parameters);
        process.LastToolCall = new ToolCallLog(
            "create_revision_request", JsonSerializer.Serialize(parameters), resultJson);

        var (requestId, status) = ParseCreateResult(resultJson);
        return Finish(process, "created",
            $"Votre demande de révision a été créée : identifiant **{requestId}**, statut "
            + $"« {status} ». Elle sera examinée par le service à la clientèle.");
    }

    /// <summary>Bouton « Confirmer » : le SEUL signal autorisant une écriture en mode protégé.</summary>
    public Task<string> ConfirmAsync(RevisionProcess process, SecurityPolicy policy, TrustedContext context)
        => CreateAsync(process, "button_click", policy, context);

    public string Cancel(RevisionProcess process) =>
        Finish(process, "cancelled", "Démarche annulée. Aucune demande n'a été créée.");

    // --- Routage des messages utilisateur -------------------------------------

    public async Task<string> HandleMessageAsync(
        RevisionProcess process, string userText, SecurityPolicy policy, TrustedContext context)
    {
        // Toute entrée utilisateur est une donnée non fiable : on la scanne.
        policy.ScanForInjection(userText, "user_message");

        // Une « confirmation » exprimée en texte libre n'est pas une confirmation.
        if (TextConfirmationRegex().IsMatch(userText ?? ""))
        {
            return await CreateAsync(process, "text_confirmation", policy, context);
        }

        return process.Step switch
        {
            1 => await Step1Async(process, userText!, policy, context),
            3 => await Step3Async(process, userText!),
            4 => await Step4TextAsync(process, userText!),
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

    // --- Aides -----------------------------------------------------------------

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
