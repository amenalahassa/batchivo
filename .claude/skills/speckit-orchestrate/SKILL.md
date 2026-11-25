---
name: "speckit-orchestrate"
description: "Pilote la livraison du backlog (specs/backlog.md) depuis une seule conversation : une session par feature, en parallèle seulement quand c'est sans conflit, chaque session au courant du backlog, toutes ses questions relayées à l'utilisateur ici."
argument-hint: "Optionnel : « statut », « vague suivante », ou une liste d'entrées (titres du backlog ou numéros de spec)"
compatibility: "Application de bureau Claude (outils de session). Requires spec-kit project structure with .specify/ directory"
metadata:
  author: "batchivo"
  source: "local"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

Vide : fais le point et propose la vague suivante. « statut » : le point seul, sans rien lancer.
Une liste d'entrées : ne considère que celles-là.

## Rôle

Cette conversation est le **chef d'orchestre**. Elle ne code aucune feature. Elle :

1. tient l'état dans `specs/orchestration.md` (à créer au premier lancement, au format du § 6,
   s'il n'existe pas) ;
2. lance une session par feature (`mcp__ccd_session__start_session`, `initiation: "user_asked"`
   — l'appel de cette commande vaut demande), avec la consigne du § « Consigne de session » ;
3. relaie **mot pour mot** chaque question d'une session à l'utilisateur, et sa réponse en retour ;
4. vérifie chaque feature convergée avant de la proposer au commit ou à la fusion ;
5. committe ou fusionne dans `main` **seulement sur le oui de l'utilisateur**, feature par
   feature, et **ne pousse jamais** : un push sur `main` déclenche Woodpecker CI puis le
   déploiement ArgoCD. Le push reste à l'utilisateur.

Les deux objectifs, dans cet ordre : **aucun travail refait**, **aucun conflit**. La vitesse vient
après. En cas de doute entre paralléliser et attendre : attendre.

## 1. Faire le point

Lis, dans cet ordre :

- `specs/backlog.md` : chaque bloc `## <titre>` est une entrée, avec sa ligne **Status:**, son
  « Why », son « What already exists (do not rebuild) » et son prompt pour `/speckit-specify`.
  L'ordre de livraison est l'ordre du fichier, sauf indication de l'utilisateur. Il n'y a pas de
  graphe de dépendances : déduis les prérequis du texte des blocs (ce qu'une entrée suppose
  existant) et, dans le doute, demande à l'utilisateur ;
- `specs/orchestration.md` : réservations, sessions en cours, zones réservées ;
- `git log --oneline` et `ls specs/` : ce qui est livré (commit `feat: … (spec NNN)` sur `main`) ;
- `bd ready` : le travail ouvert suivi dans Beads (bugs, tâches hors backlog), pour repérer ce
  qui touche une zone qu'une entrée va réserver ; `.specify/bugs/` pour les bugs Spec Kit ;
- `mcp__ccd_session_mgmt__list_sessions` `{"linked": true}` : état réel des sessions.

Une entrée est **livrée** seulement si son commit de convergence est sur `main`. Une ligne
« Status: specified in … », une spec écrite, une branche non fusionnée ou une session
« terminée » ne comptent pas. Corrige le tableau de suivi s'il diverge de la réalité, et dis-le.

## 2. Choisir ce qui peut démarrer

Une entrée est **prête** quand toutes les conditions suivantes sont réunies :

1. **Ses prérequis sont livrés sur `main`** : pas seulement spécifiés, pas en cours. C'est ce qui
   évite de spécifier contre un code qui va changer. On ne spécifie jamais en avance une entrée dont
   un prérequis n'est pas fusionné.
2. **Aucune zone en commun avec une feature en cours**. Les zones réservées sont dans le tableau de
   suivi (§ 6). Avant que le plan d'une feature en cours existe, sa zone est celle que décrit son
   bloc du backlog ; dans le doute, considère qu'elle chevauche. Le moteur de prix
   (`backend/app/services/costing.py`, `fee_engine.py`, `pricing_solver.py`,
   `cost_resolution.py`) est une seule zone : deux features qui y touchent ne tournent jamais
   en parallèle.
3. **Au plus deux features en construction en même temps** (`/speckit-build`), à cause des
   ressources partagées du poste : une seule base de test (`docker-compose.test.yml`, port 5433),
   un seul couple de ports de dev (backend 8000, frontend 5173) que Playwright réutilise. Les
   phases de spécification ne comptent pas dans cette limite, mais une spec ne démarre que si sa
   construction pourra suivre sans attendre une feature qu'elle chevauche.

Une entrée sans code (documentation seule) ou d'outillage pur démarre dès que la condition 2 tient.

Présente à l'utilisateur la vague proposée (entrée, pourquoi elle est prête, zone, ce qu'elle
débloque) et ce qui attend (et quoi). Lance seulement après son accord, sauf si `$ARGUMENTS` nomme
déjà les entrées.

