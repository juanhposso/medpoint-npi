from pydantic import BaseModel
from zmq import Enum

class MatchVerdict(str, Enum):
    MATCH = "MATCH"
    REVIEW = "REVIEW"
    NO_MATCH = "NO_MATCH"

class MatchResult(BaseModel):
    npi_name: str
    dca_name: str
    score: float
    verdict: MatchVerdict