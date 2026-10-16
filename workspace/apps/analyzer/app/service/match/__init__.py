"""匹配与推荐：加权覆盖率打分 + TopN 推荐。

`recommender` 消费 `matcher` 产出的 `MatchReport`，两者共用同一套打分口径
（`util.rounding` 的 `round_half_up`），所以放一组 —— 改打分公式时两处都要复核，
放在一起不容易漏。
"""
