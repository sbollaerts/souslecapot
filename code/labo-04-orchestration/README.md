# Labo 4 — Orchestrer un processus métier (Assistant Bikaroo)

Quatrième laboratoire du parcours *Sous le capot de l'IA*. Il fait passer
l'Assistant Bikaroo d'**appels ponctuels** (une question → une réponse,
éventuellement enrichie par le RAG ou un tool) à un **processus métier explicite
en plusieurs étapes**, avec un état visible, une distinction claire entre logique
déterministe et contribution du LLM, et — pour la première fois du parcours —
une **action d'écriture** protégée par une confirmation explicite.

Deux implémentations fonctionnellement équivalentes : **Python** (Streamlit) et
**.NET** (Blazor Server), chacune avec un serveur MCP et un client.

---

## 1. Objectif pédagogique

Montrer comment conduire un **processus contrôlé en 5 étapes**, où :

- l'**application** décide de façon **déterministe** de l'enchaînement des étapes,
  des règles d'éligibilité, du moment de demander confirmation et du moment
  d'écrire ;
- le **LLM** contribue uniquement à *comprendre* l'utilisateur (détecter
  l'intention, juger si une réponse convient) et à *formuler* les messages ;
- aucune **écriture** (créer une demande de révision) n'a lieu sans un clic de
  confirmation explicite.

---

## 2. Ce que fait le code fourni

Le code est complet et fonctionnel (pas de squelette à compléter). Il reprend les
acquis des labos précédents — chat, **RAG** (labo 2), **tools de lecture**
`get_member` / `get_trip_status` via MCP (labo 3) — et ajoute :

- un **tool d'écriture** `create_revision_request`, qui enregistre une demande
  dans une base SQLite ;
- un **module d'orchestration** qui pilote un processus de contestation de frais
  en 5 étapes ;
- une interface qui affiche l'**étape courante** et propose des boutons
  **Confirmer / Annuler** au moment décisif.

En dehors du processus, l'assistant garde le comportement du labo 3 (chat + RAG +
tools de lecture).

---

## 3. Prérequis et dépendances

Rien de nouveau par rapport au labo 3 :

| Élément | Rôle |
| --- | --- |
| [Ollama](https://ollama.com/) + `qwen2.5:3b` | Génération |
| `bge-m3` | Embeddings (RAG) |
| SDK MCP (`mcp` Python / `ModelContextProtocol` .NET) | Serveur + client MCP |
| SQLite (`sqlite3` standard / `Microsoft.Data.Sqlite`) | RAG **et** demandes de révision |

```bash
ollama pull qwen2.5:3b
ollama pull bge-m3
```

---

## 4. Restauration et lancement depuis un clone propre

> **Important : démarrez le serveur MCP AVANT le client** (comme au labo 3).

### Python (Streamlit)

```bash
# 1) Serveur MCP (laisser tourner)
cd code/labo-04-orchestration/python
python -m venv .venv
source .venv/bin/activate                  # Windows : .venv\Scripts\activate
pip install -r requirements.txt
python mcp_server/server.py                # http://localhost:8000/mcp

# 2) Client (second terminal, même venv)
cd code/labo-04-orchestration/python
source .venv/bin/activate
streamlit run app.py
```

### .NET (Blazor Server)

```bash
# 1) Serveur MCP
cd code/labo-04-orchestration/dotnet/McpServer
dotnet run                                 # http://localhost:8000/mcp

# 2) Client (second terminal)
cd code/labo-04-orchestration/dotnet/AssistantBikaroo
dotnet run
```

---

## 5. Ressources dupliquées

Le dossier `ressources/` **duplique** le corpus documentaire (6 documents +
`README-corpus.md` + `questions-test.md`) et les données synthétiques
(`members.json`, `trips.json`) des labos 2 et 3. C'est un choix délibéré : chaque
labo reste **autonome** et peut être cloné et lancé seul, sans dépendre des
dossiers des autres labos.

La base des demandes de révision (`revision_requests.db`) est créée par le serveur
MCP, à côté de lui (`python/mcp_server/` ou `dotnet/McpServer/`), et **exclue de
Git** (`.gitignore`).

---

## 6. Ce que le labo ajoute — le scénario en 5 étapes

Stéphane (`MBR-1042`) constate que son trajet du matin (`TRP-88231`, resté
ouvert) va lui occasionner des frais indus et veut contester. L'assistant le guide :

```text
1. Identification   — quel trajet ? (identifiant TRP-XXXXX)
2. Diagnostic       — statut réel (get_trip_status) + procédure (RAG)
                      → règle déterministe d'éligibilité
3. Collecte         — heure de restitution, emplacement, description du problème
                      → max 3 tentatives par information
4. Confirmation     — récapitulatif + boutons « Confirmer » / « Annuler »
5. Création         — create_revision_request (écriture) → identifiant + statut
```

Le processus démarre **naturellement** : le modèle reconnaît l'intention de
contester (pas de bouton « démarrer » dédié), puis l'application pilote les étapes.

---

## 7. Points clés du code à observer

- **Déterministe vs LLM.** Tout le contrôle des étapes est dans le module
  d'orchestration (`orchestration.py` / `OrchestrationService.cs`) : c'est *lui*
  qui décide de passer à l'étape suivante, d'arrêter, de demander confirmation,
  d'écrire. Le LLM n'est appelé que pour *comprendre* (détection d'intention et
  jugement des réponses, en **sortie JSON structurée**) et *formuler* les
  messages. Il ne décide jamais d'un changement d'étape.
- **Règle d'éligibilité (étape 2).** Un trajet déjà `closed` (ou inexistant, ou
  appartenant à un autre membre) arrête le processus proprement, dans le code —
  ce n'est pas laissé au LLM.
