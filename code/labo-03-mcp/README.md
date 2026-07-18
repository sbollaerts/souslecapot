# Labo 3 — Tools et MCP (Assistant Bikaroo)

Troisième laboratoire du parcours *Sous le capot de l'IA*. Il ajoute à
l'Assistant Bikaroo la capacité d'utiliser des **tools** via un vrai **serveur
MCP** (Model Context Protocol) : l'assistant peut désormais consulter des
**données opérationnelles** (statut d'un trajet, informations d'un membre), là où
le RAG du labo 2 ne fournissait que de la connaissance documentaire statique.

Deux implémentations fonctionnellement équivalentes : **Python** (Streamlit) et
**.NET** (Blazor Server). Chacune comprend **deux processus** : un serveur MCP et
le client (l'Assistant Bikaroo).

---

## 1. Objectif pédagogique

Montrer comment l'assistant accède à une capacité externe — une donnée
opérationnelle dynamique — via un serveur MCP exposant des tools, et faire la
différence avec la connaissance documentaire du RAG.

Scénario central : Stéphane demande pourquoi son trajet du matin est encore
ouvert. L'assistant combine deux sources :

```text
Que prévoit la procédure en cas de trajet resté ouvert ? → RAG (labo 2)
Quel est le statut réel du trajet de Stéphane maintenant ? → tool MCP get_trip_status
```

Le modèle décide **lui-même** s'il appelle un tool (mécanisme standard MCP). Les
tools **s'ajoutent** au comportement du labo 2 : la bascule « Avec RAG / Sans
RAG » reste, rien n'est remplacé.

---

## 2. Situation de départ

On part de la **solution du labo 2** : le chatbot, le RAG (chunking, embeddings
`bge-m3`, index SQLite, recherche cosinus, bascule RAG) et l'interface sont
**déjà fonctionnels** dans `depart/` — ce n'est pas l'exercice de ce labo.

Le dossier `depart/` ajoute le **squelette MCP** : un serveur avec les deux tools
déclarés mais **non implémentés** (`TODO`), et un client dont la connexion est
câblée mais dont la **boucle d'appel de tools reste à écrire** (`TODO`). Le
dossier `solution/` contient tout, fonctionnel.

---

## 3. Prérequis et dépendances

| Élément | Rôle | Installation |
| --- | --- | --- |
| [Ollama](https://ollama.com/) | Exécute les modèles en local | voir la side note du livre |
| Modèle **`qwen2.5:3b`** | **Génération** (nouveau — voir « Choix techniques ») | `ollama pull qwen2.5:3b` |
| Modèle `bge-m3` | Embeddings (RAG, repris du labo 2) | `ollama pull bge-m3` |
| **SDK MCP** Python (`mcp`) | Serveur FastMCP + client | via `requirements.txt` |
| **SDK MCP** .NET (`ModelContextProtocol`) | Serveur ASP.NET Core + client | via les `.csproj` |
| Python / Streamlit, .NET 10 / Blazor | Interfaces | inchangés depuis le labo 2 |

**Aucune dépendance à un service cloud** : tout fonctionne en local.

```bash
ollama pull qwen2.5:3b   # génération (appel de tools fiable)
ollama pull bge-m3       # embeddings (RAG)
```

### Choix techniques

- **Modèle de génération : `qwen2.5:3b`.** Ce labo exige que le modèle décide
  d'appeler un tool de façon fiable — une capacité qui varie beaucoup d'un modèle
  local à l'autre, surtout en présence d'un contexte RAG (certains modèles
  répondent alors depuis le contexte sans jamais déclencher le tool). Un
  comparatif sur le scénario central (plusieurs modèles, corpus RAG chargé) a
  tranché : `qwen2.5:3b` appelle le bon tool de façon régulière tout en
  n'appelant **pas** de tool sur une question purement procédurale, et il est
  **léger** (~2 Go), donc accessible à la plupart des machines. Le modèle est
  fixé en constante en tête du client (`MODEL` dans `app.py` / `generationModel`
  dans `Program.cs`), facile à changer pour comparer.
  - Sur une machine confortable, `qwen2.5:7b` est encore plus stable.
  - `qwen2.5:3b` est peu fiable à **température 0** (il n'appelle plus le tool) ;
    la valeur par défaut de l'interface (0,7) lui convient très bien. Évitez les
    températures très basses avec ce petit modèle.
  - Les **embeddings** restent `bge-m3`.
- **Transport MCP : Streamable HTTP (et non stdio).** Le stdio réserve le flux
  standard au protocole MCP, ce qui entre en conflit avec les logs de débogage
  (`print`/console). Le HTTP évite ce piège et permet d'inspecter le serveur
  directement (`curl`) avant de le relier au modèle. Serveur et client tournent
  comme deux processus distincts, sur `http://localhost:8000/mcp`.
- **Corpus dupliqué, pas centralisé.** Le corpus documentaire du labo 2 est
  **recopié** dans `code/labo-03-mcp/ressources/` (avec `members.json` et
  `trips.json`), plutôt que partagé entre labos. C'est un choix délibéré : chaque
  labo reste **autonome** et peut être cloné et lancé seul.

---

## 4. Restauration et lancement depuis un clone propre

> **Important : démarrez le serveur MCP AVANT le client.** Le client vérifie la
> connexion au serveur au démarrage.

### Python (Streamlit)

```bash
# 1) Serveur MCP (laisser tourner dans un terminal)
cd code/labo-03-mcp/python/solution        # ou .../depart
python -m venv .venv
source .venv/bin/activate                  # Windows : .venv\Scripts\activate
pip install -r requirements.txt
python mcp_server/server.py                # écoute sur http://localhost:8000/mcp

# 2) Client (dans un SECOND terminal, même venv)
cd code/labo-03-mcp/python/solution
source .venv/bin/activate
streamlit run app.py
```

### .NET (Blazor Server)

```bash
# 1) Serveur MCP (laisser tourner dans un terminal)
cd code/labo-03-mcp/dotnet/solution/McpServer      # ou .../depart/McpServer
dotnet run                                          # écoute sur http://localhost:8000/mcp

# 2) Client (dans un SECOND terminal)
cd code/labo-03-mcp/dotnet/solution/AssistantBikaroo
dotnet run
```

Les dépendances Python (client et serveur) sont identiques ; un seul
`requirements.txt` suffit pour le client, `mcp_server/requirements.txt` déclare
la dépendance du serveur (`mcp`).

---

## 5. Ce qui est déjà préparé dans `depart/`

- **Tout le labo 2** : chatbot, RAG complet, interface, zone d'informations
  techniques (chunks/sources). Fonctionnel, pas de `TODO` dessus.
- Le **squelette du serveur MCP** : serveur FastMCP / ASP.NET Core qui démarre,
  charge `members.json` et `trips.json`, et déclare les deux tools — dont le
  **corps est à écrire**.
- La **connexion client MCP** câblée (liste des tools au démarrage) et les aides
  (conversion du schéma, appel au modèle) — la **boucle d'appel de tools** est à
  écrire.

**Ce qui n'est pas fourni** (l'exercice) : le corps des deux tools côté serveur,
et côté client la boucle « le modèle demande un tool → on l'exécute → on
réinjecte le résultat → le modèle répond », plus l'affichage des appels de tools.

---

## 6. Ce que vous allez construire

1. **Deux tools MCP** : `get_member(member_id)` et `get_trip_status(trip_id)`,
   qui lisent les données synthétiques et renvoient un résultat (ou une absence
   de résultat si l'identifiant est inconnu).
2. **La boucle client** : transmettre les tools au modèle, exécuter l'appel qu'il
   demande, réinjecter le résultat, laisser le modèle conclure.
3. **La zone d'appels de tools** dans l'interface : pour chaque appel, le nom du
   tool, les paramètres et le résultat — dans le prolongement de la zone
   d'informations techniques du labo 2.

---

## 7. Étapes principales

1. **Serveur MCP** — implémenter le corps de `get_member` et `get_trip_status`
   (recherche dans les données chargées ; absence de résultat si inconnu).
   Garder des **descriptions de tools courtes** (un modèle local les appelle plus
   fiablement).
2. **Client — liste des tools** : la connexion et la récupération des tools sont
   déjà câblées ; les convertir au format attendu par le modèle.
3. **Client — boucle d'appel** : appeler le modèle avec les tools ; tant qu'il
   renvoie un appel, l'exécuter, journaliser (nom, paramètres, résultat) et
   réinjecter le résultat (rôle `tool`) ; sinon, renvoyer la réponse finale.
4. **Repli** : si le serveur MCP n'est pas joignable, répondre sans tools et le
   signaler clairement.
5. **Interface** : afficher les appels de tools sous la réponse.

---

## 8. Expérimentations proposées

- **Scénario central** (en vous positionnant comme Stéphane) :
  *« Pourquoi mon trajet TRP-88231 de ce matin est-il toujours ouvert ? Que
  dois-je faire ? »* → l'assistant combine RAG (procédure) et tool
  (`get_trip_status` sur `TRP-88231`).
- **Question purement procédurale** : *« Que dois-je faire si mon trajet reste
  ouvert ? »* → aucun tool ne devrait être appelé, seul le RAG répond.
- **Trajet clôturé** : demander le statut de `TRP-88190` (Stéphane) ou
  `TRP-90044` (Marie) → l'assistant restitue l'information sans confondre les
  membres.
- **Identifiant inexistant** : `TRP-99999` ou `MBR-9999` → l'assistant reconnaît
  l'absence de résultat au lieu d'inventer.
- **Serveur arrêté** : couper le serveur MCP et reposer une question nécessitant
  un tool → le message d'erreur doit être clair (repli sans tools).

---

## 9. Résultat attendu

Une application locale où, sur une même question, l'assistant peut mobiliser le
RAG (documentation) et/ou un tool MCP (donnée opérationnelle), avec l'affichage
des chunks retrouvés **et** des appels de tools (nom, paramètres, résultat) — le
tout sans aucune connexion distante.

---

## 10. Critères de fin de labo

- [ ] le serveur MCP démarre et expose `get_member` et `get_trip_status` ;
- [ ] le client se connecte au serveur et liste les tools au démarrage ;
- [ ] le scénario central appelle `get_trip_status(TRP-88231)` et combine la
      réponse avec la procédure (RAG) ;
- [ ] une question procédurale n'appelle aucun tool ;
- [ ] un identifiant inexistant produit une absence de résultat, pas une
      invention ;
- [ ] la zone d'appels de tools affiche nom, paramètres et résultat ;
- [ ] serveur MCP arrêté → message clair, pas de plantage.

---

## 11. La limite révélée par ce labo

> **Un assistant qui sait utiliser des tools ne sait pas encore conduire de
> manière fiable un processus complet en plusieurs étapes.**

Chaque appel de tool est ici une **décision ponctuelle** du modèle, au cas par
cas, sans enchaînement contrôlé. L'assistant peut consulter une donnée, mais il
ne pilote pas un processus métier (vérifier le trajet, puis appliquer la
procédure, puis déclencher une action, puis confirmer) de façon garantie et
reproductible.

**Transition vers le labo 4 :** le laboratoire suivant introduit
l'**orchestration** — enchaîner des étapes de manière contrôlée, pour conduire un
processus complet plutôt que de laisser le modèle improviser appel par appel.

---

## 12. Pour aller plus loin

- **Poursuivre votre propre projet** : repartez de votre `solution/` complétée ;
  elle servira de base au labo 4.
- **Repartir proprement** : le dossier `depart/` du dépôt GitHub reste disponible
  pour recommencer l'exercice, ou pour démarrer directement le labo 4.

---

## Commandes pratiques

Aide-mémoire des commandes utiles pendant le labo.

### Ollama

```bash
ollama serve                 # démarrer le serveur Ollama (souvent déjà lancé)
ollama pull qwen2.5:3b       # génération (appel de tools) — ce labo
ollama pull bge-m3           # embeddings (RAG) — depuis le labo 2
ollama list                  # lister les modèles installés
curl http://localhost:11434/api/tags   # vérifier qu'Ollama répond
```

### Serveur MCP (à lancer AVANT le client)

```bash
# Python
cd code/labo-03-mcp/python/solution        # ou .../depart
python mcp_server/server.py                # http://localhost:8000/mcp

# .NET
cd code/labo-03-mcp/dotnet/solution/McpServer   # ou .../depart/McpServer
dotnet run                                       # http://localhost:8000/mcp

# Vérifier que l'endpoint MCP répond (poignée de main « initialize ») :
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
# 200 = le serveur répond. (Lister réellement les tools nécessite ensuite la
# session MCP : c'est ce que fait le client de l'Assistant Bikaroo.)
```

Arrêter le serveur : `Ctrl+C`.

### Client Python (Streamlit)

```bash
cd code/labo-03-mcp/python/solution        # ou .../depart
python -m venv .venv
source .venv/bin/activate                  # Windows : .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

### Client .NET (Blazor Server)

```bash
cd code/labo-03-mcp/dotnet/solution/AssistantBikaroo   # ou .../depart/...
dotnet run
```

Forcer une reconstruction de l'index RAG : supprimer `bikaroo_rag.db` du dossier
du client, puis relancer. Arrêter le client : `Ctrl+C`.
