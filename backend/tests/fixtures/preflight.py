"""Preflight documents for the spec 009 tests.

``INTENT_TEMPLATE`` is the Preflight skill's ``templates/intent.yaml`` (schema
version 1) as shipped on 2026-11-25, copied verbatim: the round trip through
Batchivo must give back exactly what ``yaml.safe_load`` reads from it.
"""

INTENT_TEMPLATE = """\
# Fiche d'intention Préflight (schema_version 1).
# Statuts d'une valeur : déduit (image/géométrie) | estimée (cote sur photo) | validé (confirmé) | mesurée (pied à coulisse).
# Inconnu : "[À PRÉCISER]". Aucune valeur inventée.
schema_version: 1
slug: "[À PRÉCISER]"
function: "[À PRÉCISER]"                 # ce que fait la pièce, en une phrase
category: "[À PRÉCISER]"                 # support | crochet | clip | boîtier | adaptateur | pièce de rechange | décoratif | jouet | autre
images: []                               # chemins dans work/<slug>/images/
loads:
  - value: "[À PRÉCISER]"
    unit: kg                             # kg | N
    direction: "[À PRÉCISER]"            # ex. "vers le bas, au bout du crochet, perpendiculaire à l'appuie-tête"
    duration: "[À PRÉCISER]"             # permanent | cyclic | shock | short
    cycles: null                         # si cyclic
    status: déduit
environment:
  max_temp_c: "[À PRÉCISER]"
  max_temp_source: "[À PRÉCISER]"        # ex. règle env.car.dashboard, ou mesure
  outdoor: false
  uv: false
  humidity: false
  chemicals: null
  food_contact_claimed: false
  children: false
  safety_critical: false                 # la rupture peut-elle blesser quelqu'un ?
  status: déduit
interfaces:
  - neighbour: "[À PRÉCISER]"            # ex. "tige d'appuie-tête Ø 14 mm"
    fit: "[À PRÉCISER]"                  # slide | press | snap | screw | insert | print-in-place | none
    dimensions_mm: {}
    status: estimée
quantity: 1
selling: false
sales_channel: none                      # etsy | makerworld | shop | none
country: "[À PRÉCISER]"
eu: true
third_party_model: false
third_party_license: null                # ex. cc-by, cc-by-nc, makerworld-standard
alternatives: "[À PRÉCISER]"             # produit du commerce ? autre procédé ?
success_criteria:
  - "[À PRÉCISER]"                       # mesurable, ex. "tient 5 kg 24 h à 70 °C sans déformation visible"
"""

#: A filled intent: a car headrest bag hook (the skill's reference part).
FILLED_INTENT = {
    "schema_version": 1,
    "slug": "porte-sac",
    "function": "Tient un sac de courses à l'appuie-tête",
    "category": "crochet",
    "images": [],
    "loads": [
        {
            "value": 5,
            "unit": "kg",
            "direction": "vers le bas, au bout du crochet",
            "duration": "cyclic",
            "cycles": 2000,
            "status": "validé",
        }
    ],
    "environment": {"max_temp_c": 80, "max_temp_source": "env.car.dashboard", "status": "validé"},
    "interfaces": [
        {
            "neighbour": "tige Ø 14 mm",
            "fit": "snap",
            "dimensions_mm": {"d": 14},
            "status": "mesurée",
        }
    ],
    "quantity": 2,
    "selling": True,
    "sales_channel": "etsy",
    "country": "FR",
    "eu": True,
    "success_criteria": ["tient 5 kg 24 h à 70 °C"],
    "x_custom": {"kept": True},
}
