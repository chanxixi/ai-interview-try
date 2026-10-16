"""技能归一化：简历原文 → 规范技能名。

    `document.cleaner` → `skill.normalizer` → `match.matcher`

单独一组是因为「技能词典」是独立领域：`skills.yaml` 的别名、分类、去重规则
全在这一层，它不关心文本怎么来的，也不关心分数怎么算。
"""
