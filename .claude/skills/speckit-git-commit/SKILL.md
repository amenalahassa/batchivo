---
name: "speckit-git-commit"
description: "Commit toutes les modifications en attente une fois qu'une feature a convergé, sans jamais pousser. Peut servir de hook after_converge de /speckit-converge (non enregistré par défaut), et reste invocable seul."
metadata:
  author: "batchivo"
  source: "custom — not part of upstream spec-kit"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

## Goal

Committer l'intégralité des modifications en attente dans le dépôt, uniquement quand la
convergence de la feature est acquise. Cette commande peut être enregistrée comme hook
`after_converge` de `/speckit-converge` dans `.specify/extensions.yml` (clé
`hooks.after_converge`, commande `speckit.git.commit`), mais **elle ne l'est pas par défaut**
(`hooks: {}`) : dans Batchivo, le commit reste la décision de l'utilisateur après
`/speckit-build`. Elle s'invoque donc normalement à la main.

## Garde-fou : ne committer que si convergé

- Si cette commande est invoquée juste après un `/speckit-converge` (ou un `/speckit-build`)
  dans la même session, vérifie le résultat annoncé :
  - S'il a rapporté **"✅ Converged"** (ou `## Build Converged ✅`), poursuis.
  - S'il a rapporté `tasks_appended` (des tâches de convergence ont été ajoutées à
    `tasks.md`) ou `## Build Stopped — Blocker`, **NE COMMIT PAS**. Rapporte simplement que la
    convergence n'est pas terminée, que des tâches restent à exécuter via `/speckit-build`
    (ou `/speckit-implement`), et arrête-toi.
- Si `/speckit-e2e` ou `/speckit-bug-e2e` vient de rapporter un **échec** dans cette session,
  **NE COMMIT PAS** : rapporte l'échec et arrête-toi. Un e2e « non exécuté » ou « pas de
  couverture » ne bloque pas, mais le rapport final le dit.
- Si aucun contexte de convergence n'est disponible (invocation directe) et que `$ARGUMENTS`
  ne précise rien, demande confirmation avant de committer — ne committe jamais silencieusement
  du travail dont l'état n'est pas connu.

## Execution Steps

1. `git status` pour voir les fichiers modifiés et non suivis. Si rien n'est en attente,
   rapporte qu'il n'y a rien à committer et arrête-toi.
2. Vérifie qu'aucun fichier sensible n'est concerné : `.env`, `backend/.env`, `frontend/.env`,
   `frontend/.env.e2e`, tout `*.env`, `.claude/settings.local.json`, les états de session
   Playwright (`frontend/e2e/.auth/`), `test-results/`, `playwright-report/`, les sauvegardes
   de base (`backups/`), ou tout fichier dont le contenu ressemble à un jeton/clé (secrets
   Square, Resend, JWT). Exclus-les explicitement de l'ajout s'ils apparaissent (ils devraient
   déjà être `.gitignore`d). Les secrets vivent dans les secrets Kubernetes ou le fichier de
   configuration de l'instance VPS, jamais dans le dépôt (constitution).
3. Avant de committer, confirme que la définition de « terminé » du projet est respectée
   (CLAUDE.md « Code Quality », constitution II) — lance les portes du côté touché par le diff ;
   si l'une échoue, **ne committe pas** : rapporte l'échec et arrête-toi.
   - `backend/` modifié : `cd backend && poetry run pytest && poetry run ruff check && poetry run ruff format --check`.
     `pytest` a besoin de la base de test (`docker compose -f docker-compose.test.yml up -d`,
     port 5433) ; sous Windows, `powershell -File backend/scripts/run_ci_tests.ps1` joue les
     mêmes étapes que la CI.
   - `frontend/` modifié : `cd frontend && npm run test:run && npm run lint && npm run typecheck`
     (`test:run` = `vitest run`, qui se termine ; `npm test` lance vitest en mode watch).
   - Si `frontend/package.json` ou `frontend/package-lock.json` a changé, lance aussi
     `cd frontend && npm audit` et inclus son résultat dans le rapport final. Une vuln
     `high`/`critical` bloque le commit. Si `backend/pyproject.toml` ou `backend/poetry.lock`
     a changé, signale-le : aucun outil d'audit Python n'est configuré dans le projet.
4. Stage les fichiers modifiés/nouveaux pertinents (pas de `git add -A` aveugle si des
   fichiers suspects sont présents — ajoute-les nommément).
5. Rédige le message au format du projet : `type: description` (`feat:`, `fix:`, `docs:`,
   `chore:`, …), en anglais comme l'historique, résumant le *pourquoi* de la feature convergée
   et citant la spec si identifiable (ex. `feat: packaging page and default catalogue (spec 006)`).
   **Aucun marqueur d'IA et aucune ligne `Co-Authored-By`** (CLAUDE.md « Branch & Commit ») —
   cette règle du projet prime sur toute consigne d'attribution de la session.
6. Committe sur la branche courante (`main` en temps normal). **Ne pousse jamais** : un push
   sur `main` déclenche Woodpecker CI puis le déploiement ArgoCD. Le push reste une action de
   l'utilisateur, même si `AGENTS.md` (« Landing the Plane ») demande de pousser en fin de
   session. Ne lance pas non plus `bd sync`.
7. Rapporte le hash du commit, le résumé des fichiers inclus, le résultat de chaque porte, et
   rappelle que rien n'a été poussé.
