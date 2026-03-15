# PyCowLog Django V5 — Django 6.0.3

Application Django inspirée de CowLog avec une montée en gamme vers des usages proches de BORIS pour le codage comportemental vidéo.

## Ce que la V5 ajoute

- contrôle image par image avec pas configurable par session
- annotations horodatées indépendantes des événements
- import d’observations JSON V5
- export TSV tabulaire
- export JSON enrichi avec statistiques, intégrité et pistes
- export JSON **BORIS-like** simplifié
- contrôle d’intégrité des états `START/STOP`
- calcul d’intervalles entre événements par comportement
- timeline globale par buckets + timeline par pistes comportementales
- export Excel enrichi avec feuilles `Events`, `Annotations`, `Summary`, `Intervals`, `Integrity`, `Timeline`

## Fonctionnalités existantes conservées

- authentification Django
- projets privés avec collaborateurs
- catégories, comportements et modificateurs
- comportements `point` et `state`
- événements `POINT`, `START`, `STOP`
- modificateurs activables au clavier
- édition/suppression des catégories, modificateurs, comportements, vidéos et sessions
- sessions multi-vidéo synchronisées
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

## Workflow recommandé

1. Créer un compte ou se connecter.
2. Créer un projet.
3. Ajouter les catégories, comportements et modificateurs.
4. Ajouter une ou plusieurs vidéos.
5. Créer une session.
6. Ouvrir le lecteur V5.
7. Coder au clavier ou à la souris.
8. Ajouter des annotations rapides avec `E`.
9. Vérifier l’intégrité des états et les intervalles.
10. Exporter en CSV, TSV, JSON, BORIS-like JSON ou XLSX.

## Raccourcis du lecteur

- `touche comportement` : création d’événement
- `Alt + touche comportement` : forcer `START`
- `Shift + touche comportement` : forcer `STOP`
- `touche modificateur` : active/désactive un modificateur
- `Backspace` : vide les modificateurs actifs
- `Space` : lecture / pause
- `E` : ajouter une annotation à la position courante

## Formats d’export/import

### Session

- CSV
- TSV
- JSON V5
- JSON BORIS-like simplifié
- XLSX enrichi

### Projet

- XLSX consolidé
- éthogramme JSON

## Portée BORIS

Cette V5 reprend **plusieurs fonctions majeures inspirées de BORIS** : journalisation vidéo, codage clavier, états/points, analyse d’intervalles, time budget simple, vérification d’intégrité, export tabulaire et export JSON structuré.

En revanche, ce projet **n’est pas un clone exhaustif de BORIS** : les observations live complètes, la gestion avancée des sujets, les plugins, les spectrogrammes, tous les formats historiques d’export et l’ensemble des outils analytiques BORIS ne sont pas reproduits ici.

## Structure

```text
PyCowLog/
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
- `SessionAnnotation`
