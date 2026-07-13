# Labo 1 — Chatbot local (Assistant Bikaroo)

Premier laboratoire du parcours *Sous le capot de l'IA*. Il existe en deux
implémentations fonctionnellement équivalentes : **Python** (interface
[Streamlit](https://streamlit.io/)) et **.NET** (interface
[Blazor](https://learn.microsoft.com/aspnet/core/blazor/)). Choisissez celle qui
vous convient : le scénario, les informations affichées et les résultats sont les
mêmes.

---

## 1. Objectif pédagogique

Comprendre le mécanisme de base d'un appel à un LLM (grand modèle de langage)
exécuté **en local** :

> prompt système + prompt utilisateur → génération d'une réponse

et observer l'effet des principaux paramètres de génération (**température**,
**nombre maximum de tokens en sortie**).

Ce labo reste volontairement minimal : pas de RAG, pas de tools, pas de logique
métier. L'idée est de voir clairement ce qui se passe lors d'un appel au modèle,
avant d'enrichir l'assistant dans les labos suivants.

---

## 2. Situation de départ

Vous partez d'un squelette fonctionnel (dossier `depart/`) : l'interface et la
connexion au client Ollama sont déjà en place, mais **le cœur de l'exercice
n'est pas implémenté** — construction du prompt système, historique de
conversation, appel au modèle et prise en compte des paramètres. Des commentaires
`TODO` vous guident pas à pas.

Le dossier `solution/` contient l'implémentation complète, à consulter en cas de
blocage ou pour comparer.

---

## 3. Prérequis et dépendances

| Élément | Rôle | Installation |
| --- | --- | --- |
| [Ollama](https://ollama.com/) | Exécute le LLM en local | voir la side note « Mise en place de l'environnement » du livre |
| Modèle `mistral` | LLM utilisé (bonnes performances en français) | `ollama pull mistral` |
| Python 3.10+ | Implémentation Python | — |
| Streamlit + `ollama` (lib) | Interface et client Python | via `requirements.txt` |
| .NET 10 SDK | Implémentation .NET | — |
| Blazor + OllamaSharp | Interface et client .NET | via le `.csproj` (restauré par NuGet) |

**Aucune dépendance à un service cloud** : tout fonctionne en local avec Ollama.

Avant de lancer un des deux projets, assurez-vous qu'Ollama tourne et que le
modèle est téléchargé :

```bash
ollama pull mistral   # une seule fois
ollama serve          # généralement déjà lancé en tâche de fond
```

### Choix techniques

- **Client Ollama** : côté Python, la bibliothèque officielle
  [`ollama`](https://github.com/ollama/ollama-python) ; côté .NET,
  [`OllamaSharp`](https://github.com/awaescher/OllamaSharp). Dans les deux cas,
  une bibliothèque cliente plutôt qu'un appel HTTP brut, pour rester lisible.
- **Blazor Server** (et non WebAssembly) : le modèle tourne sur la même machine
  que le serveur, l'appel à Ollama se fait donc naturellement côté serveur, sans
  exposer d'API ni gérer CORS. C'est aussi l'option la plus simple à démarrer.

---

## 4. Restauration et lancement depuis un clone propre

### Python (Streamlit)

```bash
cd code/labo-01-chatbot/python/solution   # ou .../depart pour partir du squelette
python -m venv .venv
source .venv/bin/activate                 # Windows : .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Streamlit ouvre l'application dans le navigateur (par défaut
<http://localhost:8501>).

### .NET (Blazor Server)

```bash
cd code/labo-01-chatbot/dotnet/solution/AssistantBikaroo   # ou .../depart/...
dotnet run
```

Ouvrez ensuite l'URL affichée dans la console (par défaut
<http://localhost:5000> ou un port `https://localhost:5xxx`).

---

## 5. Ce qui est déjà préparé dans `depart/`

- Un projet fonctionnel qui **démarre** (dépendances déclarées, interface qui
  s'affiche).
- La structure de fichiers et l'ossature de l'interface (zone de prompt système,
  paramètres, fil de conversation, bouton « Effacer »).
- La connexion au client Ollama (import Python / injection du client .NET).
- Des commentaires `TODO` indiquant précisément ce qu'il reste à écrire.

**Ce qui n'est pas fourni** (c'est l'exercice) : la rédaction du prompt système
par défaut, la construction de la liste de messages (système + historique),
l'appel effectif au modèle avec les paramètres, et l'affichage des informations
techniques.

---

## 6. Ce que vous allez construire

Un chatbot local minimal comprenant :

1. une **zone de prompt système** éditable, avec une valeur par défaut ;
2. une **zone de saisie** pour la question de l'utilisateur ;
3. un **fil de conversation** affichant l'historique (utilisateur / assistant) ;
4. un bouton **« Effacer »** qui vide la conversation mais conserve le prompt
   système ;
5. des **paramètres de génération** modifiables : température et nombre maximum
   de tokens en sortie ;
6. une **zone d'informations techniques** après chaque réponse : modèle utilisé,
   paramètres appliqués, durée de la génération.

Pas de persistance : à chaque démarrage, le prompt système et les paramètres
reviennent à leurs valeurs par défaut.

---

## 7. Étapes principales

En suivant les `TODO` du fichier principal (`app.py` en Python,
`Components/Pages/Chatbot.razor` en .NET) :

1. **Prompt système par défaut** — définir un texte positionnant l'assistant
   comme « Assistant Bikaroo », sans connaissance documentaire.
2. **Contrôles de configuration** — exposer le prompt système (éditable) et les
   curseurs de température et de nombre maximum de tokens.
3. **Appel au modèle** — construire la liste de messages (prompt système +
   historique), appeler Ollama avec les paramètres, mesurer la durée, ajouter la
   réponse à l'historique.
4. **Informations techniques** — afficher modèle, paramètres et durée du dernier
   appel.
5. **Bouton « Effacer »** — vider la conversation en conservant le prompt système.

Une gestion d'erreur simple est prévue : si Ollama n'est pas lancé ou si le
modèle est absent, un message clair s'affiche.

---

## 8. Expérimentations proposées

Une fois l'application fonctionnelle, jouez avec :

- **Modifier le prompt système** : changez le ton ou le rôle de l'assistant
  (formel, familier, « répond comme un mécanicien vélo », etc.).
- **Imposer un format** : demandez des réponses en trois points, en une phrase,
  ou toujours terminées par une question.
- **Faire varier la température** : comparez une température basse (0,1 —
  réponses stables et répétables) et haute (0,9 — réponses plus créatives et
  variées).
- **Répéter la même question** plusieurs fois et observer les variations selon la
  température.
- **Limiter le nombre de tokens** et constater la troncature des réponses
  longues.
- **Poser une question sur Bikaroo** (« Quels sont les tarifs de la Semi-Pro
  League ? ») et constater que le modèle produit une réponse **convaincante mais
  inventée** : il ne connaît pas les documents internes de Bikaroo.

---

## 9. Résultat attendu

Une application locale dans laquelle vous dialoguez avec le modèle `mistral`,
modifiez le prompt système et les paramètres à la volée, voyez l'historique de la
conversation, et disposez après chaque réponse des informations techniques de
l'appel. Le tout sans aucune connexion à un service distant.

---

## 10. Critères de fin de labo

Le labo est terminé lorsque :

- [ ] l'application démarre et répond à une question via `mistral` ;
- [ ] modifier le prompt système change visiblement le comportement de
      l'assistant ;
- [ ] la température et le nombre maximum de tokens ont un effet observable ;
- [ ] le bouton « Effacer » vide la conversation **sans** réinitialiser le prompt
      système ;
- [ ] la zone d'informations techniques affiche modèle, paramètres et durée ;
- [ ] arrêter Ollama produit un message d'erreur clair plutôt qu'un plantage.

---

## 11. La limite révélée par ce labo

> **Le LLM sait produire du texte, mais il ne connaît pas les documents internes
> de Bikaroo.**

Si vous l'interrogez sur les tarifs, les stations ou les conditions
d'abonnement, il répondra de façon plausible… mais sans fondement réel. C'est une
limite fondamentale d'un modèle seul : il génère du langage, il ne consulte
aucune source.

**Transition vers le labo 2 :** le laboratoire suivant introduit le **RAG**
(Retrieval-Augmented Generation), qui permet de fournir au modèle les documents
pertinents de Bikaroo au moment de la génération, pour des réponses ancrées dans
des sources réelles.

---

## 12. Pour aller plus loin

- **Poursuivre votre propre projet** : repartez de votre `solution/` complétée ;
  elle servira de base au labo 2.
- **Repartir proprement** : le dossier `depart/` du dépôt GitHub reste disponible
  pour recommencer l'exercice à zéro, ou pour démarrer directement le labo 2 sur
  une base saine.
