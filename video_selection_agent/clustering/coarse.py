"""coarse_cluster (설계 §4 [6]).

정규화 텍스트 임베딩 → KMeans k=5(seed 고정). 클러스터는 "관점 정답"이 아니라
자막 fetch 예산 배분 + 중복 완화 장치(설계 §5). 후보 < k 면 k 를 줄인다.

sklearn 은 함수 내부 lazy import — 오프라인 테스트·prod 정상경로(shadow off)에
scipy/numpy 를 끌어오지 않게(NR-007 의존성 정책). 설계 §5 에서 KMeans 도입 합의.
"""
from __future__ import annotations

DEFAULT_K = 5
_SEED = 42


def kmeans_labels(vectors: list[list[float]], k: int = DEFAULT_K) -> tuple[list[int], dict]:
    """벡터 → 군집 라벨(입력 순서 정렬) + meta.

    반환: (labels, meta{k_effective, cluster_sizes})
    n<=1 또는 k<=1 이면 전부 라벨 0.
    """
    n = len(vectors)
    if n == 0:
        return [], {"k_effective": 0, "cluster_sizes": {}}
    k_eff = max(1, min(k, n))
    if k_eff == 1:
        return [0] * n, {"k_effective": 1, "cluster_sizes": {0: n}}

    from sklearn.cluster import KMeans  # lazy

    km = KMeans(n_clusters=k_eff, random_state=_SEED, n_init=10)
    labels = km.fit_predict(vectors).tolist()
    labels = [int(x) for x in labels]

    sizes: dict[int, int] = {}
    for lbl in labels:
        sizes[lbl] = sizes.get(lbl, 0) + 1
    return labels, {"k_effective": k_eff, "cluster_sizes": sizes}