- **Confirmation avant écriture (étape 4).** `create_revision_request` n'est
  appelé qu'au clic sur « Confirmer ». Ce tool d'écriture n'est **jamais** exposé
  au modèle dans le chat libre (voir `WRITE_TOOLS` / `WriteTools`) : le modèle ne
  peut pas le déclencher seul.
- **Robustesse simple.** Au bout de 3 réponses inexploitables sur une même
  information, le processus s'arrête en renvoyant vers le service à la clientèle
  (pas de boucle infinie).
- **État du processus.** Un objet d'état (étape courante, trajet, informations
  collectées, tentatives) est porté par la session (Streamlit) ou la page (Blazor).

---

## 8. Expérimentations proposées

- **Scénario complet** : en tant que Stéphane, écrivez par exemple *« Mon trajet
  TRP-88231 est resté ouvert ce matin, je veux contester les frais »*, répondez
  aux questions, puis cliquez sur **Confirmer** → une demande est créée.
- **Annuler** : à l'étape de confirmation, cliquez sur **Annuler** → aucune
  demande n'est créée.
- **Trajet déjà clôturé** : tentez une révision sur `TRP-88190` → le processus
  s'arrête dès le diagnostic (non éligible).
- **3 réponses hors sujet** : répondez n'importe quoi 3 fois à une question de
  collecte → le processus s'arrête et renvoie vers le service à la clientèle.
- **Changement de sujet / abandon** : dites « laisse tomber » en cours de route →
  la démarche s'interrompt proprement, sans rien créer.

---

## 9. Résultat attendu

Une application locale où une simple phrase de l'utilisateur déclenche un
processus guidé, visible étape par étape, se terminant — après confirmation
explicite — par la création d'une demande de révision (identifiant + statut
`pending`) stockée en base, ou par un arrêt propre (non éligible, annulé,
abandonné). Le tout sans aucune connexion distante.

---

## 10. Critères de fin de labo

- [ ] une phrase de contestation démarre le processus ; l'étape courante s'affiche ;
- [ ] un trajet ouvert éligible mène à la collecte des informations ;
- [ ] un trajet clôturé / inexistant / d'un autre membre arrête le processus au
      diagnostic ;
- [ ] la demande n'est créée qu'au clic sur « Confirmer » ; « Annuler » ne crée rien ;
- [ ] 3 réponses inexploitables arrêtent proprement le processus ;
- [ ] l'appel à `create_revision_request` apparaît dans la zone d'informations
      techniques (paramètres + résultat) ;
- [ ] le tool d'écriture n'est jamais appelé par le modèle en chat libre.

---

## 11. La limite révélée par ce labo

> **Plus le système possède de connaissances et de capacités, plus une
> instruction malveillante, ambiguë ou mal interprétée peut avoir des
> conséquences.**

C'est la première fois qu'une **action d'écriture réelle** est introduite. La
confirmation explicite protège le cas nominal, mais elle ne suffit pas : que se
passe-t-il si un document consulté par le RAG contient une instruction cachée ? si
un membre tente d'ouvrir une révision au nom d'un autre ? si une réponse est
formulée pour tromper le modèle ?

**Transition vers le labo 5 :** le laboratoire suivant porte sur la **sécurité**.
Il attaquera précisément ce qui est construit ici (injection de prompt, données
non fiables, contrôle d'identité) et renforcera l'assistant en conséquence.

---

## 12. Limites volontaires

- **SQLite pour les demandes de révision.** Comme pour l'index RAG au labo 2, on
  reste sur SQLite : simple, sans service supplémentaire. Une vraie application
  utiliserait une base applicative avec transactions, contraintes et historique.
  La base est **réinitialisée à chaque démarrage** du serveur (repartir propre) ;
  elle n'est pas versionnée.
- **Limite de 3 tentatives de clarification.** C'est une robustesse volontairement
  minimale pour éviter les boucles ; une vraie application gérerait plus finement
  les reformulations et les canaux alternatifs.
- **Pas d'authentification réelle.** Le membre connecté est simplement
  pré-configuré dans l'interface. Le contrôle d'identité est hors sujet ici — il
  sera abordé au labo 5.
- **Pas de moteur de workflow générique.** Les 5 étapes sont codées explicitement,
  pas dans un framework réutilisable : c'est plus lisible pour comprendre le
  principe.

---

## Commandes pratiques

### Ollama

```bash
ollama serve                 # démarrer Ollama (souvent déjà lancé)
ollama pull qwen2.5:3b       # génération
ollama pull bge-m3           # embeddings (RAG)
ollama list                  # modèles installés
```

### Serveur MCP (à lancer AVANT le client)

```bash
# Python
cd code/labo-04-orchestration/python
python mcp_server/server.py                 # http://localhost:8000/mcp

# .NET
cd code/labo-04-orchestration/dotnet/McpServer
dotnet run                                   # http://localhost:8000/mcp
```

### Client Python (Streamlit)

```bash
cd code/labo-04-orchestration/python
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

### Client .NET (Blazor Server)

```bash
cd code/labo-04-orchestration/dotnet/AssistantBikaroo
dotnet run
```

Réinitialiser l'index RAG : supprimer `bikaroo_rag.db` du dossier du client.
Réinitialiser les demandes : elles le sont automatiquement au (re)démarrage du
serveur MCP. Arrêter un processus : `Ctrl+C`.
