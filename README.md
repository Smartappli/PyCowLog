# PyCowLog Django V4 — Django 6.0.3

Application Django inspirée de CowLog, prête à exécuter, avec une interface multi-utilisateur pour le codage comportemental à partir de vidéos.

## Nouveautés de la V4

- authentification Django
- projets privés avec collaborateurs
- catégories, comportements et modificateurs
- comportements `point` et `state`
- événements `POINT`, `START`, `STOP`
- modificateurs activables au clavier
- édition et suppression des catégories, modificateurs, comportements, vidéos et sessions depuis l’interface
- sessions multi-vidéo synchronisées
- timeline dynamique par buckets d’une minute
- statistiques automatiques par comportement avec pourcentage d’occupation
- export CSV, JSON et Excel (`.xlsx`) par session
- export Excel consolidé au niveau projet
- import/export d’éthogrammes au format JSON
- interface admin

## Stack

- Django 6.0.3
- SQLite par défaut
- openpyxl pour les exports Excel
- stockage local des médias

## Compatibilité Python

Prévois Python 3.12+ pour rester aligné avec Django 6.0.x.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# ou
.venv\Scripts\activate   # Windows PowerShell

python -m pip install --upgrade pip
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Accès

- Application : http://127.0.0.1:8000/
- Admin : http://127.0.0.1:8000/admin/
- Connexion : http://127.0.0.1:8000/accounts/login/

## Workflow recommandé

1. Créer un compte ou se connecter.
2. Créer un projet.
3. Ajouter les catégories, comportements et modificateurs de l’éthogramme.
4. Ajouter une ou plusieurs vidéos.
5. Créer une session en choisissant une vidéo principale et éventuellement des vidéos secondaires synchronisées.
6. Ouvrir le lecteur.
7. Utiliser les raccourcis clavier pour enregistrer les événements.
8. Modifier ou supprimer les événements si nécessaire.
9. Consulter les statistiques et la timeline.
10. Exporter les données en CSV, JSON ou Excel.
11. Exporter le projet complet en Excel ou l’éthogramme en JSON.

## Types d'événements

### `point`

Événement ponctuel, par exemple :
- toux
- coup de tête
- vocalisation

Une pression sur la touche enregistre directement un événement `POINT`.

### `state`

Événement avec durée, par exemple :
- alimentation
- couchage
- rumination

Une pression sur la touche alterne automatiquement entre `START` et `STOP`.

## Raccourcis disponibles dans le lecteur

- `touche comportement` : toggle automatique
- `Alt + touche comportement` : forcer `START`
- `Shift + touche comportement` : forcer `STOP`
- `touche modificateur` : active/désactive un modificateur
- `Backspace` : vide les modificateurs actifs
- `Space` : lecture / pause
- clic sur un temps d’événement : repositionne la vidéo
- clic sur une barre de timeline : saute au début du bucket

## Multi-vidéo synchronisée

La V4 garde une vidéo principale et permet d’ajouter des vidéos secondaires à la session.
Toutes les vidéos sont synchronisées avec le lecteur principal :

- lecture / pause
- seek temporel
- vitesse de lecture

## Import / export d’éthogrammes

La V4 exporte la structure d’un projet au format JSON :

- catégories
- modificateurs
- comportements
- couleurs, ordres d’affichage, modes et raccourcis clavier

L’import supporte deux modes :

- ajout / mise à jour
- remplacement complet, uniquement si le projet ne contient pas encore de sessions ni d’événements

## Statistiques calculées

Dans le lecteur, dans les exports de session et dans l’export projet, la V4 calcule :

- nombre total d’événements
- nombre d’événements ponctuels
- nombre d’états ouverts
- nombre de segments par comportement
- durée totale par comportement de type `state`
- pourcentage d’occupation par comportement de type `state`
- résumé agrégé par session et par comportement au niveau du projet

## Structure

```text
cowlog_django_v4_6_0_3/
├── config/
├── tracker/
├── templates/
├── static/
├── manage.py
└── requirements.txt
```

## Modèle de données

- `Project`
- `BehaviorCategory`
- `Behavior`
- `Modifier`
- `VideoAsset`
- `ObservationSession`
- `SessionVideoLink`
- `ObservationEvent`

## Notes

- Les médias sont stockés localement dans `media/`.
- Les collaborateurs peuvent créer, modifier et supprimer leurs sessions et coder des événements.
- Le propriétaire garde la main sur la configuration du projet, les vidéos et l’import d’éthogrammes.
- La timeline et les statistiques sont recalculées automatiquement à chaque rafraîchissement de la session.
