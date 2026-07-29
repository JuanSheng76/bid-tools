"""数据库模型 — 7 张表"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Float, Boolean, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from database import Base


def gen_id():
    return str(uuid.uuid4())


def now():
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=gen_id)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(200), unique=True, nullable=True)
    password_hash = Column(String(200), nullable=False)
    full_name = Column(String(100), nullable=False, default="")
    role = Column(String(20), nullable=False, default="staff")  # admin / staff
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)

    # 关联
    assigned_tasks = relationship("Task", back_populates="assignee", foreign_keys="Task.assignee_id")


class Company(Base):
    __tablename__ = "company"

    id = Column(String(36), primary_key=True, default=gen_id)
    name = Column(String(200), nullable=False, default="")
    credit_code = Column(String(50), default="")
    legal_person = Column(String(100), default="")
    address = Column(Text, default="")

    # JSON 数组
    qualifications = Column(JSON, default=list)   # [{name, level, cert_no, issuing_authority, issue_date, expiry_date, is_permanent}]
    performances = Column(JSON, default=list)      # [{project_name, project_type, contract_amount, client_name, contract_date, description}]
    personnel = Column(JSON, default=list)         # [{name, position, certifications, phone, email}]
    bank_info = Column(JSON, default=dict)         # {bank_name, account_no, tax_no}

    contact_phone = Column(String(20), default="")
    contact_person = Column(String(50), default="")
    contact_email = Column(String(200), default="")

    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)


class BidSource(Base):
    __tablename__ = "bid_sources"

    id = Column(String(36), primary_key=True, default=gen_id)
    name = Column(String(200), nullable=False)
    url = Column(String(500), nullable=False)
    website_type = Column(String(50), default="other")  # government_procurement / public_resource / enterprise / pv_industry / other
    region = Column(String(100), default="")
    is_active = Column(Boolean, default=True)
    scrape_config = Column(JSON, default=dict)  # {list_url, fields, detail_fields, pagination, use_playwright}
    scrape_interval_minutes = Column(Integer, default=60)
    requires_login = Column(Boolean, default=False)
    login_username = Column(String(200), default="")
    login_password = Column(String(200), default="")
    last_scraped_at = Column(DateTime, nullable=True)
    last_status = Column(String(20), default="")  # success / partial / failed
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    notices = relationship("BidNotice", back_populates="source")


class BidNotice(Base):
    __tablename__ = "bid_notices"

    id = Column(String(36), primary_key=True, default=gen_id)
    source_id = Column(String(36), ForeignKey("bid_sources.id"), nullable=True)
    source_url = Column(String(1000), default="")
    external_id = Column(String(200), default="")
    title = Column(String(500), nullable=False, default="")

    publishing_date = Column(DateTime, nullable=True)
    registration_deadline = Column(DateTime, nullable=True)
    bid_deadline = Column(DateTime, nullable=True)
    bid_opening_date = Column(DateTime, nullable=True)
    bid_opening_location = Column(String(500), default="")

    budget_amount = Column(Float, nullable=True)          # 万元
    bid_document_fee = Column(Float, nullable=True)       # 元
    bid_bond_amount = Column(Float, nullable=True)        # 万元

    project_location = Column(String(300), default="")
    project_scope = Column(Text, default="")
    qualification_requirements = Column(Text, default="")  # 原始文本
    platform_registration_required = Column(Boolean, default=False)
    platform_name = Column(String(200), default="")

    contact_person = Column(String(100), default="")
    contact_phone = Column(String(50), default="")
    contact_email = Column(String(200), default="")

    raw_content = Column(Text, default="")

    # 状态流转: new → assessing → worth/not_worth → registered → bidding → completed / ignored
    status = Column(String(20), nullable=False, default="new")
    bid_decision = Column(String(20), nullable=True)  # bid / no_bid — 手动决策（独立于评估分数）
    abandon_reason = Column(Text, default="")          # 放弃投标原因（决定投标后又放弃时填写）
    is_manual = Column(Boolean, default=False)

    # 评估结果（内嵌 JSON）
    assessment = Column(JSON, nullable=True)
    # {total_score, qual_score, perf_score, personnel_score, financial_score, other_score,
    #  recommendation, risk_notes, missing_requirements, assessed_at}

    # 招标文件解析结果（内嵌 JSON）
    tender_analysis = Column(JSON, nullable=True)
    # {file_name, file_stored_at, parsed_at, parse_version,
    #  qualification_requirements, scoring_criteria, recommendations, important_notes}

    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    source = relationship("BidSource", back_populates="notices")
    registrations = relationship("Registration", back_populates="notice")
    tasks = relationship("Task", back_populates="notice")
    result = relationship("BidResult", back_populates="notice", uselist=False)


class Registration(Base):
    __tablename__ = "registrations"

    id = Column(String(36), primary_key=True, default=gen_id)
    notice_id = Column(String(36), ForeignKey("bid_notices.id"), nullable=False)

    status = Column(String(20), default="pending")  # pending / submitted / confirmed / rejected
    form_data = Column(JSON, default=dict)
    platform_name = Column(String(200), default="")
    platform_account = Column(String(200), default="")
    payment_status = Column(String(20), default="unpaid")  # unpaid / paid
    payment_amount = Column(Float, nullable=True)
    notes = Column(Text, default="")

    submitted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    notice = relationship("BidNotice", back_populates="registrations")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=gen_id)
    notice_id = Column(String(36), ForeignKey("bid_notices.id"), nullable=False)

    title = Column(String(300), nullable=False)
    description = Column(Text, default="")
    task_type = Column(String(50), nullable=False)
    # get_docs / qualifications / pricing / certs / writing / format / stamp / custom

    assignee_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    status = Column(String(20), default="todo")  # todo / in_progress / done
    priority = Column(String(10), default="medium")  # low / medium / high / urgent

    planned_start = Column(DateTime, nullable=True)
    planned_end = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    sort_order = Column(Integer, default=0)
    checklist = Column(JSON, default=list)  # [{text: "...", done: false}]

    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    notice = relationship("BidNotice", back_populates="tasks")
    assignee = relationship("User", back_populates="assigned_tasks", foreign_keys=[assignee_id])


class BidResult(Base):
    __tablename__ = "bid_results"

    id = Column(String(36), primary_key=True, default=gen_id)
    notice_id = Column(String(36), ForeignKey("bid_notices.id"), nullable=False, unique=True)

    # 开标信息
    opening_date = Column(DateTime, nullable=True)
    participant_count = Column(Integer, nullable=True)
    our_quote = Column(Float, nullable=True)
    competitor_quotes = Column(JSON, default=list)  # [{company, quote}]

    # 结果信息
    result = Column(String(20), default="")  # won / lost / rejected / cancelled
    winning_company = Column(String(300), default="")
    winning_amount = Column(Float, nullable=True)
    result_url = Column(String(1000), default="")

    # 合同信息
    contract_signed_date = Column(DateTime, nullable=True)
    contract_expiry_date = Column(DateTime, nullable=True)
    contract_amount = Column(Float, nullable=True)

    loss_reason = Column(Text, default="")
    notes = Column(Text, default="")

    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    notice = relationship("BidNotice", back_populates="result")
