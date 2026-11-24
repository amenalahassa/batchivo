# Orchestration

Tenu par le chef d'orchestre (`/speckit-orchestrate`). Livré = commit de convergence sur `main`.

| Entrée | Spec | Statut | Session | Branche | Zone réservée | Attend |
|---|---|---|---|---|---|---|
| Ideas | 007 | prête | — | — | `api/v1/ideas.py`, `services/idea_service.py`, `schemas/idea.py`, `models/idea*.py`, `services/image_storage.py` (owner-keyed), `main.py` (montage `/uploads`), `tenant_module_service.py` + `api/v1/modules.py` (module ideas), `models/model.py` + `models/product.py` (`source_idea_id`), frontend `routes/ideas*`, `components/ideas/`, `lib/api/ideas.ts`, `types/idea.ts` | — |
| Generative AI (Replicate) | 008 | à venir | — | — | `services/genai/`, `api/v1/genai*.py`, `models/generation_job.py`, `tasks/genai*.py`, `tenant_settings` (Replicate), `ProductImagesEditor`, pages idées/modèles (actions IA) | 007 livrée |
| Preflight foundations | 009 | à venir | — | — | design brief, `model_file_notes` (typage), calibrations, print test results, `models/printer.py` + secrets chiffrés | 007, 008 et 011 livrées (009 chiffre les secrets d'imprimante que 011 lit) |
| Batchivo MCP server | 010 | à venir | — | — | `mcp/` (processus séparé), jetons API personnels (`auth/`, `api/v1/api_tokens.py`) | 007 livrée (lecture) ; 008, 009 pour leurs outils |
| Bambu print send | 011 | prête | — | — | `services/bambu_mqtt.py`, nouveau `services/bambu_ftps.py` / `bambu_print_send.py`, `api/v1/printers.py` (envoi), page réglages imprimante, dialogue d'envoi | — |

Hors périmètre : 005 (single-tenant VPS) est spécifiée mais non livrée ; aucune session ouverte dessus.

**File d'attente ressources partagées** (base de test 5433, e2e 8000/5173) : vide.
