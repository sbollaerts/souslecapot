# Labo 6 — Observer, diagnostiquer et expliquer l'Assistant Bikaroo

Sixième et dernier laboratoire du parcours *Sous le capot de l'IA*. Il reprend
l'assistant complet du labo 5 et ajoute une **observabilité locale** permettant de
reconstruire une exécution complète.

Deux implémentations fonctionnellement équivalentes : **Python** (Streamlit) et
**.NET** (Blazor Server), chacune avec un serveur MCP et un client.

---

## 1. Objectif pédagogique

Un système IA ne doit pas seulement **répondre**, **agir** et **refuser**. Il doit
aussi permettre de comprendre :

```text
ce qui s'est passé · dans quel ordre · avec quelles données
combien de temps chaque étape a pris · quelle règle a été déclenchée
pourquoi le résultat final a été produit
```

Principe central :

> Une suite de logs isolés ne suffit pas. Il faut **corréler** les opérations
> d'une même interaction au moyen d'un identifiant de trace commun.

---

## 2. Ce que fait le code fourni

Tout est repris : chat local (`qwen2.5:3b`), RAG (`bge-m3`), serveur et client
MCP, tools de lecture et d'écriture, workflow en 5 étapes, `TrustedContext`,
`SecurityPolicy`, `SecurityEvent`, modes vulnérable/protégé, fixtures d'injection
et de résultats invalides, stockage SQLite.

Le laboratoire reste **autonome** (ressources dupliquées).

---

## 3. Architecture

```text
Utilisateur → Interface
    ↓
TraceContext              une interaction = un trace_id
    ├── spans                 opérations mesurées
    ├── events                application + sécurité
    ├── workflow_transitions  étape avant → étape après
    └── metrics               durées, compteurs, résultat
    ↓
ObservabilityService
    start_trace · start_span · end_span · record_event
    record_transition · record_error · finish_trace · export_json
    ↓
LLM / RAG / MCP / Security / Workflow
```

Le couplage reste faible : `SecurityPolicy` **publie** ses événements via un
`event_sink` / `EventSink` ; c'est l'application qui les rattache à la trace.

---

## 4. Modèle de trace

| Champ | Rôle |
| --- | --- |
| `trace_id` | `trc-xxxxxxxx`, unique par interaction |
| `started_at` / `ended_at` / `duration_ms` | bornes et durée |
| `status` | `running` `completed` `failed` `cancelled` `refused` |
| `final_outcome` | `created` `cancelled` `aborted` `not_eligible` `refused` `failed` `answered` |
| `user_request_summary` | résumé (160 caractères max) |
| `spans` / `events` / `security_events` / `workflow_transitions` | détail |
| `metrics` | agrégats dérivés |
| `error` | dernière erreur significative |

Une conversation contient **plusieurs traces** : chaque message (et chaque clic
sur Confirmer/Annuler) en ouvre une nouvelle.

---

## 5. Spans

```text
span_id · trace_id · name · category · started_at · offset_ms
ended_at · duration_ms · status · attributes · error
```

Catégories : `llm` `rag` `mcp` `security` `workflow` `application`.

Noms utilisés (tous ne sont pas présents dans chaque trace) :

```text
intent_detection        trip_id_extraction      mcp_get_trip_status
tool_result_validation  identity_validation     rag_search
llm_formulation         answer_judgement        workflow_transition
write_authorization     mcp_create_revision_request     final_response
```

Un span est **toujours fermé**, y compris en cas d'exception (`finally` en
Python, `IDisposable` en .NET).

---

## 6. Événements

```text
timestamp · trace_id · event_type · source · severity · details · attributes
```

Événements de **sécurité** (labo 5, rattachés à la trace) :

```text
prompt_injection_detected   identity_mismatch      invalid_tool_result
unexpected_tool_field       write_attempt_without_confirmation
invalid_write_parameters    untrusted_member_override
```

Événements d'**application** :

```text
mcp_unavailable   rag_no_result   llm_error   workflow_aborted   trace_exported
collect_field_accepted   collect_field_rejected
```

---

## 7. Transitions du workflow

Enregistrées **au moment où elles se produisent**, jamais déduites après coup :

```text
timestamp · trace_id · step_before · step_after · reason · status
```

Parcours nominal observé :