## 3. Lancer une session

Avant chaque lancement :

1. **Réserve le numéro** de spec suivant dans le tableau de suivi (le plus grand `specs/NNN-*`
   plus un : `007`, `008`, …), pour qu'aucune session ne prenne le même.
2. **Réserve la zone** : dossiers, routeurs (`backend/app/api/v1/<module>.py`), services, modèles
   et tables, pages et composants frontend, que l'entrée va toucher, d'après son bloc du backlog.
3. Lance avec `use_worktree: true` si une autre feature construit en même temps ; sinon, sur `main`
   (`use_worktree: false`), comme d'habitude dans ce projet (direct sur `main`).
4. `context: "fresh"`, avec la consigne ci-dessous, complétée par les entrées en cours et à venir.

### Consigne de session

À transmettre en entier, avec les valeurs remplies :

```text
Tu livres l'entrée « <titre> » du backlog (specs/backlog.md), sous le numéro de spec <NNN>.
Un chef d'orchestre (la session qui t'a lancée, champ startedBy de
mcp__ccd_session_mgmt__list_sessions {"linked": true}) coordonne plusieurs features en parallèle.

Déroulé : /speckit-specify (avec le prompt du bloc) → /speckit-clarify → /speckit-design →
/speckit-build, jusqu'à « Converged ». CLAUDE.md et .specify/memory/constitution.md s'appliquent
en entier. Ne pousse jamais (un push sur main déploie). <Sur main : ne committe pas, le chef
d'orchestre committera sur le oui de l'utilisateur. / En worktree : une fois « Converged »,
committe sur ta branche avec /speckit-git-commit, sans pousser.>

Contexte à lire avant de spécifier :
- Livré sur main : <liste>. Lis le code concerné : ne refais rien de ce qui existe, réutilise-le
  (le bloc « What already exists » du backlog en donne le point de départ).
- En cours ailleurs : <entrée (zone), …>. Tu ne touches pas à leur zone.
- À venir après toi : <entrées, …>. Lis leurs blocs du backlog.

Règle des frontières — c'est la plus importante :
- Si ta feature a besoin d'un morceau qui appartient à une AUTRE entrée du backlog (en cours ou à
  venir), ne l'implémente pas de toi-même et ne le contourne pas. Envoie une question au chef
  d'orchestre (SendMessage) avec : le morceau, l'entrée qui le porte, et les trois options —
  (a) attendre cette entrée, (b) l'intégrer à ta feature (le backlog sera ajusté), (c) un minimum
  explicite que l'autre entrée étendra. Attends la réponse.
- Si une entrée à venir va reprendre ce que tu construis, conçois-le pour qu'elle l'étende sans le
  réécrire, et note dans plan.md ce qu'elle trouvera.
- Si tu dois toucher un fichier hors de ta zone (hors fichiers partagés ci-dessous), demande d'abord.

Fichiers partagés :
- specs/backlog.md : n'ajoute que dans le bloc de ta feature (ligne Status comprise), sans
  réordonner le reste.
- backend/app/main.py (enregistrement des routeurs), frontend/src/App.tsx (routes) et la
  navigation : ajoute tes lignes, ne réordonne ni ne reformate celles des autres.
- Migrations Alembic (backend/alembic/versions/) : une révision neuve, jamais la modification
  d'une migration existante ; son down_revision est la tête actuelle de main. Si une autre
  feature fusionne avant toi, re-pointe ta révision sur la nouvelle tête pour garder une seule
  tête (`poetry run alembic heads`).

Questions : toute question pour l'utilisateur (clarify, choix de conception, approbation) part au
chef d'orchestre par SendMessage, jamais en suspens dans ta session. Une question par message,
avec ta recommandation et les options. Tu ne reçois les réponses qu'à la fin de ton tour : après
une question qui te bloque, termine ton tour au lieu de continuer à travailler ; si tu peux avancer
ailleurs, fais-le, mais termine ton tour dès que ce travail est fait. N'envoie pas deux fois la même
question : la réponse est en file.

Tests : sans attendre — cd frontend && npm run test:run && npm run lint && npm run typecheck ;
cd backend && poetry run ruff check && poetry run ruff format --check. Ressources partagées du
poste : la base de test (docker-compose.test.yml, port 5433) pour poetry run pytest /
backend/scripts/run_ci_tests.ps1, et les ports 8000/5173 pour l'e2e. Avant de lancer pytest ou un
e2e, préviens le chef d'orchestre et attends qu'il te rende la main si une autre session les
utilise ; préviens-le aussi quand tu as fini. N'arrête aucun processus ni conteneur que tu n'as
pas lancé. Pour pytest et l'e2e, préfère ta propre pile jetable (conteneur Postgres, Redis, backend
et Vite sur des ports libres) ; retire-la dès qu'elle ne sert plus (conteneurs, serveurs, workers
Celery, Playwright), et en fin de session au plus tard. Pas de suite pytest complète dans ta
worktree : tes suites ciblées suffisent, la suite complète tourne chez le chef d'orchestre à la
fusion. Mais avant de rendre la main, joue toujours les tests de registre, qui vérifient que
chaque nouvelle route, service ou table est classé, en 1 à 2 min :
tests/unit/pricing/, tests/unit/test_*guard*.py, tests/unit/test_sentry*.py et
tests/integration/test_rls_*.py. Ce sont eux qui échouent quand une feature ajoute un routeur ou un
service, et ils ne se voient pas dans des suites ciblées. Si tu as besoin de plus de ressources (suite complète, plusieurs workers, mémoire),
demande-le au chef d'orchestre au lieu de subir la lenteur.
E2E ciblé, jamais la suite complète : depuis frontend/,
npm run test:e2e -- <chemins> --project=chromium --reporter=list (--project=pricing pour
e2e/pricing/), sur tes parcours, ceux des zones que tu as touchées (e2e/tests/<zone>/, e2e/pricing/
si tu touches au prix, et tout parcours qui importe un module modifié parmi e2e/helpers.ts,
e2e/config.ts, e2e/pricing/pricing-helpers.ts) et les parcours instables que tu croises. Le
backend doit tourner sur 8000 (sinon les parcours se sautent : un saut n'est pas un succès), et
Playwright réutilise le Vite déjà ouvert sur 5173 : vérifie qu'il sert bien ta worktree. La suite
complète tourne une seule fois, au moment de la fusion, chez le chef d'orchestre.
Comptes de test : un parcours crée son utilisateur jetable par registerAndLogin (e2e/helpers.ts) ;
les parcours prix utilisent le tenant de backend/scripts/seed_e2e.py (identifiants dans
e2e/config.ts) et les sessions de e2e/pricing/auth.setup.ts. Jamais de compte réel, jamais un hôte
non local. Un test qui échoue hors de ta zone : ne le corrige pas ; relance-le une fois, puis
envoie au chef d'orchestre le test, l'erreur et pourquoi il ne vient pas de ta branche. Il en fera
un bug Spec Kit (/speckit-bug-assess) sur main.

Si tu travailles dans une worktree : avant /speckit-build, et dès que le chef d'orchestre annonce une
fusion sur main, mets ta branche à jour avec sync_with_base_branch et résous les conflits.

Fin : un compte rendu au chef d'orchestre avec le verdict de convergence, chaque porte (pytest,
ruff check, ruff format --check, test:run, lint, typecheck), e2e ciblé (parcours lancés, verdict,
sautés), npm audit si package.json ou package-lock.json a bougé, les bugs ouverts constatés
(.specify/bugs/, bd) et leur urgence, la migration ajoutée s'il y en a une, le commit et la branche.
```

