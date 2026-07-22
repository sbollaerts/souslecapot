using System.Text.Json;
using System.Text.RegularExpressions;
using OllamaSharp;
using OllamaSharp.Models;
using OllamaSharp.Models.Chat;

namespace AssistantBikaroo;

/// <summary>État d'un processus de révision en cours.</summary>
public class RevisionProcess
{
    public bool Active { get; set; } = true;
    /// <summary>0 = créé mais pas encore démarré (transition START → …).</summary>
    public int Step { get; set; }
    public string MemberId { get; set; } = "";
    public string? TripId { get; set; }
    public string? ValidatedTripId { get; set; }
    public Dictionary<string, string> Collected { get; } = new();
    public int FieldIndex { get; set; }
    public int Attempts { get; set; }
    public string? Outcome { get; set; }
    public bool NeedConfirmation { get; set; }
    public ToolCallLog? LastToolCall { get; set; }
}

/// <summary>Contexte d'exécution : sécurité, identité de confiance, observabilité.</summary>
public record RunContext(SecurityPolicy Policy, TrustedContext Trusted, ObservabilityService Obs);

/// <summary>
/// Orchestration du processus métier, instrumentée — Labo 6.
///
/// Le processus en 5 étapes (labo 4) sous contrôle de sécurité (labo 5) est
/// désormais observable : chaque opération significative ouvre un span, chaque
/// changement d'étape enregistre une transition, et tout est corrélé par le
/// trace_id courant. L'observabilité ne change rien au comportement métier.
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
        [0] = "Non démarré", [1] = "Identification du trajet", [2] = "Diagnostic",
        [3] = "Collecte des informations", [4] = "Confirmation", [5] = "Création de la demande",
    };
    private static readonly Dictionary<int, string> StepNames = new()
    {
        [0] = "START", [1] = "IDENTIFICATION", [2] = "DIAGNOSTIC",
        [3] = "COLLECTE", [4] = "CONFIRMATION", [5] = "CREATION",
    };
    private const string Terminated = "TERMINATED";

    [GeneratedRegex(@"TR[PI]P?-[A-Z0-9]+", RegexOptions.IgnoreCase)]
    private static partial Regex TripRegex();
    [GeneratedRegex(@"MBR-\d+", RegexOptions.IgnoreCase)]
    private static partial Regex MemberRegex();
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
        var m = TripRegex().Match(text ?? "");
        return m.Success ? m.Value.ToUpperInvariant() : null;
    }

    public static string? FindMemberId(string text)
    {
        var m = MemberRegex().Match(text ?? "");
        return m.Success ? m.Value.ToUpperInvariant() : null;
    }

    // --- Appels LLM instrumentés ----------------------------------------------

    private async Task<string> ChatAsync(RunContext ctx, List<Message> messages,
        RequestOptions options, string callType, string spanName, JsonElement? format = null)
    {
        var inputChars = messages.Sum(m => m.Content?.Length ?? 0);
        using var span = ctx.Obs.StartSpan(spanName, SpanCategory.Llm,
            ("model", _model), ("call_type", callType),
            ("temperature", options.Temperature), ("num_predict", options.NumPredict),
            ("input_chars", inputChars),
            ("estimated_input_tokens", inputChars / 4));
        try
        {
            var request = new ChatRequest
            {
                Model = _model, Stream = false, Messages = messages,
                Options = options, Format = format,
            };
            Message? message = null;
            await foreach (var chunk in _ollama.ChatAsync(request))
            {
                message = chunk?.Message;
            }
            var content = message?.Content ?? "";
            span.Set("output_chars", content.Length)
                .Set("estimated_output_tokens", TraceMetrics.EstimateTokens(content));
            return content;
        }
        catch (Exception ex)
        {
            span.Fail(ex);
            ctx.Obs.RecordEvent(AppEventType.LlmError, "llm", "critical",
                $"Appel LLM « {callType} » en échec : {ex.Message}");
            throw;
        }
    }

    public async Task<bool> DetectRevisionIntentAsync(string text, RunContext ctx)
    {
        const string schema =
            """{"type":"object","properties":{"wants_revision":{"type":"boolean"}},"required":["wants_revision"]}""";
        const string system =
            "Tu analyses le message d'un membre Bikaroo. Renvoie wants_revision=true s'il "
            + "veut CONTESTER des frais ou DEMANDER une révision/correction pour un trajet ; "
            + "false pour une simple question d'information ou de procédure. JSON uniquement.";
        try
        {
            var json = await ChatAsync(ctx, Msgs(system, text),
                new RequestOptions { Temperature = 0f }, "intent_detection", "intent_detection",
                JsonSerializer.Deserialize<JsonElement>(schema));
            return ReadBool(json, "wants_revision");
        }
        catch { return false; }
    }

    private async Task<(bool Answered, bool WantsToCancel)> JudgeAnswerAsync(
        string question, string reply, RunContext ctx)
    {
        const string schema =
            """{"type":"object","properties":{"answered":{"type":"boolean"},"wants_to_cancel":{"type":"boolean"}},"required":["answered","wants_to_cancel"]}""";
        var system =
            $"Un membre Bikaroo répond à cette question : « {question} ». Renvoie answered=true "
            + "si sa réponse fournit l'information demandée (même approximative), false si "
            + "absente, incompréhensible, hors sujet ou s'il dit ne pas savoir. Renvoie "
            + "wants_to_cancel=true UNIQUEMENT s'il exprime clairement vouloir arrêter la "
            + "démarche. JSON uniquement.";
        try
        {
            var json = await ChatAsync(ctx, Msgs(system, reply),
                new RequestOptions { Temperature = 0f }, "answer_judgement", "answer_judgement",
                JsonSerializer.Deserialize<JsonElement>(schema));
            return (ReadBool(json, "answered"), ReadBool(json, "wants_to_cancel"));
        }
        catch { return (false, false); }
    }

    private async Task<string> FormulateAsync(string instruction, RunContext ctx,
        string context = "", string fallback = "")
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
        try
        {
            var text = (await ChatAsync(ctx, messages,
                new RequestOptions { Temperature = 0.3f, NumPredict = 220 },
                "formulation", "llm_formulation")).Trim();
            return string.IsNullOrEmpty(text) ? fallback : text;
        }
        catch { return fallback; }
    }

    private static List<Message> Msgs(string system, string user) => new()
    {
        new() { Role = ChatRole.System, Content = system },
        new() { Role = ChatRole.User, Content = user },
    };

    // --- Transitions -----------------------------------------------------------

    private static void Transition(RunContext ctx, RevisionProcess process,
        string stepAfter, string reason, string status = "ok")
    {
        var before = StepNames.TryGetValue(process.Step, out var n) ? n : "START";
        ctx.Obs.RecordTransition(before, stepAfter, reason, status);
        using var span = ctx.Obs.StartSpan("workflow_transition", SpanCategory.Workflow,
            ("step_before", before), ("step_after", stepAfter), ("reason", reason));
    }

    private static string Finish(RunContext ctx, RevisionProcess process,
        string outcome, string message, string reason)
    {
        Transition(ctx, process, Terminated, reason,
            outcome == TraceOutcome.Created ? "ok" : "stopped");
        process.Active = false;
        process.Outcome = outcome;
        process.NeedConfirmation = false;
        if (outcome is TraceOutcome.Aborted or TraceOutcome.Refused)
        {
            ctx.Obs.RecordEvent(AppEventType.WorkflowAborted, "workflow", "warning",
                $"Processus arrêté : {reason}");
        }
        return message;
    }

    // --- Étape 1 : identification ----------------------------------------------

    public async Task<string> AdvanceAfterStartAsync(RevisionProcess process, string userText, RunContext ctx)
    {
        var claimed = FindMemberId(userText);
        ctx.Policy.NoteMemberOverride(claimed, ctx.Trusted);
        if (claimed is not null && !ctx.Policy.Protected)
        {
            process.MemberId = claimed;
        }

        Transition(ctx, process, StepNames[1], "intention de révision détectée");
        process.Step = 1;
        if (process.TripId is not null)
        {
            return await DiagnoseAsync(process, ctx);
        }
        return "Je peux vous aider à contester un trajet. Quel est l'identifiant du "
             + "trajet concerné (format TRP-XXXXX) ?";
    }

    private async Task<string> Step1Async(RevisionProcess process, string userText, RunContext ctx)
    {
        string? tripId;
        using (var span = ctx.Obs.StartSpan("trip_id_extraction", SpanCategory.Application))
        {
            tripId = FindTripId(userText);
            span.Set("found", tripId is not null).Set("trip_id", tripId ?? "");
        }
        if (tripId is null)
        {
            var (_, wantsCancel) = await JudgeAnswerAsync("l'identifiant du trajet à contester", userText, ctx);
            if (wantsCancel) { return Cancel(process, ctx); }
            return "Je n'ai pas repéré d'identifiant de trajet (format TRP-XXXXX). "
                 + "Pouvez-vous me le communiquer ?";
        }
        process.TripId = tripId;
        return await DiagnoseAsync(process, ctx);
    }

    // --- Étape 2 : diagnostic ---------------------------------------------------

    private async Task<string> DiagnoseAsync(RevisionProcess process, RunContext ctx)
    {
        Transition(ctx, process, StepNames[2], "identifiant de trajet connu");
        process.Step = 2;

        // (1) Appel MCP — succès TECHNIQUE.
        string raw;
        using (var span = ctx.Obs.StartSpan("mcp_get_trip_status", SpanCategory.Mcp,
            ("tool_name", "get_trip_status"), ("validated_arguments", process.TripId)))
        {
            try
            {
                raw = await _mcp.CallToolAsync("get_trip_status",
                    new Dictionary<string, object?> { ["trip_id"] = process.TripId });
                span.Set("result_summary", raw.Length > 120 ? raw[..120] : raw);
            }
            catch (Exception ex)
            {
                span.Fail(ex);
                ctx.Obs.RecordError(AppEventType.McpUnavailable, "mcp",
                    $"Serveur MCP injoignable : {ex.Message}");
                return Finish(ctx, process, TraceOutcome.Failed,
                    "Je ne parviens pas à joindre le système opérationnel pour vérifier ce "
                    + "trajet. Réessayez plus tard ou contactez le service à la clientèle.",
                    "mcp_unavailable");
            }
        }

        // (2) Validation MÉTIER — distincte du succès technique.
        TripInfo? trip;
        using (var span = ctx.Obs.StartSpan("tool_result_validation", SpanCategory.Security,
            ("tool_name", "get_trip_status")))
        {
            trip = ctx.Policy.ValidateTripResult(raw);
            span.Set("valid", trip is not null);
            if (trip is null) { span.Fail("Résultat de tool invalide."); }
        }
        if (trip is null)
        {
            return Finish(ctx, process, TraceOutcome.Refused,
                $"Je ne peux pas exploiter les informations du trajet {process.TripId} : le "
                + "résultat reçu est incomplet ou invalide. Par précaution, je m'arrête ici.",
                "invalid_tool_result");
        }

        // (3) Contrôle d'identité.
        bool identityOk;
        using (var span = ctx.Obs.StartSpan("identity_validation", SpanCategory.Security,
            ("trip_member", trip.MemberId), ("authenticated_member", ctx.Trusted.AuthenticatedMemberId)))
        {
            identityOk = ctx.Policy.CheckIdentity(trip, ctx.Trusted);
            span.Set("identity_ok", identityOk);
            if (!identityOk) { span.Fail("identity_mismatch"); }
        }
        if (!identityOk)
        {
            return Finish(ctx, process, TraceOutcome.Refused,
                $"Je ne peux pas ouvrir de demande de révision pour le trajet {trip.TripId} "
                + "avec le compte actuellement authentifié.", "identity_mismatch");
        }

        // (4) Règle métier d'éligibilité.
        if (trip.Status == "closed")
        {
            return Finish(ctx, process, TraceOutcome.NotEligible,
                $"Le trajet {trip.TripId} est déjà clôturé. Un trajet clôturé sans anomalie "
                + "signalée n'est pas éligible à une demande de révision.", "trajet clôturé");
        }

        process.ValidatedTripId = trip.TripId;
        Transition(ctx, process, StepNames[3], "trajet open et identité valide");
        process.Step = 3;
        process.FieldIndex = 0;
        process.Attempts = 0;

        // (5) Recherche RAG instrumentée.
        const string query = "procédure trajet resté ouvert après restitution, contestation et révision de frais";
        string rawContext;
        using (var span = ctx.Obs.StartSpan("rag_search", SpanCategory.Rag,
            ("query", query), ("top_k", 4)))
        {
            var chunks = await _rag.SearchAsync(query, 4);
            rawContext = RagService.BuildContext(chunks);
            span.Set("result_count", chunks.Count)
                .Set("documents", chunks.Select(c => c.Document).ToList())
                .Set("headings", chunks.Select(c => c.Heading).ToList())
                .Set("scores", chunks.Select(c => Math.Round(c.Score, 3)).ToList())
                .Set("context_chars", rawContext.Length);
            if (chunks.Count == 0)
            {
                ctx.Obs.RecordEvent(AppEventType.RagNoResult, "rag", "warning",
                    "Aucun extrait documentaire retrouvé.");
            }
        }

        ctx.Policy.ScanForInjection(rawContext, "rag_document");
        var wrapped = ctx.Policy.WrapUntrusted(rawContext, SecurityPolicy.UntrustedDocumentsTag);

        var diagnostic = await FormulateAsync(
            $"Le trajet {trip.TripId} est toujours ouvert (statut « open »). En une ou deux "
            + "phrases, explique au membre que tu vas ouvrir une demande de révision et que tu "
            + "as besoin de quelques informations, en t'appuyant sur la procédure fournie.",
            ctx, context: wrapped.Length > 0 ? "Procédure applicable :\n\n" + wrapped : "",
            fallback: $"Le trajet {trip.TripId} est effectivement toujours ouvert. Je vais "
                    + "ouvrir une demande de révision ; j'ai besoin de quelques informations.");
        return diagnostic + "\n\n" + await AskCurrentFieldAsync(process, ctx);
    }

    // --- Étape 3 : collecte -----------------------------------------------------

    private async Task<string> AskCurrentFieldAsync(RevisionProcess process, RunContext ctx)
    {
        var label = CollectFields[process.FieldIndex].Label;
        return await FormulateAsync(
            $"Pose au membre une question courte et polie pour lui demander {label}. Écris "
            + "UNIQUEMENT la question, ne réponds pas à sa place et n'ajoute pas d'explication.",
            ctx, fallback: $"Pouvez-vous m'indiquer {label} ?");
    }

    private async Task<string> Step3Async(RevisionProcess process, string userText, RunContext ctx)
    {
        var (name, label) = CollectFields[process.FieldIndex];
        var (answered, wantsCancel) = await JudgeAnswerAsync(label, userText, ctx);

        if (wantsCancel) { return Cancel(process, ctx); }
        if (answered)
        {
            process.Collected[name] = userText.Trim();
            process.FieldIndex++;
            process.Attempts = 0;
            ctx.Obs.RecordEvent("collect_field_accepted", "workflow", "info",
                $"Information « {name} » collectée.");
            if (process.FieldIndex >= CollectFields.Length) { return ToConfirmation(process, ctx); }
            return await AskCurrentFieldAsync(process, ctx);
        }

        process.Attempts++;
        ctx.Obs.RecordEvent("collect_field_rejected", "workflow", "warning",
            $"Réponse inexploitable pour « {name} ».");
        if (process.Attempts >= MaxAttempts)
        {
            return Finish(ctx, process, TraceOutcome.Aborted,
                "Je n'ai pas réussi à recueillir cette information après plusieurs tentatives. "
                + "Contactez directement le service à la clientèle. Aucune demande n'a été créée.",
                $"{MaxAttempts} tentatives infructueuses");
        }
        return await FormulateAsync(
            $"Le membre n'a pas fourni {label}. Repose la question autrement, en une phrase "
            + "courte et polie. Écris UNIQUEMENT la question, ne réponds pas à sa place.",
            ctx, fallback: $"Je n'ai pas bien compris. Pouvez-vous préciser {label} ?");
    }

    // --- Étape 4 : confirmation --------------------------------------------------

    private static string ToConfirmation(RevisionProcess process, RunContext ctx)
    {
        Transition(ctx, process, StepNames[4], "toutes les informations sont collectées");
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

    // --- Étape 5 : création -------------------------------------------------------

    private async Task<string> CreateAsync(RevisionProcess process, string confirmationEvent, RunContext ctx)
    {
        bool authorized;
        using (var span = ctx.Obs.StartSpan("write_authorization", SpanCategory.Security,
            ("confirmation_event", confirmationEvent), ("step", process.Step),
            ("need_confirmation", process.NeedConfirmation)))
        {
            authorized = ctx.Policy.AuthorizeWrite(process, confirmationEvent, ctx.Trusted);
            span.Set("authorized", authorized);
            if (!authorized) { span.Fail("write_attempt_without_confirmation"); }
        }
        if (!authorized)
        {
            return "Je ne peux pas créer la demande : une confirmation explicite est "
                 + "nécessaire. Utilisez le bouton « Confirmer » à l'étape de confirmation. "
                 + "Aucune écriture n'a été effectuée.";
        }

        var parameters = ctx.Policy.BuildWriteParameters(process, ctx.Trusted);
        if (parameters is null)
        {
            return Finish(ctx, process, TraceOutcome.Refused,
                "Les paramètres de la demande n'ont pas pu être validés. Aucune écriture "
                + "n'a été effectuée.", "invalid_write_parameters");
        }

        Transition(ctx, process, StepNames[5], "clic utilisateur sur Confirmer");
        process.NeedConfirmation = false;
        process.Step = 5;

        string resultJson;
        using (var span = ctx.Obs.StartSpan("mcp_create_revision_request", SpanCategory.Mcp,
            ("tool_name", "create_revision_request"),
            ("validated_arguments", $"{parameters["member_id"]} / {parameters["trip_id"]}")))
        {
            try
            {
                resultJson = await _mcp.CallToolAsync("create_revision_request", parameters);
                span.Set("result_summary", resultJson.Length > 120 ? resultJson[..120] : resultJson);
            }
            catch (Exception ex)
            {
                span.Fail(ex);
                ctx.Obs.RecordError(AppEventType.McpUnavailable, "mcp",
                    $"Écriture impossible (serveur MCP) : {ex.Message}");
                return Finish(ctx, process, TraceOutcome.Failed,
                    "La demande n'a pas pu être enregistrée : le système est indisponible. "
                    + "Aucune écriture n'a été effectuée.", "mcp_unavailable");
            }
        }

        process.LastToolCall = new ToolCallLog("create_revision_request",
            JsonSerializer.Serialize(parameters), resultJson);
        var (requestId, status) = ParseCreateResult(resultJson);
        return Finish(ctx, process, TraceOutcome.Created,
            $"Votre demande de révision a été créée : identifiant **{requestId}**, statut "
            + $"« {status} ». Elle sera examinée par le service à la clientèle.", "demande créée");
    }

    public Task<string> ConfirmAsync(RevisionProcess process, RunContext ctx)
        => CreateAsync(process, "button_click", ctx);

    public string Cancel(RevisionProcess process, RunContext ctx) =>
        Finish(ctx, process, TraceOutcome.Cancelled,
            "Démarche annulée. Aucune demande n'a été créée.", "annulation par l'utilisateur");

    // --- Routage -------------------------------------------------------------------

    public async Task<string> HandleMessageAsync(RevisionProcess process, string userText, RunContext ctx)
    {
        ctx.Policy.ScanForInjection(userText, "user_message");

        if (TextConfirmationRegex().IsMatch(userText ?? ""))
        {
            return await CreateAsync(process, "text_confirmation", ctx);
        }

        return process.Step switch
        {
            1 => await Step1Async(process, userText!, ctx),
            3 => await Step3Async(process, userText!, ctx),
            4 => await Step4TextAsync(process, userText!, ctx),
            _ => "Le processus est terminé.",
        };
    }

    private async Task<string> Step4TextAsync(RevisionProcess process, string userText, RunContext ctx)
    {
        var (_, wantsCancel) = await JudgeAnswerAsync("la confirmation de la demande", userText, ctx);
        if (wantsCancel) { return Cancel(process, ctx); }
        return "Pour créer la demande, utilisez le bouton « Confirmer » ci-dessous "
             + "(ou « Annuler » pour abandonner).";
    }

    // --- Aides -----------------------------------------------------------------------

    private static bool ReadBool(string json, string property)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            return doc.RootElement.TryGetProperty(property, out var v) && v.ValueKind == JsonValueKind.True;
        }
        catch { return false; }
    }

    private static (string RequestId, string Status) ParseCreateResult(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            return (root.TryGetProperty("request_id", out var r) ? r.GetString() ?? "?" : "?",
                    root.TryGetProperty("status", out var s) ? s.GetString() ?? "?" : "?");
        }
        catch { return ("?", "?"); }
    }

    private static string Get(Dictionary<string, string> collected, string key) =>
        collected.TryGetValue(key, out var value) ? value : "—";
}
