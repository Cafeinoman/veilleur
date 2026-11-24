# ADR-0024 — Sessions éphémères sur pages publiques (DV-02)

- **Statut :** Accepté
- **Date :** 2026-11-19
- **Exigences :** DV-02, EF-06, ES-08, ES-09 ; périmètre §3

## Contexte

Des sites publics, consultables sans compte, ne servent une liste complète qu'à travers un formulaire et un cookie
de session. Le greffon `veilleur-marches` en a besoin hors de sa V1. Le périmètre exclut « la collecte derrière une
authentification interactive » et « le contournement de protections anti-robots ».

## Rapport au hors-périmètre

Une session éphémère n'est pas une authentification : aucun identifiant, aucun compte, aucun mot de passe, aucune
donnée de l'administrateur ; le contenu est celui que tout visiteur anonyme obtient avec un navigateur qui garde ses
cookies. Ce n'est pas un contournement : aucun défi (captcha, JavaScript, preuve de travail) n'est résolu ; une page
de défi reste une panne. Le refus des champs `password` et l'absence de toute saisie d'identifiant gardent cette
frontière. [Probable]

## Options considérées

- Cookies : **`http.cookiejar`** (bibliothèque standard) ; **code propre minimal**. `http.cookiejar` attend des objets
  `urllib.request.Request` et des réponses `urllib`, alors que le client a son propre transport ; il implémente la
  logique de domaine (`Domain=`, sous-domaines, liste des suffixes publics absente) dont une session limitée à un
  seul hôte n'a pas besoin et qui élargirait l'envoi des cookies. **Retenu : code propre**, cookies liés à l'hôte
  exact, analyse des en-têtes `Set-Cookie` par `http.cookies.SimpleCookie` (bibliothèque standard) [Probable : à
  confirmer par un essai sur les formes courantes de `Set-Cookie` au début du lot].
- Formulaires : `post_form(url, fields)` libre (forme demandée par DV-02) ; **formulaire lu dans une page de la
  session**, puis soumis. Le second rend vérifiable le refus des champs `password` (critère 4) ; le premier ne voit
  que des noms de champs. Voir `docs/DECISIONS.md`.

## Décision

- `http.session()` rend une `HttpSession`, gestionnaire de contexte, liée au **premier hôte** demandé :
  `get(url, accept=…)`, `form(response, selector=None) -> Form` (champs, cachés compris, et action, lus par
  l'analyseur HTML de `page`), `submit(form, changes, accept=…)` (POST `application/x-www-form-urlencoded`, ou GET
  si la méthode du formulaire l'est). `post_form(url, fields)` n'est pas fourni (D9) ; la forme est à confirmer avec le greffon `veilleur-marches`
  avant J12-L1.
- Un formulaire qui contient un champ `type=password` est refusé (`password_form_refused`).
- Cookies en mémoire, propres à la session, **jamais écrits sur disque** et **jamais envoyés à un autre hôte** :
  `Domain=` ignoré (cookie lié à l'hôte exact), `Secure` respecté, `Path` ignoré (tout le site) ; 50 cookies de
  4 Kio au plus.
- Une redirection vers un autre hôte est suivie sans cookie (critère 2) ; une requête de session vers un autre hôte
  est refusée (`session_host_refused`).
- 100 requêtes par session au plus (`session_quota_exceeded`), comptées aussi dans le quota de l'hôte.
- Mêmes contrôles que `get` : garde SSRF, politique `robots.txt`, quota, délai, plafonds ; POST : règles de
  redirection de l'ADR-0023.
- La session se ferme à la fin de la collecte, même après une exception : le cœur ouvre une **portée de collecte**
  (ADR-0027) dont la sortie ferme toute session encore ouverte.
- Ni cookie, ni valeur de formulaire, ni adresse dans les journaux.

## Conséquences

- C'est le plus gros chantier des demandes (lot L). Il réutilise l'analyseur HTML de `page` : ses réserves (R17)
  sont à lever avant.
- Ajout au port `HttpClient` (`session`) : voir ADR-0028.

## Sources

- `DEMANDES-VEILLEUR.md`, DV-02 (commit `4cccab5`).
- Documentation Python 3.12, `http.cookiejar` et `http.cookies` — https://docs.python.org/3.12/library/http.cookiejar.html,
  https://docs.python.org/3.12/library/http.cookies.html [Certain, de mémoire ; non relues le 2026-11-19].
