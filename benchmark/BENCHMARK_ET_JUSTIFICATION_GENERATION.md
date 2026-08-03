# BENCHMARK ET JUSTIFICATION GENERATION

## 1. Objectif du benchmark

Comparer de maniere isolee Groq et Ollama sur deux niveaux adaptatifs, Debutant et Intermediaire, pour le cours 23 chapitre 1. Le benchmark ne modifie pas `CourseLevelVariant`.

## 2. Architecture du pipeline de generation

- Lecture des sources du chapitre depuis PostgreSQL (`Course`, `CourseChapter`).
- Compactage identique avec `prepare_compact_variant_sources`.
- Deux appels par execution valide: `main_content`, puis `pedagogical_support`.
- Validation avec les schemas Pydantic et les validateurs de production.

## 3. Conditions experimentales

- Course: `23`.
- Chapitre position: `1`.
- Modele Groq: `openai/gpt-oss-20b`.
- Modele Ollama: `qwen3:1.7b`.
- Aucun parallelisme.
- Aucun retry automatique Groq dans le benchmark.
- Aucun fallback marque comme succes.

## 4. Seuils pedagogiques

- Debutant: seuils actuels du pipeline Debutant.
- Intermediaire: resume >= 110 mots, explication >= 200 mots, learning_support >= 100 mots, au moins 5 key_points, au moins 5 termes de vocabulaire, cinq sections completes.

## 5. Tableau comparatif

| Niveau | Solution | Modele | Statut | Appels | JSON valide | Resume | Explication | Support | Sections | Qualite |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| debutant | Groq | openai/gpt-oss-20b | rate_limited | 1 | False | 0 | 0 | 0 | False | 0 |
| debutant | Ollama local | qwen3:1.7b | not_available | 0 | False | 0 | 0 | 0 | False | 0 |
| intermediaire | Groq | openai/gpt-oss-20b | rate_limited | 1 | False | 0 | 0 | 0 | False | 0 |
| intermediaire | Ollama local | qwen3:1.7b | not_available | 0 | False | 0 | 0 | 0 | False | 0 |

## 6. Analyse par niveau

### debutant
- Groq / openai/gpt-oss-20b: statut `rate_limited`, appels `1`, JSON valide `False`, erreurs: Groq request failed: HTTP 429 {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `[REDACTED]` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199725, Requested 2515. Please try again in 16m7.68s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
; retry_after_seconds=967.68.
- Ollama local / qwen3:1.7b: statut `not_available`, appels `0`, JSON valide `False`, erreurs: Ollama non installe ou absent du PATH..

### intermediaire
- Groq / openai/gpt-oss-20b: statut `rate_limited`, appels `1`, JSON valide `False`, erreurs: Groq request failed: HTTP 429 {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `[REDACTED]` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199723, Requested 2593. Please try again in 16m40.512s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
; retry_after_seconds=1000.512.
- Ollama local / qwen3:1.7b: statut `not_available`, appels `0`, JSON valide `False`, erreurs: Ollama non installe ou absent du PATH..

## 7. Impact de la complexite du niveau

Le niveau Intermediaire impose des seuils plus eleves que Debutant. Il augmente donc la pression sur le budget de tokens, le respect du format JSON et la longueur utile du contenu.

## 8. Justification du choix technique final

Recommendation mesuree: **NOT_DETERMINED**. Aucune execution complete n'a permis de comparer objectivement la qualite; Groq ou Ollama doivent etre retestes quand les ressources sont disponibles.

## 9. Limites

- Si Groq retourne HTTP 429, la comparaison de qualite est partielle.
- Si Ollama ou `qwen3:1.7b` n'est pas installe, l'execution locale est partielle.
- Les scores pedagogiques sont heuristiques et doivent etre confirmes par une evaluation enseignante.
