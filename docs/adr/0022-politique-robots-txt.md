# ADR-0022 — Politique `robots.txt` : passer outre avec alerte, `enforce` au choix

- **Statut :** Accepté
- **Date :** 2026-11-19
- **Révise :** ADR-0014 (partie `robots.txt`), décision du cahier §10 du 2026-11-18 (« `robots.txt` illisible (5xx)
  refuse la requête »), EF-06 (« respect de `robots.txt` »)
- **Exigences :** EF-06 (révisée), EF-07 (nouvelle), DV-01 et DV-02 (critères révisés), DV-04

## Contexte

Veilleur 0.1.0 refuse toute adresse que `robots.txt` interdit à l'agent `Veilleur` (`robots_disallowed`) et toute
requête vers un hôte dont le `robots.txt` est illisible (`robots_unavailable`). Ce respect est un engagement public
(README, guide d'écriture d'un collecteur, `design.md`). Les demandes DV-01 et DV-02 du greffon `veilleur-marches`
le reprennent dans leurs critères.

Or Veilleur ne **découvre** pas de pages : il lit des adresses qu'un humain a choisies (l'administrateur, ou un
membre que l'administrateur y autorise, EF-11), à une fréquence faible (un tour par jour par défaut), comme un lecteur
de flux. Pour ce cas, un `robots.txt` pensé pour les indexeurs bloque des sources publiques que tout navigateur lit.

C'est la seule décision de la reprise qui change un engagement public du projet.

### Ce que disent les textes et la pratique

- **RFC 9309.** « Crawlers are automated clients » ; l'exemple donné est celui des moteurs de recherche qui suivent
  les liens pour indexer. Les règles « are not a form of access authorization ». Un `robots.txt` injoignable (5xx,
  erreur réseau) impose de tout refuser ; absent (4xx), tout est permis. La RFC ne parle pas de `Crawl-delay` mais
  permet d'interpréter d'autres enregistrements. [Certain]
- **Récupérateurs déclenchés par l'utilisateur.** Google documente une catégorie de *user-triggered fetchers* qui,
  « because the fetch was requested by a user, … generally ignore robots.txt rules », avec pour exemple la lecture
  d'un flux RSS externe à la demande des utilisateurs d'un site. Le récupérateur de Feedly « ignores robots.txt
  entries », parce qu'il « behaves as a direct agent of the human user, not as a robot », et ne lit un flux qu'après
  qu'un utilisateur l'a ajouté. [Certain, pages officielles]
