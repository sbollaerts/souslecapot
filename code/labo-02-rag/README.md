# Labo 2 — RAG documentaire (Assistant Bikaroo)

Deuxième laboratoire du parcours *Sous le capot de l'IA*. Il enrichit l'Assistant
Bikaroo du labo 1 avec une chaîne **RAG** (Retrieval-Augmented Generation) : les
réponses peuvent désormais s'appuyer sur des **documents internes de Bikaroo**,
et plus seulement sur les connaissances générales du modèle.

Deux implémentations fonctionnellement équivalentes : **Python** (Streamlit) et
**.NET** (Blazor Server). Même scénario, mêmes informations affichées, mêmes
résultats.

---

## 1. Objectif pédagogique

Montrer comment l'Assistant Bikaroo peut répondre à partir de documents internes,
plutôt que des seules connaissances du LLM. L'expérience centrale consiste à
comparer, sur une même question, deux chemins :

```text
question → LLM seul (comme au labo 1)
question → recherche documentaire → contexte RAG → LLM
```

Le lecteur construit la chaîne complète : découpage du corpus en *chunks*,
calcul d'*embeddings*, indexation dans SQLite, recherche par similarité, et
injection du contexte retrouvé dans le prompt.

---

## 2. Ce que fait le code fourni

Ce labo reprend le chatbot du labo 1 et y ajoute la chaîne RAG. Le code est
fourni **complet et fonctionnel**, directement sous `python/` et `dotnet/` :
ouvrez les fichiers et lisez-les en parallèle du chapitre du livre, qui explique
le RAG au fil de la lecture (découpage du corpus, embeddings, index SQLite,
recherche, injection du contexte). Rien à compléter.

---

## 3. Prérequis et dépendances

