# schemas.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="Имя пользователя (3-50 символов)")
    password: str = Field(..., min_length=6, max_length=128, description="Пароль (минимум 6 символов)")

class UserLogin(BaseModel):
    username: str = Field(..., description="Имя пользователя")
    password: str = Field(..., description="Пароль")

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str

class UserOut(BaseModel):
    id: int
    username: str
    class Config:
        from_attributes = True

class DataSourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Уникальное имя источника")
    url: str = Field(..., description="URL Prometheus/VictoriaMetrics")
    ds_type: str = Field(default="prometheus", description="Тип: prometheus или victoriametrics")

class DataSourceOut(DataSourceCreate):
    id: int
    creator_username: Optional[str] = None
    class Config:
        from_attributes = True

class SavedQueryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Имя запроса")
    promql: str = Field(..., description="PromQL выражение")
    datasource_id: int = Field(..., description="ID источника данных")
    step: str = Field(default="60s", description="Шаг времени")
    condition_min: Optional[float] = Field(None, description="Минимальное допустимое значение")
    condition_max: Optional[float] = Field(None, description="Максимальное допустимое значение")
    description: Optional[str] = Field(None, max_length=1000, description="Описание или комментарий")

class SavedQueryOut(SavedQueryCreate):
    id: int
    user_id: int
    class Config:
        from_attributes = True

class ProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Имя профиля")
    query_ids: List[int] = Field(..., description="Список ID запросов")
    is_public: bool = Field(default=False, description="Сделать публичным")

class ProfileOut(BaseModel):
    id: int
    name: str
    user_id: Optional[int]
    is_public: bool
    creator_username: Optional[str] = None
    queries: List[SavedQueryOut] = []
    class Config:
        from_attributes = True

class ExecuteQueryRequest(BaseModel):
    datasource_id: int = Field(..., description="ID источника")
    promql: str = Field(..., description="PromQL выражение")
    start_time: datetime = Field(..., description="Время начала")
    end_time: datetime = Field(..., description="Время окончания")
    step: str = Field(default="60s", description="Шаг времени")
    condition_min: Optional[float] = Field(None, description="Минимальное значение")
    condition_max: Optional[float] = Field(None, description="Максимальное значение")

class ExecuteProfileRequest(BaseModel):
    profile_id: int = Field(..., description="ID профиля")
    start_time: datetime = Field(..., description="Время начала")
    end_time: datetime = Field(..., description="Время окончания")
    step: str = Field(default="60s", description="Шаг времени")

class ViolationDetail(BaseModel):
    timestamp: int
    value: float
    type: str
    threshold: Optional[float]
    deviation: Optional[float]

class QueryExecutionResult(BaseModel):
    status: str
    message: str
    raw_data: List[Dict[str, Any]]
    violations: List[ViolationDetail]
    total_points: int
    success_count: int
    failed_count: int

class ProfileExecutionResult(BaseModel):
    profile_id: int
    profile_name: str
    start_time: str
    end_time: str
    total_queries: int
    success_count: int
    failed_count: int
    failed_details: List[Dict[str, Any]]
    success_details: List[Dict[str, Any]] = []

class HistoryItem(BaseModel):
    id: int
    item_type: str
    item_name: str
    promql: Optional[str]
    status: str
    executed_at: datetime
    class Config:
        from_attributes = True