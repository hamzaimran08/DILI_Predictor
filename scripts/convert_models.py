"""One-off conversion of the scikit-learn 1.1.1 model pickles to the current tree format.

scikit-learn >= 1.3 added a ``missing_go_to_left`` field to the tree node array and refuses to
unpickle older trees. scikit-learn >= 1.4 also stores classifier leaf values as class proportions
instead of weighted counts (SHAP relies on this). This script patches both while unpickling and
re-saves every model, so the app can run on current scikit-learn without retraining.

Usage: python scripts/convert_models.py models/
"""

import pickle
import sys
from pathlib import Path

import numpy as np
from numpy.lib import recfunctions as rfn
from sklearn.tree._tree import Tree


class LegacyTreeUnpickler(pickle._Unpickler):
    def load_build(self):
        state = self.stack[-1]
        inst = self.stack[-2]
        if isinstance(inst, Tree) and isinstance(state, dict):
            nodes = state["nodes"]
            if "missing_go_to_left" not in nodes.dtype.names:
                # Trees from scikit-learn < 1.3 never route missing values, so 0 keeps behaviour identical.
                state["nodes"] = rfn.append_fields(
                    nodes, "missing_go_to_left", np.zeros(len(nodes), dtype=np.uint8), usemask=False
                )
            if self.is_classifier:
                values = state["values"]
                totals = values.sum(axis=2, keepdims=True)
                state["values"] = np.divide(values, totals, out=np.zeros_like(values), where=totals != 0)
        super().load_build()

    dispatch = pickle._Unpickler.dispatch.copy()
    dispatch[pickle.BUILD[0]] = load_build


RENAMED_ATTRS = {"base_estimator": "estimator", "base_estimator_": "estimator_"}


def upgrade_params(est) -> None:
    """Rename attributes renamed since 1.1.1 and add constructor params introduced since, at their defaults.

    These are all training-time settings; none of them change how a fitted tree predicts.
    """
    for old, new in RENAMED_ATTRS.items():
        if old in vars(est):
            value = vars(est).pop(old)
            if not hasattr(est, new):
                setattr(est, new, value)
    if getattr(est, "max_features", None) == "auto":  # removed in 1.3; "auto" meant "sqrt" (clf) / 1.0 (reg)
        est.max_features = "sqrt" if "Classifier" in type(est).__name__ else 1.0
    for name, default in type(est)().get_params(deep=False).items():
        if name not in vars(est):
            setattr(est, name, default)


def convert(path: Path) -> None:
    raw = path.read_bytes()
    with path.open("rb") as fh:
        unpickler = LegacyTreeUnpickler(fh)
        unpickler.is_classifier = b"Classifier" in raw
        model = unpickler.load()
    for est in [model, *model.estimators_]:
        upgrade_params(est)
    with path.open("wb") as fh:
        pickle.dump(model, fh, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"converted {path.name}: {type(model).__name__}, {len(model.estimators_)} trees")


if __name__ == "__main__":
    for model_path in sorted(Path(sys.argv[1]).glob("*.sav")):
        convert(model_path)
