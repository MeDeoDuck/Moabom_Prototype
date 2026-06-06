"""v3 영상선정 coarse 클러스터링 (설계 §3 [5][6][7], PR2 shadow).

lang_normalize → embed → coarse_cluster(KMeans) → llm_cluster_shortlist.
shadow 단계라 v1 반환을 바꾸지 않고 결과를 metrics_json 에만 기록한다.
"""
