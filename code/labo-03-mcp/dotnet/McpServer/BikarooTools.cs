using System.ComponentModel;
using ModelContextProtocol.Server;

namespace McpServer;

/// <summary>
/// Les deux tools exposés par le serveur MCP. Les descriptions sont
/// volontairement courtes et directes : un modèle local choisit d'appeler un
/// tool bien plus fiablement avec une description brève qu'avec un long
/// paragraphe. Le service BikarooData est injecté par le conteneur.
/// </summary>
[McpServerToolType]
public class BikarooTools
{
    [McpServerTool(Name = "get_member")]
    [Description("Donne les informations d'un membre Bikaroo à partir de son identifiant, par exemple MBR-1042.")]
    public static string GetMember(BikarooData data,
        [Description("Identifiant du membre, par exemple MBR-1042.")] string member_id)
        => data.GetMember(member_id);

    [McpServerTool(Name = "get_trip_status")]
    [Description("Donne le statut réel et actuel d'un trajet Bikaroo à partir de son identifiant, par exemple TRP-88231.")]
    public static string GetTripStatus(BikarooData data,
        [Description("Identifiant du trajet, par exemple TRP-88231.")] string trip_id)
        => data.GetTripStatus(trip_id);
}
