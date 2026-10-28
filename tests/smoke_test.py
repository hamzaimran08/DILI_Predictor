"""Regression check: run the full prediction pipeline headlessly and compare with known-good results.

expected_predictions.json was produced by the original image (Python 3.10, scikit-learn 1.1.1,
shap 0.42), so this guards against dependency upgrades silently changing predictions.

Usage (from the app directory): python tests/smoke_test.py
"""

import importlib.util
import json
import math
import sys
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

TOLERANCE = 1e-9
SMILES = {
    "paracetamol": "CC(=O)NC1=CC=C(O)C=C1",
    "aspirin": "CC(=O)OC1=CC=CC=C1C(O)=O",
    "diclofenac": "OC(=O)CC1=CC=CC=C1NC1=C(Cl)C=CC=C1Cl",
    "ibuprofen": "CC(C)CC1=CC=C(C=C1)C(C)C(O)=O",
    "troglitazone": "CC1=C(C)C2=C(CCC(C)(COC3=CC=C(CC4SC(=O)NC4=O)C=C3)O2)C(C)=C1O",
}

spec = importlib.util.spec_from_file_location("page", "pages/Submit single SMILES.py")
page = importlib.util.module_from_spec(spec)
spec.loader.exec_module(page)

expected = json.loads((Path(__file__).parent / "expected_predictions.json").read_text())
failures = []
for name, smiles in SMILES.items():
    data = pd.DataFrame({"smiles_r": [page.standardized_smiles(smiles)]})
    data = page.predict_liv_all(page.calc_all_fp_desc(data))
    interpret, proba, pred = page.predict_DILI(data)
    got = {
        "proba": float(proba[0]),
        "pred": int(pred[0]),
        "cmax_u": float(data["median pMolar unbound plasma concentration"][0]),
        "shap_sum": float(interpret["SHAP"].sum()),
        **{f"proxy_{k}": float(data[k][0]) for k in page.liv_data},
    }
    want = {k: v for k, v in expected[name].items() if k != "proxy"}
    want.update({f"proxy_{k}": v for k, v in expected[name]["proxy"].items()})
    for key, value in want.items():
        # expected cmax/proxy/shap values were stored rounded to 6 decimals
        tol = TOLERANCE if key in ("proba", "pred") else 5e-7
        if not math.isclose(got[key], value, abs_tol=tol):
            failures.append(f"{name}.{key}: expected {value}, got {got[key]}")
    print(f"{name:13} pred={got['pred']} proba={got['proba']:.6f}")

if failures:
    print("FAILED:\n  " + "\n  ".join(failures))
    sys.exit(1)
print(f"OK: {len(SMILES)} molecules match the reference predictions")