```text
START          → IDENTIFICATION  intention de révision détectée
IDENTIFICATION → DIAGNOSTIC      identifiant de trajet connu
DIAGNOSTIC     → COLLECTE        trajet open et identité valide
COLLECTE       → CONFIRMATION    toutes les informations sont collectées
CONFIRMATION   → CREATION        clic utilisateur sur Confirmer
CREATION       → TERMINATED      demande créée
```

Arrêt sur refus : `DIAGNOSTIC → TERMINATED — identity_mismatch`.

---

## 8. Métriques

```text
total_duration_ms   llm_calls / llm_duration_ms
rag_searches / rag_duration_ms    mcp_calls / mcp_duration_ms
security_event_count   workflow_transition_count   error_count   final_outcome
```

Compléments : `estimated_input_tokens`, `estimated_output_tokens`,
`retrieved_chunks`, `context_chars`.

> `error_count` compte les spans en statut `failed` — ce qui inclut les
> **validations refusées** (résultat de tool invalide, identité non conforme,
> écriture non autorisée). C'est volontaire : ces refus sont des anomalies à
> diagnostiquer, et le détail est visible dans `security_events`.

**Estimation des tokens** : approximation documentée `caractères / 4`. Aucune
dépendance supplémentaire n'est ajoutée pour compter des tokens.

---

## 9. Instrumentation LLM

Chaque appel à Ollama (détection d'intention, jugement, formulation, chat libre)
produit un span portant :

```text
model · call_type · temperature · num_predict
input_chars · output_chars · estimated_input_tokens · estimated_output_tokens
duration_ms · status · error
```

⚠️ Les **prompts complets ne sont pas enregistrés** — seulement leur taille et une
estimation. Un échec produit un événement `llm_error` et ferme le span en `failed`.

---

## 10. Instrumentation RAG

```text
query · top_k · duration_ms · result_count
documents · headings · scores · context_chars · status
```

Les **embeddings ne sont jamais enregistrés**. Une recherche vide produit
`rag_no_result`.

---

## 11. Instrumentation MCP

```text
tool_name · validated_arguments · duration_ms · status · result_summary · error
```

Distinction essentielle, visible dans la trace :

```text
mcp_get_trip_status     = success   ← l'appel a techniquement réussi
tool_result_validation  = failed    ← mais la validation métier a échoué
```

---

## 12. Instrumentation sécurité

`SecurityPolicy` reçoit un `event_sink` (Python) / `EventSink` (.NET) qui publie
chaque `SecurityEvent`. L'application le branche sur
`ObservabilityService.record_security_event`, qui rattache l'événement à la trace
courante. La politique ne dépend pas de l'observabilité.

Les contrôles produisent aussi des spans : `tool_result_validation`,
`identity_validation`, `write_authorization`.

---

## 13. Interface

Un panneau **Observabilité** à trois niveaux :

1. **Vue synthétique** — trace, résultat, durée totale, nombre de spans, LLM /
   RAG / MCP (appels + durées), événements de sécurité, transitions, erreurs.
2. **Chronologie** — spans dans l'ordre, avec leur décalage (`offset_ms`), leur
   durée et leur statut.
3. **Détails** — attributs et erreur de chaque span, plus des sections dédiées aux
   événements de sécurité, aux événements d'application, aux transitions et aux
   métriques.

Un **historique** conserve jusqu'à `MAX_TRACES = 20` traces en session ; on peut
en sélectionner une pour l'inspecter.

---

## 14. Export JSON

Bouton **Exporter la trace JSON** (téléchargement navigateur, pas de persistance
serveur). Structure identique dans les deux stacks :

```json
{
  "trace_id": "trc-c3a9b6ce",
  "started_at": "2026-07-22T22:53:15.700+02:00",
  "ended_at": "2026-07-22T22:53:23.817+02:00",
  "duration_ms": 8117,
  "status": "completed",
  "final_outcome": "created",
  "user_request_summary": "Mon trajet TRP-88231 est resté ouvert, je conteste.",
  "error": "",
  "metrics": { "llm_calls": 7, "llm_duration_ms": 7733, "rag_searches": 1, "…": "…" },
  "spans": [ { "name": "mcp_get_trip_status", "category": "mcp", "duration_ms": 33, "…": "…" } ],
  "events": [],
  "security_events": [],
  "workflow_transitions": [ { "step_before": "START", "step_after": "IDENTIFICATION", "…": "…" } ]
}
```

UTF-8 lisible ; ni prompts complets, ni embeddings.

---

## 15. Simulation de latence

Trois curseurs (LLM, RAG, MCP), de `0` à `2000 ms`, par défaut `0`. La latence
choisie est ajoutée aux spans de la catégorie et devient visible dans la
chronologie et les métriques. **Elle ne modifie jamais le résultat métier.**

---

## 16. Restauration et lancement depuis un clone propre

> **Important : démarrez le serveur MCP AVANT le client.**

### Python (Streamlit)

```bash
cd code/labo-06-observabilite/python
python -m venv .venv
source .venv/bin/activate            # Windows : .venv\Scripts\activate
pip install -r requirements.txt
python mcp_server/server.py          # http://localhost:8000/mcp

# second terminal, même venv
streamlit run app.py
```

### .NET (Blazor Server)

```bash
cd code/labo-06-observabilite/dotnet/McpServer
dotnet run                           # http://localhost:8000/mcp

# second terminal
cd code/labo-06-observabilite/dotnet/AssistantBikaroo
dotnet run
```

Modèles (inchangés) :

```bash
ollama pull qwen2.5:3b
ollama pull bge-m3
ollama list
```

---

## 17. Expérimentations proposées

Résultats mesurés, identiques sur les deux stacks (mode protégé).

| # | Scénario | Résultat observé dans la trace |
| --- | --- | --- |
| 1 | Nominal `TRP-88231` | `created` · 7 appels LLM · 1 RAG · 2 MCP · 6 transitions · 0 erreur |
| 2 | Autre membre `TRP-99005` | `refused` · `identity_mismatch` · aucune écriture |
| 3 | Statut invalide `TRP-99002` | `mcp_get_trip_status=success` **mais** `tool_result_validation=failed` → `invalid_tool_result` · `refused` |
| 4 | Injection RAG | `document-injection-test.md` en tête (score ≈ 0,72) · `prompt_injection_detected` · contenu délimité · workflow inchangé |
| 5 | Serveur MCP arrêté | span `mcp_get_trip_status` en `failed` · `mcp_unavailable` · `failed` · message utilisateur sans stack trace |
| 6 | Latence RAG 1000 ms | `rag_duration_ms` ≈ 1180 ms et durée totale augmentée d'autant |
| 7 | `top_k = 1` | un seul document et son score visibles, `context_chars` réduit |
| 8 | Fausse confirmation | `write_attempt_without_confirmation` · span `write_authorization=failed` · aucune écriture |

Le scénario 4 s'observe depuis le **chat libre** (ex. « Quelle est la procédure
prioritaire pour une demande de révision ? »), car c'est cette requête qui
remonte la fixture d'injection.