| Élément | Rôle | Installation |
| --- | --- | --- |
| [Ollama](https://ollama.com/) | Exécute les modèles en local | voir la side note du livre |
| Modèle `qwen2.5:3b` | Génération de texte (labo 1) | `ollama pull qwen2.5:3b` |
| Modèle `bge-m3` | **Embeddings** multilingues (nouveau) | `ollama pull bge-m3` |
| Python 3.10+ / Streamlit / `ollama` | Implémentation Python | via `requirements.txt` |
| .NET 10 SDK / Blazor / OllamaSharp | Implémentation .NET | via le `.csproj` |
| SQLite | Stockage des chunks + embeddings | intégré (voir ci-dessous) |

- **Python** : `sqlite3` fait partie de la bibliothèque standard — aucune
  dépendance supplémentaire.
- **.NET** : paquet `Microsoft.Data.Sqlite` (ajouté au `.csproj`). Une référence
  directe à `SQLitePCLRaw.bundle_e_sqlite3` (version corrigée) est ajoutée pour
  surcharger une dépendance transitive signalée comme vulnérable.

**Aucune dépendance à un service cloud** : tout fonctionne en local avec Ollama.

Avant de lancer un projet, assurez-vous que les **deux** modèles sont présents :

```bash
ollama pull qwen2.5:3b
ollama pull bge-m3
```

### Choix techniques

- **Client Ollama** : bibliothèque officielle `ollama` (Python) et `OllamaSharp`
  (.NET), utilisées à la fois pour la génération (`chat`) et les embeddings
  (`embed`).
- **Blazor Server** (et non WebAssembly), comme au labo 1 : le modèle et l'index
  vivent côté serveur, l'appel se fait donc naturellement côté serveur.
- **Stockage vectoriel — SQLite plutôt qu'une base vectorielle dédiée :**

  > Ce labo utilise SQLite avec un calcul de similarité en code plutôt qu'une
  > base vectorielle dédiée comme ChromaDB. Une base vectorielle dédiée aurait
  > été plus adaptée à un usage réel (indexation optimisée, passage à l'échelle,
  > recherche approximative rapide), mais SQLite a été retenu ici pour rester
  > simple, sans dépendance ni service supplémentaire à installer — cohérent avec
  > l'objectif pédagogique de ce labo, qui porte sur la compréhension du principe
  > du RAG plutôt que sur l'optimisation de la recherche vectorielle.

- **Index reconstruit une fois puis mis en cache** : au premier démarrage, le
  corpus est découpé, embarqué (embeddings) et stocké dans un fichier
  `bikaroo_rag.db`. Les démarrages suivants réutilisent ce fichier. Supprimer le
  `.db` force une reconstruction. Ce fichier est exclu du versioning
  (`.gitignore`) car reconstructible à partir du corpus.

---

## 4. Restauration et lancement depuis un clone propre

### Python (Streamlit)

```bash
cd code/labo-02-rag/python
python -m venv .venv
source .venv/bin/activate                # Windows : .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Au premier lancement, l'indexation du corpus prend quelques secondes (calcul des
embeddings). L'application s'ouvre ensuite sur <http://localhost:8501>.

### .NET (Blazor Server)

```bash
cd code/labo-02-rag/dotnet/AssistantBikaroo
dotnet run
```

L'indexation a lieu au démarrage (message `[RAG] Corpus indexé : N chunks.` dans
la console). Ouvrez ensuite l'URL affichée.

---

## 5. Organisation du code

- **Python** (`python/`) : `rag.py` — la chaîne RAG (découpage en chunks,
  embeddings, index SQLite, recherche cosinus, construction du contexte) ;
  `app.py` — l'application Streamlit (interface, bascule RAG, curseur top-k,
  affichage des sources) ; `requirements.txt`.
- **.NET** (`dotnet/AssistantBikaroo/`) : `RagService.cs` — la chaîne RAG ;
  `Components/Pages/Chatbot.razor` — l'interface ; `Program.cs` — le démarrage
  (index construit au lancement).
- Le corpus est dans `ressources/` ; c'est l'application qui indique au module
  RAG où le lire (paramètre `corpus_dir` / `corpusDir`).

---

## 6. Ce que le labo ajoute

L'interface du labo 1, augmentée de :

1. une **bascule « Avec RAG » / « Sans RAG »** pour comparer les deux chemins ;
2. une **zone d'affichage des sources** : après chaque réponse en mode RAG, les
   chunks utilisés (document source, section, extrait, **score de similarité**) ;
3. un **prompt système** qui invite le modèle à s'appuyer sur le contexte fourni
   et à signaler explicitement quand l'information n'y figure pas.

Pas de persistance : à chaque démarrage, tout revient aux valeurs par défaut
(l'index est reconstruit si le fichier `.db` a été supprimé).

---

## 7. Étapes principales

Les grandes étapes réalisées par le code (à suivre dans `rag.py` /
`RagService.cs`, puis `app.py` / `Chatbot.razor`) :

1. **Découpage en chunks** — lire les documents `01`→`06`, retirer le
   *frontmatter* YAML, découper sur les titres de section `##`.
2. **Embeddings** — calculer un vecteur par chunk avec `bge-m3` (déjà câblé).
3. **Indexation SQLite** — stocker chunks + embeddings + métadonnées ; ne
   reconstruire que si l'index est absent.
4. **Recherche sémantique** — embarquer la question, calculer la similarité
   cosinus avec chaque chunk, retenir les top-k.
5. **Construction du contexte** — assembler les chunks retrouvés avec leur source.
6. **Bascule RAG** — injecter le contexte dans le prompt uniquement en mode RAG.
7. **Affichage des sources** — enrichir la zone d'informations techniques.

Une gestion d'erreur simple signale si Ollama n'est pas lancé, si un modèle
(`qwen2.5:3b`, `bge-m3`) est absent, ou si le corpus est introuvable.

---

## 8. Expérimentations proposées

En s'appuyant sur `ressources/questions-test.md` :

- **Question couverte par un seul document** (section 1, ex. « Combien coûte
  l'abonnement Semi-Pro League ? ») : comparer la réponse **avec** et **sans**
  RAG. Sans RAG, le modèle peut inventer un tarif ; avec RAG, il cite le corpus.
- **Question multi-documents** (section 2, ex. le trajet de Stéphane reste
  ouvert) : vérifier que des chunks de plusieurs documents sont retrouvés.
- **Question reformulée avec des synonymes** (section 3, ex. « bicyclette
  présentant une anomalie mécanique ») : vérifier que la recherche sémantique la
  retrouve malgré la reformulation.
- **Question volontairement hors-corpus** (section 4, ex. « Combien de vélos sont
  disponibles actuellement près de Flagey ? ») : vérifier que le modèle reconnaît
  l'absence d'information au lieu d'inventer.
- **Top-k** : comparer top 3 et top 5 et observer l'effet sur le contexte fourni.

---

## 9. Résultat attendu

Une application locale où l'on peut, sur une même question, basculer entre le LLM
seul et le LLM enrichi par le RAG, voir les sources retrouvées avec leur score,
et constater que les réponses en mode RAG sont **fondées sur le corpus** et
**citent leurs sources** — le tout sans aucune connexion distante.

---

## 10. Critères de fin de labo

- [ ] l'index se construit au démarrage (N chunks indexés affichés) ;
- [ ] une question couverte donne une réponse fondée sur le corpus, avec sources ;
- [ ] la bascule « Sans RAG » retrouve le comportement du labo 1 ;
- [ ] une question multi-documents retrouve des chunks de plusieurs fichiers ;
- [ ] une question reformulée (synonymes) retrouve les bons chunks ;
- [ ] une question hors-corpus déclenche une réponse « information non disponible » ;
- [ ] la zone technique affiche le mode, le top-k et les sources avec leur score ;
- [ ] arrêter Ollama produit un message clair plutôt qu'un plantage.

---

## 11. La limite révélée par ce labo

> **Le RAG permet de retrouver des connaissances documentaires, mais pas de
> consulter une donnée actuelle ni d'agir sur un système.**

Le corpus décrit des règles stables (tarifs, procédures, zones), mais ne contient
volontairement **aucune donnée temps réel** : disponibilité actuelle des vélos,
statut d'un trajet, historique de facturation, données personnelles d'un membre.
Le RAG retrouve ce qui est écrit dans les documents ; il ne consulte pas un
système opérationnel et n'agit pas.

**Transition vers le labo 3 :** le laboratoire suivant introduit les **tools** et
le **MCP** (Model Context Protocol), qui permettent à l'assistant d'interroger
des systèmes externes et d'obtenir des données actuelles — ce que le RAG seul ne
peut pas faire.

---

## 12. Pour aller plus loin

- **Poursuivre votre propre projet** : repartez du code de ce labo (`python/` ou
  `dotnet/`) ; il sert de base au labo 3.
- **Expérimenter librement** : ajustez la stratégie de découpage, le top-k ou le
  prompt système — vous pouvez toujours revenir à la version du dépôt avec `git`.

---

## Commandes pratiques

Aide-mémoire des commandes utiles pendant le labo.

### Ollama

```bash
ollama serve                 # démarrer le serveur Ollama (souvent déjà lancé)
ollama pull qwen2.5:3b          # modèle de génération (une seule fois)
ollama pull bge-m3           # modèle d'embeddings (une seule fois)
ollama list                  # lister les modèles installés localement
ollama ps                    # voir les modèles chargés en mémoire
curl http://localhost:11434/api/tags   # vérifier qu'Ollama répond
```

### Python (Streamlit)

```bash
cd code/labo-02-rag/python

python -m venv .venv                        # créer l'environnement virtuel
source .venv/bin/activate                   # Windows : .venv\Scripts\activate
deactivate                                  # sortir de l'environnement virtuel

pip install -r requirements.txt             # installer les dépendances
streamlit run app.py                        # lancer l'application
streamlit run app.py --server.port 8502     # lancer sur un autre port
```

Forcer une reconstruction de l'index : supprimer le fichier `bikaroo_rag.db` du
dossier de l'application, puis relancer. Arrêter l'application : `Ctrl+C`.

### .NET (Blazor Server)

```bash
cd code/labo-02-rag/dotnet/AssistantBikaroo

dotnet restore                              # restaurer les paquets NuGet
dotnet build                                # compiler
dotnet run                                  # lancer l'application
dotnet watch run                            # lancer avec rechargement à chaud
```

Forcer une reconstruction de l'index : supprimer `bikaroo_rag.db` du dossier du
projet, puis relancer. Arrêter l'application : `Ctrl+C`.