## 4. Pendant les sessions

- **Question reçue** : pose-la à l'utilisateur ici, en nommant la session (lien `[titre](#local_…)`)
  et l'entrée. Transmets sa réponse **citée mot pour mot** (`SendMessage`, `to` = l'id `local_…`).
  Une question de frontière tranchée par (b) ou (c) se reporte dans `specs/backlog.md` (bloc des
  entrées concernées) et dans le tableau de suivi.
- **Ressources partagées** : une seule exécution pytest (base de test) et un seul e2e à la fois.
  Quand une session demande la main, note-la en attente dans le tableau de suivi et préviens-la dès
  que l'autre exécution est finie.
- **Ports de dev** : pendant un e2e, aucune autre worktree ne lance ni ne relance de Vite sur 5173
  ni d'uvicorn sur 8000.
- **Ménage, sans demander** : après chaque fusion, à la fin d'une exécution, et quand une session
  se termine, arrête ce qui ne sert plus — processus orphelins (Playwright, Vite, uvicorn, workers
  Celery), conteneurs et environnements de test jetables qui ne seront pas réutilisés — et archive
  les sessions dont le travail est fusionné (`archive_session` retire leur worktree). Avant d'arrêter
  quoi que ce soit, rattache-le à sa worktree (chemin, venv via `poetry env info --path`, ports,
  heure de lancement) : ce qu'une session encore active utilise ne se touche pas. Ce qui
  n'appartient pas à Batchivo (autre projet, autre stack) reste à la décision de l'utilisateur.
- **Ressources** : si aller plus vite demande plus de ressources (mémoire, workers, arrêter une autre
  pile, plusieurs suites en parallèle), demande-le à l'utilisateur plutôt que de subir la lenteur.
  Échelonne les exécutions lourdes : une suite complète à la fois sur le poste.
