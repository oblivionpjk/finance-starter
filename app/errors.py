"""系统级结构化错误：带错误码，便于前端给出可读原因。"""


class AnalysisError(Exception):
    def __init__(self, code: str, message: str, detail: str = "",
                 data: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
        self.data = data