- **Contre-exemple.** Anthropic indique que son récupérateur `Claude-User` suit `robots.txt`. [Probable : rapporté par
  plusieurs sources secondaires, page d'origine non consultée] La pratique n'est donc pas unanime.
- **Droit de l'Union.** L'article 4 de la directive (UE) 2019/790 autorise les reproductions pour la fouille de
  textes et de données, sauf si le titulaire s'y est opposé « de manière appropriée, notamment par des procédés
  lisibles par machine » pour les contenus en ligne ; le considérant 18 cite les métadonnées et les conditions
  générales d'utilisation d'un site. En France, l'article L. 122-5-3, III, du CPI transpose cette règle ;
  l'article R. 122-28 précise que l'opposition « peut être exprimée par tout moyen », y compris des CGU. `robots.txt`
  est, en fait, le principal procédé invoqué ; une décision allemande (Hambourg, LAION c. Kneschke) a jugé qu'une
  réserve écrite dans des CGU suffisait. [Probable : textes rapportés par des sources secondaires concordantes ;
  Légifrance et EUR-Lex n'ont pas pu être lus directement le 2026-11-19]
- Conséquences juridiques [Probable, ce n'est pas un avis juridique] :
  1. passer outre un `robots.txt` qui exprime une opposition à la fouille peut priver l'administrateur de
     l'exception de fouille pour les contenus protégés ;
  2. **respecter `robots.txt` n'a jamais suffi** : une opposition peut figurer dans les CGU ou des métadonnées que
     Veilleur ne lit pas ; le mode strict actuel donnait donc une assurance trompeuse ;
  3. l'exception de fouille couvre des copies faites pour l'analyse ; la **redistribution** de contenus aux membres
     par les rapports relève d'autres règles. Dans tous les cas, c'est l'administrateur qui choisit ses sources et en
     répond.

## Options considérées

1. **Statu quo** : refus strict. Bloque des sources publiques lues à la demande d'un humain ; donne une fausse
   assurance juridique (point 2 ci-dessus).
2. **Ignorer `robots.txt`** sans le lire. Perd `Crawl-delay` (DV-04) et toute trace ; l'administrateur ne sait pas
   qu'une source s'oppose à la lecture automatisée.
3. **Passer outre avec alerte** (`warn`) par défaut, et **`enforce`** au choix de l'administrateur, par instance et
   par hôte. Le client lit toujours `robots.txt` ; la première fois qu'une collecte passe outre une règle pour un
   hôte, l'administrateur est averti.
4. Passer outre seulement pour les collecteurs « de flux » (`rss`). Arbitraire : un greffon qui lit une API publique
   est dans la même situation qu'un lecteur de flux.

## Décision

Option 3.

1. **Lecture.** Le client HTTP lit `robots.txt` une fois par jour et par origine (`scheme`, hôte, port), comme
   aujourd'hui, et l'analyse avec un **analyseur RFC 9309 propre** (règle la plus longue, `*` et `$`, groupe
   `Veilleur` sinon `*`, 500 Kio analysés au plus), qui rend la règle en cause et `Crawl-delay`. `urllib.robotparser`
   est abandonné : il applique la première règle qui correspond, pas la plus longue, et ne dit pas laquelle a joué.
2. **Politique.** Réglage `robots` : `"warn"` (défaut) ou `"enforce"`, dans `[http]` pour l'instance et dans
   `[http.hosts."<hôte>"]` pour un hôte (format commun avec l'ADR-0025). Le réglage d'un hôte prime.
3. **`warn`.** Une adresse interdite est demandée et collectée. Au **premier** cas pour un couple (collecte
   mutualisée, hôte) et une empreinte donnée de `robots.txt` (SHA-256 des octets analysés) :
   - un événement `robots_ignored` est ajouté au journal d'administration (`event`), avec la collecte, le
     collecteur, l'hôte et la règle en cause (`Disallow: <motif>`) ;
   - l'état de la collecte porte l'avertissement `robots_ignored` (mécanisme de DV-05, ADR-0027), affiché par
     `veilleur sources` tant que la règle s'applique ;
   - la notification suivante du ou des jumelages concernés compte les sources en cause (« N sources passent outre
     `robots.txt` »), sans autre détail (EF-52).
   Les cas suivants pour le même couple et la même empreinte ne réalertent pas ; un `robots.txt` modifié (nouvelle
   empreinte) qui interdit encore l'adresse réalerte. Les alertes déjà émises sont gardées en base (table dédiée,
   migration), puisque le tour est un processus neuf chaque jour.
4. **Jamais l'adresse.** Ni l'événement, ni l'avertissement, ni la notification, ni les journaux ne contiennent
   l'adresse demandée ni ses paramètres (ES-09 : elle peut porter des paramètres d'abonnement) ; seulement l'hôte, le
   collecteur, l'identifiant de collecte et la règle, tronquée à 200 caractères.
5. **`enforce`.** Comportement de 0.1.0, corrigé par l'analyseur RFC 9309 : `robots_disallowed` pour une adresse
   interdite, `robots_unavailable` pour un `robots.txt` injoignable (5xx ou panne réseau).
6. **`robots.txt` absent ou illisible** en `warn` : la collecte continue, sans alerte (aucune règle connue) ;
   `Crawl-delay` inconnu, le délai par défaut s'applique ; l'état « illisible » est gardé 1 heure avant une nouvelle
   lecture (D12), pour ne pas redemander le fichier à chaque requête.
7. **Ce qui reste dû, quelle que soit la politique** : `User-Agent` honnête avec l'adresse du serveur, délai et quota
   par hôte (ADR-0025), `Crawl-delay` (ADR-0026), `Retry-After` sur `429` et `503` (ADR-0026), garde SSRF. Aucun
   contournement d'une protection technique : `401`, `403`, `429` et toute page de défi restent des pannes
   (`http_<statut>`) ; le hors-périmètre « contournement de protections anti-robots » est inchangé.
8. **Documentation** (deux langues) : README, guide d'administration (responsabilité de l'administrateur : CGU,
   opposition à la fouille par `robots.txt`, CGU ou métadonnées, choix `enforce`), guide d'écriture d'un collecteur,
   `design.md`, modèle de menace (l'alerte ne fuit pas d'adresse), notes de version.

## Conséquences

- Engagement public modifié : la 0.2.0 l'annonce dans ses notes de version, en tête.
- Les tests existants qui attendent `robots_disallowed` et `robots_unavailable`
  (`tests/server/test_http_client.py::test_robots_txt_is_obeyed_and_read_once`,
  `::test_robots_txt_that_cannot_be_read_refuses`) sont **conservés et rattachés au mode `enforce`** ; seule leur
  configuration change, pas leurs assertions. `tests/verif/test_g3_verif.py::test_robots_txt_redirected_to_an_internal_address_is_never_fetched`
  reste valable dans les deux modes. Ce rattachement est signalé dans la PR du lot (règle : ne pas affaiblir un test
  sans le dire).
- Le port `HttpClient` vu par les greffons ne change pas ; le cœur reçoit les avertissements du client par un port
  serveur distinct (ADR-0027).
- Un administrateur qui veut le comportement de 0.1.0 écrit `robots = "enforce"` dans `[http]`.
- Risque d'image (« Veilleur ignore `robots.txt` ») : atténué par l'alerte, la documentation et le réglage, voir
  `docs/RISKS.md`.

## Sources

- RFC 9309, *Robots Exclusion Protocol*, §1, §2.2.2, §2.3.1.3, §2.3.1.4, §2.4, §2.5 —
  https://www.rfc-editor.org/rfc/rfc9309.html, consulté le 2026-11-19.
- Google, *Google user-triggered fetchers* —
  https://developers.google.com/crawling/docs/crawlers-fetchers/google-user-triggered-fetchers, consulté le 2026-11-19.
- Feedly, *Feedly Fetcher* — https://feedly.com/fetcher.html, consulté le 2026-11-19.
- Anthropic, récupérateur `Claude-User`, rapporté par https://tryrenown.com/ai-crawlers/claude-user/ et
  https://momenticmarketing.com/blog/ai-search-crawlers-bots, consultés le 2026-11-19 (page d'origine :
  https://support.claude.com/en/articles/8896518, non consultée).
- Directive (UE) 2019/790, art. 4 et considérant 18 ; CPI art. L. 122-5-3 et R. 122-28 : textes rapportés par
  https://gdroit.fr/droit-et-ia/reglement-ia/droit-auteur-donnees-entrainement/,
  https://www.testu-avocat.fr/text-and-data-mining-et-propriete-intellectuelle/ et
  https://www.legifrance.gouv.fr/codes/id/LEGISCTA000045960671/ (section R. 122-23 à R. 122-28), consultés le
  2026-11-19 ; EUR-Lex et l'article L. 122-5-3 sur Légifrance n'ont pas pu être lus directement (page vide, `403`).
- Décision de Hambourg, LAION c. Kneschke, rapportée par
  https://www.seban-associes.avocat.fr/intelligence-artificielle-et-exception-de-fouille-de-textes-et-de-donnees-une-premiere-decision-rendue-en-europe/,
  consulté le 2026-11-19.
- Essai local de `urllib.robotparser` (Python 3.12.13) : `Disallow: /a` puis `Allow: /a/b` refuse `/a/b` ; le groupe
  `*` fournit `Crawl-delay` à l'agent `Veilleur` ; un agent `X` s'applique à tout agent dont le nom contient `x`.