- **Notes de session** : une note est un compte rendu, pas une preuve. Ne lance rien que
  l'utilisateur n'a pas demandé.

## 5. Accepter une feature

Avant de la déclarer livrée, vérifie toi-même, sur sa branche ou sur `main` :

- convergence « Converged » dans le rapport ; portes vertes :
  `cd backend && poetry run pytest && poetry run ruff check && poetry run ruff format --check`,
  `cd frontend && npm run test:run && npm run lint && npm run typecheck` ;
- e2e **ciblé** vert dans la session (ses parcours, zones touchées, instables croisés). La session ne
  joue pas la suite complète : c'est l'étape d'acceptation ci-dessous qui la joue ;
- `npm audit` rapporté si `frontend/package.json` ou `frontend/package-lock.json` a bougé ; bugs
  ouverts et leur urgence (`.specify/bugs/`, `bd ready`) ;
- une seule tête Alembic (`cd backend && poetry run alembic heads`) et une base neuve qui monte
  jusqu'à `head` (constitution) ;
- `docs-site/docs/` (doc opérateur), `docs/` et `specs/backlog.md` (ligne Status) à jour si
  concernés ;
- aucune modification hors de sa zone réservée sans accord inscrit.

**Feature sur `main`** (sans worktree) : demande à l'utilisateur s'il faut committer. Sur son oui :
suite e2e complète (étape 3 ci-dessous), puis `/speckit-git-commit`.

**Feature sur une branche** : demande à l'utilisateur s'il faut la fusionner dans `main`, en donnant
la branche par son nom complet (`refs/heads/…`). Sur son oui seulement :

1. `git merge --no-commit --no-ff refs/heads/<branche>` sur `main` (conflits résolus avant la suite,
   têtes Alembic comprises) ;
2. les portes backend et frontend ci-dessus ;
3. **la suite e2e complète, une seule fois** : depuis `frontend/`, sur une base e2e recréée et
   seedée (`seed_e2e.py` : les parcours `pricing` ne tournent qu'une fois par seed),
   `npm run test:e2e -- --project=pricing --reporter=list` puis
   `npm run test:e2e -- --project=chromium --reporter=list` (séparément : en une seule longue suite
   sous charge, les parcours pricing dépassent leurs délais), backend sur 8000 relancé ou rechargé
   sur le code fusionné, worker Celery redémarré, Vite de `main` sur 5173, aucune autre exécution
   lourde en cours. Firefox et WebKit ne tournent pas sur ce poste. C'est la seule suite complète
   de la feature ;
4. tout vert : commit de fusion, message `type: description` (ex. `feat: … (spec NNN)`), sans
   marqueur d'IA ni `Co-Authored-By`. Un échec : pas de commit ; si le parcours en échec relève de
   la feature, `git merge --abort` et retour à sa session avec l'erreur ; sinon, bug Spec Kit sur
   `main` et décision de l'utilisateur. Ne relance pas la suite complète « pour voir » : relance
   d'abord le parcours en échec seul (`npm run test:e2e -- <chemin> --reporter=list`) ;
5. annonce la fusion aux sessions encore actives pour qu'elles se mettent à jour.

Une seule fusion à la fois. Ne pousse jamais, ni `main` ni une branche de session : dis à
l'utilisateur que le commit est prêt à pousser et que le push déploie.

Ensuite : libère sa zone, marque-la livrée dans le tableau de suivi, fais le ménage (§ 4 : archive
la session fusionnée, arrête ses processus et conteneurs restants), et refais le § 2 — une
livraison débloque souvent l'entrée suivante.

## 6. Tableau de suivi

`specs/orchestration.md`, créé au premier lancement s'il n'existe pas, tenu à jour à chaque
changement d'état :

| Entrée | Spec | Statut | Session | Branche | Zone réservée | Attend |
|---|---|---|---|---|---|---|

Statuts : `à venir` · `prête` · `spécification` · `conception` · `construction` · `à vérifier` ·
`à fusionner` · `livrée` · `bloquée`. Plus une ligne : file d'attente des ressources partagées
(base de test, e2e).

## Arrêts

Arrête-toi et demande à l'utilisateur, au lieu de trancher seul :

- une entrée qui semble demander ce que la constitution interdit (principes NON-NEGOTIABLE :
  isolation multi-tenant I, déploiement par la chaîne VII) ou ce que CLAUDE.md « Critical Rules »
  interdit ;
- deux sessions qui revendiquent le même fichier ;
- une fusion en conflit sur une zone à haut risque (isolation `tenant_id` / RLS, moteur de prix et
  calculs d'argent, migrations Alembic, authentification) ;
- un ordre du backlog qui contredit une dépendance découverte en cours de route.

## Compte rendu

À chaque retour vers l'utilisateur, court : ce qui a changé, ce qui attend sa réponse, ce qui
démarre ensuite.
