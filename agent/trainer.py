"""Train Phase 1 model. Uses sklearn if available, otherwise a stdlib nearest-centroid classifier."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import pickle
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.db import init_db
from agent.device_registry import registry_hash
from agent.feature_engineering import LABELS, build_full_dataset, feature_metadata, get_feature_columns
from agent.simple_model import SimpleCentroidClassifier

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_MODEL_PATH = PROJECT_ROOT / 'models' / 'decision_tree.pkl'
DEFAULT_META_PATH = PROJECT_ROOT / 'models' / 'decision_tree_meta.json'


def _split(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Sort rows chronologically by t_observe and perform a 75/25 split."""
    rows = sorted(rows, key=lambda r: r.get('t_observe', ''))
    idx = max(1, min(len(rows) - 1, int(len(rows) * 0.75)))
    return rows[:idx], rows[idx:]


def _metrics(y_true: list[int], y_pred: list[int]) -> dict[str, Any]:
    """Calculate classification metrics (accuracy, precision, recall, F1) and confusion matrix."""
    labels = list(range(len(LABELS)))
    cm = [[0 for _ in labels] for _ in labels]
    
    for t, p in zip(y_true, y_pred):
        cm[int(t)][int(p)] += 1
        
    acc = sum(1 for t, p in zip(y_true, y_pred) if int(t) == int(p)) / max(1, len(y_true))
    f1s = []
    
    for c in labels:
        tp = cm[c][c]
        fp = sum(cm[r][c] for r in labels if r != c)
        fn = sum(cm[c][r] for r in labels if r != c)
        
        prec = tp / (tp + fp) if tp + fp else 0
        rec = tp / (tp + fn) if tp + fn else 0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
        f1s.append(f1)
        
    return {
        'accuracy': acc,
        'precision': acc,
        'recall': acc,
        'f1': sum(f1s) / len(f1s),
        'confusion_matrix': cm,
        'labels': LABELS,
        'test_size': len(y_true)
    }


def train(seed: int = 42, max_depth: int = 5, model_out: str | None = None) -> None:
    init_db()
    print('[trainer] Building dataset...')
    rows = build_full_dataset(seed=seed)
    
    if not rows:
        raise SystemExit('[trainer] Không có data. Chạy data_generator.py trước.')
        
    feat_cols = get_feature_columns()
    counts: dict[str, int] = {}
    for r in rows:
        counts[r['label_name']] = counts.get(r['label_name'], 0) + 1
        
    if len(counts) < 2:
        raise SystemExit(f'[trainer] Dataset cần ít nhất 2 class, hiện có: {counts}')
        
    if len(rows) < 20:
        raise SystemExit(f'[trainer] Dataset quá nhỏ ({len(rows)} rows).')
        
    train_rows, test_rows = _split(rows)
    X_train = [[r[c] for c in feat_cols] for r in train_rows]
    y_train = [r['label'] for r in train_rows]
    X_test = [[r[c] for c in feat_cols] for r in test_rows]
    y_test = [r['label'] for r in test_rows]
    
    if importlib.util.find_spec('sklearn') is not None:
        from sklearn.tree import DecisionTreeClassifier
        model = DecisionTreeClassifier(max_depth=max_depth, random_state=seed, class_weight='balanced')
        model.fit(X_train, y_train)
        model_type = 'DecisionTreeClassifier'
    else:
        model = SimpleCentroidClassifier()
        model.fit(X_train, y_train)
        model_type = 'SimpleCentroidClassifier'
        
    y_pred = model.predict(X_test)
    metrics = _metrics(y_test, y_pred)
    
    print(f"[trainer] Dataset: {len(rows)} samples {counts}")
    print(f"[trainer] Time split: train={len(train_rows)} test={len(test_rows)}")
    print(f"[trainer] metrics: accuracy={metrics['accuracy']:.3f} f1={metrics['f1']:.3f} model={model_type}")
    
    model_path = Path(model_out) if model_out else DEFAULT_MODEL_PATH
    meta_path = model_path.with_name(model_path.stem + '_meta.json') if model_out else DEFAULT_META_PATH
    model_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(model_path, 'wb') as f:
        pickle.dump(model, f)
        
    meta = {
        'model_type': model_type,
        'max_depth': max_depth,
        'trained_at': datetime.now().isoformat(),
        'seed': seed,
        'feature_columns': feat_cols,
        'label_mapping': {l: i for i, l in enumerate(LABELS)},
        'id_to_label': {str(i): l for i, l in enumerate(LABELS)},
        'classes_': [int(c) for c in model.classes_],
        'dataset_size': len(rows),
        'label_counts': counts,
        'metrics': metrics,
        'device_registry_hash': registry_hash(),
        **feature_metadata()
    }
    
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        
    print(f'[trainer] Model saved → {model_path}')
    print(f'[trainer] Metadata saved → {meta_path}')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--max-depth', type=int, default=5)
    p.add_argument('--model-out', default=None)
    a = p.parse_args()
    train(seed=a.seed, max_depth=a.max_depth, model_out=a.model_out)