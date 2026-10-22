# models.py
from sqlalchemy import Column, Integer, String, Float, ForeignKey, Table, Boolean, DateTime, Text
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

profile_queries = Table(
    "profile_queries", Base.metadata,
    Column("profile_id", Integer, ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True),
    Column("query_id", Integer, ForeignKey("saved_queries.id", ondelete="CASCADE"), primary_key=True)
)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)

class DataSource(Base):
    __tablename__ = "datasources"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    url = Column(String(500), nullable=False)
    ds_type = Column(String(50), default="prometheus")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    owner = relationship("User")

class SavedQuery(Base):
    __tablename__ = "saved_queries"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    promql = Column(String, nullable=False)
    condition_min = Column(Float, nullable=True)
    condition_max = Column(Float, nullable=True)
    step = Column(String(50), default="60s")
    description = Column(String(1000), nullable=True) 
    datasource_id = Column(Integer, ForeignKey("datasources.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    owner = relationship("User", backref="queries")
    datasource = relationship("DataSource")

class Profile(Base):
    __tablename__ = "profiles"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    is_public = Column(Boolean, default=False)
    owner = relationship("User", backref="profiles")
    queries = relationship("SavedQuery", secondary=profile_queries, backref="profiles")

class ProfileRun(Base):
    __tablename__ = "profile_runs"
    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id"))
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    result_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    profile = relationship("Profile", backref="runs")
    user = relationship("User", backref="profile_runs")

class ExecutionHistory(Base):
    __tablename__ = "execution_history"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    item_type = Column(String(20), nullable=False)
    item_name = Column(String(200), nullable=False)
    promql = Column(Text, nullable=True) 
    status = Column(String(20), nullable=False)
    executed_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User")