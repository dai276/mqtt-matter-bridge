"""Small stdlib fallback classifier with sklearn-like predict/predict_proba."""

from __future__ import annotations

import math
from typing import Any


class SimpleCentroidClassifier:
    def __init__(self) -> None:
        self.classes_: list[int] = []
        self.centroids: dict[int, list[float]] = {}
        self.priors: dict[int, float] = {}

    def fit(self, X: list[list[float]], y: list[Any]) -> SimpleCentroidClassifier:
        self.classes_ = sorted(set(int(v) for v in y))
        n = len(y)
        
        for c in self.classes_:
            rows = [X[i] for i, v in enumerate(y) if int(v) == c]
            self.priors[c] = len(rows) / n
            self.centroids[c] = [sum(float(x) for x in col) / len(rows) for col in zip(*rows)]
            
        return self

    def predict(self, X: list[list[float]]) -> list[int]:
        return [
            self.classes_[max(range(len(p)), key=lambda i: p[i])]
            for p in self.predict_proba(X)
        ]

    def predict_proba(self, X: list[list[float]]) -> list[list[float]]:
        out: list[list[float]] = []
        
        for row in X:
            scores: list[float] = []
            for c in self.classes_:
                dist = math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(row, self.centroids[c])))
                scores.append(self.priors[c] / (1.0 + dist))
            
            total = sum(scores) or 1.0
            out.append([s / total for s in scores])
            
        return out