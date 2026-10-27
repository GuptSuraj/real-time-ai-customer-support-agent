from typing import Literal
from pydantic import BaseModel, Field, model_validator


class LoginInput(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=200)


class CallInput(BaseModel):
    language: Literal["en", "hi"] = "en"


class VerifyInput(BaseModel):
    challenge_id: str
    code: str = Field(pattern=r"^\d{6}$")


class ActionInput(BaseModel):
    request_id: str = Field(pattern=r"^[a-zA-Z0-9-]{16,64}$")
    kind: Literal["return", "refund", "ticket"]
    order_id: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, min_length=3, max_length=1000)
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, min_length=3, max_length=3000)

    @model_validator(mode="after")
    def fields_for_kind(self):
        if self.kind in {"return", "refund"} and (not self.order_id or not self.reason):
            raise ValueError("Order and reason required")
        if self.kind == "ticket" and (not self.title or not self.description):
            raise ValueError("Title and description required")
        return self

    def payload(self):
        keys = ["title", "description"] if self.kind == "ticket" else ["order_id", "reason"]
        return {k: getattr(self, k) for k in keys}


class ReasonInput(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class DecisionInput(ReasonInput):
    decision: Literal["approve", "reject"]


class TicketUpdate(BaseModel):
    status: Literal["open", "in_progress", "resolved"]
    notes: str = Field(max_length=5000)
    assign_to_me: bool = True


class CustomerUpdate(BaseModel):
    notes: str = Field(max_length=5000)
    preferred_language: Literal["en", "hi"]


class TranscriptInput(BaseModel):
    event_id: str = Field(max_length=100)
    role: Literal["user", "assistant"]
    text: str = Field(max_length=12000)
    interrupted: bool = False


class MetricInput(BaseModel):
    name: str = Field(max_length=100)
    value: float = Field(allow_inf_nan=False)
    tags: dict = Field(default_factory=dict)


class SummaryInput(BaseModel):
    summary: str = Field(max_length=6000)


class RecordOut(BaseModel):
    id: str
    created_at: float


class UserOut(BaseModel):
    id: str
    name: str
    role: Literal["customer", "staff"]


class SessionOut(BaseModel):
    user: UserOut
    csrf: str


class CustomerOut(RecordOut):
    user_id: str
    preferred_language: Literal["en", "hi"]
    notes: str
    name: str | None = None
    email: str | None = None


class ProductOut(RecordOut):
    name: str
    description: str
    price_paise: int
    returnable: bool


class ReturnOut(RecordOut):
    order_id: str
    status: str
    reason: str


class RefundOut(RecordOut):
    order_id: str
    status: str
    amount_paise: int
    reason: str
    decided_by: str | None
    decision_reason: str
    processing_at: float | None


class ItemOut(RecordOut):
    order_id: str
    product_id: str
    quantity: int
    product: ProductOut


class EligibilityOut(BaseModel):
    eligible: bool
    reason: str


class OrderOut(RecordOut):
    customer_id: str
    status: str
    delivered_at: float | None
    total_paise: int
    items: list[ItemOut]
    return_: ReturnOut | None = Field(alias="return")
    refund: RefundOut | None
    return_eligibility: EligibilityOut


class TicketOut(RecordOut):
    customer_id: str
    call_id: str | None
    title: str
    description: str
    status: str
    assigned_to: str | None
    notes: str


class CallOut(RecordOut):
    customer_id: str
    room: str
    status: str
    language: Literal["en", "hi"]
    summary: str
    ended_at: float | None
    agent_epoch: int


class ActionResult(BaseModel):
    id: str
    kind: str
    status: str


class ActionOut(RecordOut):
    call_id: str
    kind: str
    payload: dict[str, str]
    status: str
    expires_at: float
    result: ActionResult | None


class EscalationOut(RecordOut):
    call_id: str
    status: str
    reason: str
    assigned_to: str | None
    deadline: float
    representative_connected: bool


class EscalationCustomer(BaseModel):
    id: str
    name: str


class EscalationDetail(EscalationOut):
    call: CallOut
    customer: EscalationCustomer
    verified: bool
    actions: list[ActionOut]


class TranscriptOut(RecordOut):
    call_id: str
    event_id: str
    role: str
    text: str
    interrupted: bool


class MetricOut(RecordOut):
    call_id: str
    name: str
    value: float
    tags: dict


class CallDetailOut(BaseModel):
    call: CallOut
    verified: bool
    transcripts: list[TranscriptOut]
    actions: list[ActionOut]
    escalation: EscalationOut | None
    metrics: list[MetricOut]


class ConnectionOut(BaseModel):
    call: CallOut
    url: str
    token: str
    escalation_id: str | None = None


class PortalOut(BaseModel):
    customer: CustomerOut
    orders: list[OrderOut]
    tickets: list[TicketOut]
    calls: list[CallOut]


class DashboardOut(BaseModel):
    customers: list[CustomerOut]
    tickets: list[TicketOut]
    refunds: list[RefundOut]
    returns: list[ReturnOut]
    calls: list[CallOut]
    escalations: list[EscalationDetail]


class KnowledgeSourceOut(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    source_path: str
    category: str
    version: str
    section: str
    ordinal: int
    text: str
    content_hash: str
    semantic_similarity: float | None
    rrf_score: float
    semantic_rank: int | None
    lexical_rank: int | None


class KnowledgePolicyOut(BaseModel):
    id: str
    title: str
    body: str
    created_at: float | None = None


class KnowledgeResponse(BaseModel):
    status: Literal["ready", "degraded"]
    mode: Literal["hybrid", "lexical_only", "semantic_only", "legacy", "unavailable"]
    reason: str | None = None
    index_id: str | None = None
    sources: list[KnowledgeSourceOut]
    policies: list[KnowledgePolicyOut]
    products: list[ProductOut]
    business_rules: dict
    authority: str
    latency_ms: float
    timings_ms: dict[str, float]
    no_match: bool = False