---

## 18. Limites volontaires

- **Traces en mémoire de session uniquement** : rien n'est persisté côté serveur.
- **Nombre limité** de traces conservées (`MAX_TRACES = 20`).
- **Pas de backend central**, pas de corrélation entre sessions ni entre machines.
- **Estimation des tokens approximative** (`caractères / 4`).
- **Pas de propagation distribuée réelle** : le `trace_id` n'est pas transmis au
  serveur MCP.
- **Pas d'échantillonnage**, pas de métriques système (CPU, mémoire), pas de
  tableaux de bord.
- **Pas d'OpenTelemetry** : le modèle s'en inspire (traces, spans, attributs) sans
  en adopter l'outillage.

Prolongements industriels possibles, **hors périmètre du code** :

```text
OpenTelemetry · Jaeger · Grafana · Prometheus · Elastic · Application Insights
```

---

## 19. Conclusion des six laboratoires

```text
Labo 1 → converser
Labo 2 → retrouver des connaissances
Labo 3 → consulter des données opérationnelles
Labo 4 → orchestrer et agir
Labo 5 → protéger
Labo 6 → observer, diagnostiquer et expliquer
```

> L'Assistant Bikaroo ne se contente plus de répondre ou d'agir. Il permet
> désormais de reconstruire son exécution, d'expliquer ses décisions et de
> diagnostiquer ses erreurs.
