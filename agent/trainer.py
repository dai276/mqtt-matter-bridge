"""
trainer.py — Train DecisionTree, lưu model + metadata

Chạy: python agent/trainer.py
"""

import sys
import json
import pickle
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.feature_engineering import build_full_dataset, get_feature_columns
from agent.db import init_db

from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix

PROJECT_ROOT = Path(__file__).parent.parent
MODEL_PATH   = PROJECT_ROOT / "models" / "decision_tree.pkl"
META_PATH    = PROJECT_ROOT / "models" / "decision_tree_meta.json"
ENTITIES     = ["light.bedroom", "light.living_room", "switch.fan_bedroom"]


def train() -> None:
    init_db()

    # ── Load dataset ──────────────────────────────────────────────────────────
    print("[trainer] Building dataset...")
    df = build_full_dataset()

    if df.empty:
        print("[trainer] Không có data. Chạy data_generator.py trước.")
        return

    feat_cols = get_feature_columns()
    missing   = [c for c in feat_cols if c not in df.columns]
    if missing:
        print(f"[trainer] Thiếu cột: {missing}")
        return

    X = df[feat_cols].values
    y = df["label"].values

    pos = int(y.sum())
    neg = int((y == 0).sum())
    print(f"[trainer] Dataset: {len(y)} samples  (+{pos} / -{neg})")

    # ── Train / test split ────────────────────────────────────────────────────
    # stratify nếu cả 2 class đều có đủ sample
    stratify = y if (pos >= 2 and neg >= 2) else None
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=stratify
    )

    # ── Train ─────────────────────────────────────────────────────────────────
    model = DecisionTreeClassifier(
        max_depth=5,
        random_state=42,
        class_weight="balanced",
    )
    model.fit(X_train, y_train)
    print(f"[trainer] Trained on {len(X_train)} samples")

    # ── Evaluate ──────────────────────────────────────────────────────────────
    y_pred = model.predict(X_test)

    print("\n=== Classification Report ===")
    print(classification_report(y_test, y_pred,
                                 target_names=["no_action", "turn_on"],
                                 zero_division=0))

    print("=== Confusion Matrix ===")
    cm = confusion_matrix(y_test, y_pred)
    print(f"  TN={cm[0,0]}  FP={cm[0,1]}")
    print(f"  FN={cm[1,0]}  TP={cm[1,1]}")

    print("\n=== Decision Tree Rules (cho báo cáo) ===")
    print(export_text(model, feature_names=feat_cols, max_depth=3))

    # ── Lưu model ─────────────────────────────────────────────────────────────
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)
    print(f"[trainer] Model saved → {MODEL_PATH}")

    meta = {
        "model_type":      "DecisionTreeClassifier",
        "max_depth":       5,
        "trained_at":      datetime.now().isoformat(),
        "feature_columns": feat_cols,
        "dataset_size":    len(y),
        "positive_count":  pos,
        "negative_count":  neg,
        "entities":        ENTITIES,
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"[trainer] Metadata saved → {META_PATH}")


if __name__ == "__main__":
    train()