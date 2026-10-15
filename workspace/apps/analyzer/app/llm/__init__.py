"""LLM 集成层（M4.4）。

`prompts.py` 只放提示词，`client.py` 只放传输与降级 —— 分开是因为两者的变更原因不同：
改措辞只动 prompts，换网关/改超时只动 client。
"""
