# Corpus Bikaroo — Laboratoire 2

Ce dossier contient un corpus documentaire fictif destiné au laboratoire 2 du livre *Sous le capot de l’IA*.

L’objectif est de permettre à l’Assistant Bikaroo de répondre à des questions à partir de documents internes, grâce à une chaîne RAG locale :

```text
documents Markdown
→ découpage en chunks
→ embeddings
→ index vectoriel
→ recherche sémantique
→ contexte fourni au LLM
→ réponse fondée avec sources
```

## Contenu

| Fichier | Sujet |
|---|---|
| `01-offres-et-tarifs.md` | Formules Amateur, Semi-Pro et Pro League |
| `02-procedure-trajet-reste-ouvert.md` | Traitement d’un trajet encore ouvert après restitution |
| `03-faq-utilisation.md` | Questions fréquentes sur l’utilisation du service |
| `04-zones-et-stationnement.md` | Zones de service et règles de stationnement |
| `05-securite-et-signalement.md` | Sécurité, dommages et signalement d’un vélo |
| `06-contestations-et-remboursements.md` | Contestations, demandes de révision et remboursements |

## Principes pédagogiques

Le corpus contient :

- des formulations différentes pour des concepts proches ;
- des informations réparties entre plusieurs documents ;
- des règles explicites qui peuvent être citées ;
- des questions pour lesquelles l’information est volontairement absente ;
- des données documentaires stables, mais aucune donnée opérationnelle en temps réel.

## Limite volontaire

Le corpus ne contient pas :

- le nombre actuel de vélos disponibles ;
- l’état en temps réel d’un trajet ;
- les données personnelles d’un membre ;
- l’historique de facturation d’un utilisateur ;
- le statut courant d’une demande.

Ces informations devront plus tard être obtenues via des tools et un système opérationnel.

## Statut

Tous les documents sont fictifs et créés uniquement pour les besoins pédagogiques du laboratoire.
