# Benchmark Groq vs Ollama - Course 23 / Chapitre 1 / Debutant

Date: 2026-07-28T21:14:57.658453+00:00

## Perimetre

- Course ID: 23
- Chapitre: position 1, chapter_id 197, chapter_source_id chapter_1
- Niveau: Debutant
- Variante Groq de reference lue en lecture seule: CourseLevelVariant id 74
- Test Ollama isole: aucun appel Groq, aucune ecriture PostgreSQL, aucune modification de CourseLevelVariant

## Mesures Ollama

- Version Ollama: 0.32.5
- Modele exact: qwen3:1.7b
- Execution locale: oui, via http://localhost:11434
- Temps total mur: 269.23 s
- Temps de chargement modele: 1.539 s
- Temps de generation: 214.605 s
- Tokens prompt: 2050
- Tokens generes: 1263
- RAM libre avant/apres: 2.05 Go / 2.43 Go
- RAM processus Ollama avant/apres: 47.7 Mo / 29.3 Mo
- Erreur memoire: aucune detectee
- JSON valide: True
- Schema respecte: True
- Reparations necessaires: aucune
- Resume: 189 mots
- Explication: 164 mots
- Qualite pedagogique estimee: bon pour benchmark initial
- Points a surveiller: aucun

## Tableau comparatif

| Critere | Groq Debutant enregistre | Ollama local qwen3:1.7b |
|---|---|---|
| Qualite et simplicite pedagogique | Variante IA de reference id 74, chapitre method=ai_generated, ancree sur le chapitre 1. | bon pour benchmark initial; ancrages detectes: sidi mohammed, dar chouafa, merveilles, lalla zoubida, rahma, bain maure, solitude, narrateur. |
| Respect du JSON | Deja stocke comme JSON PostgreSQL. | JSON valide=True; schema respecte=True. |
| Longueur | Resume 129 mots; explication 188 mots. | Resume 189 mots; explication 164 mots. |
| Vitesse | Non mesuree ici; depend du fournisseur distant. | Total 269.23 s; chargement 1.539 s; generation 214.605 s. |
| Ressources materielles | Calcul distant, charge locale faible. | RAM locale utilisee approximative: delta RAM libre -0.38 Go; processus Ollama delta -18.4 Mo. |
| Dependance a Internet | Oui pour l'appel Groq. | Non pour la generation apres telechargement; API locale localhost. |
| Limites de quota | Oui, quotas fournisseur possibles. | Pas de quota API externe; limite materielle locale. |
| Cout | Cout API potentiel. | Pas de cout API par generation locale; cout machine local. |
| Facilite d'integration | Provider principal deja en place dans la plateforme. | Integration possible via API REST Ollama, mais a garder isolee jusqu'a validation qualite/latence. |

## Reference Groq lue en base

- CourseLevelVariant id: 74
- Row generation_method: mixed
- Chapter generation_method: ai_generated
- Model: openai/gpt-oss-20b
- Source hash: 84b85050da587187e5014755a037f7ac9978c734a7c1d90d22c3beee61fd9f9e
- Generated at: 2026-07-28 15:00:44.233718

## Recommandation provisoire

qwen3:1.7b fonctionne localement et produit un JSON exploitable pour un benchmark isole. Il peut servir de piste locale economique et sans quota, mais la recommandation d'integration doit rester provisoire tant que plusieurs chapitres et niveaux n'ont pas ete mesures separement, surtout sur qualite pedagogique et latence.
