"""저장 계약에서 발생하는 도메인 오류."""


class StaleStateError(ValueError):
    """판단 당시 상태가 현재 상태와 다르다."""


class InvalidProposalError(ValueError):
    """입력 판단이 JSON 또는 증거 계약을 위반한다."""
