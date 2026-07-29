"""Pydantic 请求/响应模型"""
from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime


# ========== Auth ==========
class LoginForm(BaseModel):
    username: str
    password: str


class RegisterForm(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6)
    full_name: str = Field(default="")


# ========== Company ==========
class CompanyForm(BaseModel):
    name: str = ""
    credit_code: str = ""
    legal_person: str = ""
    address: str = ""
    contact_phone: str = ""
    contact_person: str = ""
    contact_email: str = ""
    bank_info: dict = Field(default_factory=dict)
    qualifications: list = Field(default_factory=list)
    performances: list = Field(default_factory=list)
    personnel: list = Field(default_factory=list)


# ========== Bid Notices ==========
class BidNoticeForm(BaseModel):
    title: str
    source_url: str = ""
    publishing_date: Optional[str] = None
    registration_deadline: Optional[str] = None
    bid_deadline: Optional[str] = None
    bid_opening_date: Optional[str] = None
    bid_opening_location: str = ""
    budget_amount: Optional[float] = None
    bid_document_fee: Optional[float] = None
    bid_bond_amount: Optional[float] = None
    project_location: str = ""
    project_scope: str = ""
    qualification_requirements: str = ""
    platform_registration_required: bool = False
    platform_name: str = ""
    contact_person: str = ""
    contact_phone: str = ""
    contact_email: str = ""
    status: str = "new"


# ========== Bid Source ==========
class BidSourceForm(BaseModel):
    name: str
    url: str
    website_type: str = "other"
    region: str = ""
    is_active: bool = True
    scrape_config: dict = Field(default_factory=dict)
    scrape_interval_minutes: int = 60
    requires_login: bool = False
    login_username: str = ""
    login_password: str = ""


# ========== Tasks ==========
class TaskForm(BaseModel):
    title: str
    description: str = ""
    task_type: str = "custom"
    assignee_id: Optional[str] = None
    priority: str = "medium"
    planned_start: Optional[str] = None
    planned_end: Optional[str] = None
    checklist: list = Field(default_factory=list)


class TaskStatusUpdate(BaseModel):
    status: str


class TaskAssigneeUpdate(BaseModel):
    assignee_id: Optional[str] = None


class TaskChecklistUpdate(BaseModel):
    checklist: list = Field(default_factory=list)


class GenerateScheduleRequest(BaseModel):
    notice_id: str


# ========== Results ==========
class BidResultForm(BaseModel):
    notice_id: str
    opening_date: Optional[str] = None
    participant_count: Optional[int] = None
    our_quote: Optional[float] = None
    competitor_quotes: list = Field(default_factory=list)
    result: str = ""
    winning_company: str = ""
    winning_amount: Optional[float] = None
    result_url: str = ""
    contract_signed_date: Optional[str] = None
    contract_expiry_date: Optional[str] = None
    contract_amount: Optional[float] = None
    loss_reason: str = ""
    notes: str = ""


# ========== Registration ==========
class RegistrationForm(BaseModel):
    notice_id: str
    platform_name: str = ""
    platform_account: str = ""
    notes: str = ""


class RegistrationStatusUpdate(BaseModel):
    status: str
    payment_status: str = "unpaid"
    payment_amount: Optional[float] = None
