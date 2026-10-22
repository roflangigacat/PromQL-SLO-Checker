# main.py
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import outerjoin
from typing import List
import httpx
import json

from database import get_db
from models import User, DataSource, SavedQuery, Profile, ProfileRun, ExecutionHistory, profile_queries
from auth import get_current_user, create_access_token, get_password_hash, verify_password
from schemas import (
    UserCreate, UserLogin, Token, UserOut,
    DataSourceCreate, DataSourceOut,
    SavedQueryCreate, SavedQueryOut,
    ProfileCreate, ProfileOut,
    ExecuteQueryRequest, ExecuteProfileRequest,
    QueryExecutionResult, ProfileExecutionResult, HistoryItem
)

app = FastAPI(
    title="PromQL SLO Checker API",
    description="API для проверки SLO на основе PromQL запросов",
    version="1.2.0",
    openapi_tags=[
        {"name": "Authentication", "description": "Регистрация и вход"},
        {"name": "Data Sources", "description": "Глобальные источники данных"},
        {"name": "Queries", "description": "Управление PromQL запросами"},
        {"name": "Profiles", "description": "Профили проверок и история"},
        {"name": "Execution", "description": "Выполнение запросов и анализ SLO"},
    ]
)

@app.post("/api/auth/register", response_model=Token, tags=["Authentication"])
def register(payload: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(400, "Username already exists")
    user = User(username=payload.username, hashed_password=get_password_hash(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return Token(access_token=create_access_token({"sub": str(user.id)}), username=user.username)

@app.post("/api/auth/login", response_model=Token, tags=["Authentication"])
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    return Token(access_token=create_access_token({"sub": str(user.id)}), username=user.username)

@app.get("/api/auth/me", response_model=UserOut, tags=["Authentication"])
def get_current_user_info(user: User = Depends(get_current_user)):
    return UserOut(id=user.id, username=user.username)

@app.get("/api/datasources", response_model=List[DataSourceOut], tags=["Data Sources"])
def get_datasources(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    results = db.query(DataSource, User.username).outerjoin(User, DataSource.user_id == User.id).all()
    return [
        {
            "id": ds.id,
            "name": ds.name,
            "url": ds.url,
            "ds_type": ds.ds_type,
            "creator_username": username
        }
        for ds, username in results
    ]

@app.post("/api/datasources", response_model=DataSourceOut, tags=["Data Sources"])
def add_datasource(payload: DataSourceCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if db.query(DataSource).filter(DataSource.name == payload.name).first():
        raise HTTPException(400, f"Источник с именем '{payload.name}' уже существует")
    ds = DataSource(name=payload.name, url=payload.url, ds_type=payload.ds_type, user_id=user.id)
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return {
        "id": ds.id,
        "name": ds.name,
        "url": ds.url,
        "ds_type": ds.ds_type,
        "creator_username": user.username
    }

@app.delete("/api/datasources/{ds_id}", tags=["Data Sources"])
def delete_datasource(ds_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds = db.query(DataSource).filter(DataSource.id == ds_id).first()
    if not ds:
        raise HTTPException(404, "Источник не найден")
    db.delete(ds)
    db.commit()
    return {"status": "ok"}

@app.post("/api/datasources/{ds_id}/check", tags=["Data Sources"])
def check_datasource(ds_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds = db.query(DataSource).filter(DataSource.id == ds_id).first()
    if not ds:
        raise HTTPException(404, "Источник не найден")
    try:
        response = httpx.get(f"{ds.url}/api/v1/query", params={"query": "up"}, timeout=5.0)
        response.raise_for_status()
        return {"ok": True, "status": "available"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    
@app.get("/api/datasources/{ds_id}/labels", tags=["Data Sources"])
def get_labels(ds_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds = db.query(DataSource).filter(DataSource.id == ds_id).first()
    if not ds:
        raise HTTPException(404, "Источник не найден")
    try:
        response = httpx.get(f"{ds.url}/api/v1/labels", timeout=10.0)
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])
    except Exception as e:
        raise HTTPException(500, f"Ошибка получения label: {str(e)}")

@app.get("/api/datasources/{ds_id}/label-values/{label_name}", tags=["Data Sources"])
def get_label_values(ds_id: int, label_name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds = db.query(DataSource).filter(DataSource.id == ds_id).first()
    if not ds:
        raise HTTPException(404, "Источник не найден")
    try:
        response = httpx.get(f"{ds.url}/api/v1/label/{label_name}/values", timeout=10.0)
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])
    except Exception as e:
        raise HTTPException(500, f"Ошибка получения значений: {str(e)}")

@app.get("/api/queries", response_model=List[SavedQueryOut], tags=["Queries"])
def get_queries(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(SavedQuery).filter(SavedQuery.user_id == user.id).all()

@app.post("/api/queries", response_model=SavedQueryOut, tags=["Queries"])
def save_query(payload: SavedQueryCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = SavedQuery(
        name=payload.name,
        promql=payload.promql,
        datasource_id=payload.datasource_id,
        step=payload.step,
        condition_min=payload.condition_min,
        condition_max=payload.condition_max,
        description=payload.description,
        user_id=user.id
    )
    db.add(query)
    db.commit()
    db.refresh(query)
    return query

@app.delete("/api/queries/{query_id}", tags=["Queries"])
def delete_query(query_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(SavedQuery).filter(SavedQuery.id == query_id, SavedQuery.user_id == user.id).first()
    if not query:
        raise HTTPException(404, "Запрос не найден")
    db.delete(query)
    db.commit()
    return {"status": "ok"}

@app.get("/api/profiles", response_model=List[ProfileOut], tags=["Profiles"])
def get_profiles(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    results = db.query(Profile, User.username).outerjoin(User, Profile.user_id == User.id).filter(
        (Profile.user_id == user.id) | (Profile.is_public == True)
    ).all()
    
    out = []
    for profile, username in results:
        out.append({
            "id": profile.id,
            "name": profile.name,
            "user_id": profile.user_id,
            "is_public": profile.is_public if profile.is_public is not None else False,
            "creator_username": username,
            "queries": profile.queries
        })
    return out

@app.post("/api/profiles", response_model=ProfileOut, tags=["Profiles"])
def create_profile(payload: ProfileCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    queries = db.query(SavedQuery).filter(SavedQuery.id.in_(payload.query_ids)).all()
    profile = Profile(
        name=payload.name,
        user_id=user.id,
        is_public=payload.is_public,
        queries=queries
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return {
        "id": profile.id,
        "name": profile.name,
        "user_id": profile.user_id,
        "is_public": profile.is_public,
        "creator_username": user.username,
        "queries": profile.queries
    }

@app.put("/api/profiles/{profile_id}/queries", response_model=ProfileOut, tags=["Profiles"])
def update_profile_queries(profile_id: int, query_ids: List[int], db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == user.id).first()
    if not profile:
        raise HTTPException(404, "Профиль не найден или нет прав")
    queries = db.query(SavedQuery).filter(SavedQuery.id.in_(query_ids)).all()
    profile.queries = queries
    db.commit()
    db.refresh(profile)
    return {
        "id": profile.id,
        "name": profile.name,
        "user_id": profile.user_id,
        "is_public": profile.is_public,
        "creator_username": user.username,
        "queries": profile.queries
    }

@app.delete("/api/profiles/{profile_id}", tags=["Profiles"])
def delete_profile(profile_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == user.id).first()
    if not profile:
        raise HTTPException(404, "Профиль не найден")
    db.delete(profile)
    db.commit()
    return {"status": "ok"}

@app.post("/api/profiles/{profile_id}/copy", response_model=ProfileOut, tags=["Profiles"])
def copy_profile(profile_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    original = db.query(Profile).filter(Profile.id == profile_id, Profile.is_public == True).first()
    if not original:
        raise HTTPException(404, "Публичный профиль не найден")
    new_profile = Profile(
        name=f"{original.name} (копия)",
        user_id=user.id,
        is_public=False,
        queries=original.queries
    )
    db.add(new_profile)
    db.commit()
    db.refresh(new_profile)
    return {
        "id": new_profile.id,
        "name": new_profile.name,
        "user_id": new_profile.user_id,
        "is_public": new_profile.is_public,
        "creator_username": user.username,
        "queries": new_profile.queries
    }

@app.get("/api/profiles/{profile_id}/runs", tags=["Profiles"])
def get_profile_runs(profile_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    runs = db.query(ProfileRun).filter(ProfileRun.profile_id == profile_id).order_by(ProfileRun.created_at.desc()).limit(50).all()
    return runs

@app.get("/api/history", response_model=List[HistoryItem], tags=["Execution"])
def get_user_history(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    history = db.query(ExecutionHistory).filter(
        ExecutionHistory.user_id == user.id
    ).order_by(ExecutionHistory.executed_at.desc()).limit(100).all()
    return history

@app.post("/api/execute", response_model=QueryExecutionResult, tags=["Execution"])
def execute_query(payload: ExecuteQueryRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds = db.query(DataSource).filter(DataSource.id == payload.datasource_id).first()
    if not ds:
        raise HTTPException(404, "Источник не найден")
    
    try:
        response = httpx.post(
            f"{ds.url}/api/v1/query_range",
            params={
                "query": payload.promql,
                "start": int(payload.start_time.timestamp()),
                "end": int(payload.end_time.timestamp()),
                "step": payload.step
            },
            timeout=30.0
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        raise HTTPException(500, f"Ошибка выполнения запроса: {str(e)}")
    
    violations = []
    total_points = 0
    success_count = 0
    failed_count = 0
    
    for series in data.get("data", {}).get("result", []):
        for timestamp, value_str in series.get("values", []):
            total_points += 1
            value = float(value_str)
            violation = None
            
            if payload.condition_min is not None and value < payload.condition_min:
                violation = {
                    "timestamp": int(timestamp),
                    "value": value,
                    "type": "min_violation",
                    "threshold": payload.condition_min,
                    "deviation": round(payload.condition_min - value, 4)
                }
            elif payload.condition_max is not None and value > payload.condition_max:
                violation = {
                    "timestamp": int(timestamp),
                    "value": value,
                    "type": "max_violation",
                    "threshold": payload.condition_max,
                    "deviation": round(value - payload.condition_max, 4)
                }
            
            if violation:
                violations.append(violation)
                failed_count += 1
            else:
                success_count += 1
    
    status = "success" if failed_count == 0 else "failed"
    message = "Критерии соблюдены" if status == "success" else f"Обнаружено {failed_count} нарушений"
    
    item_name = payload.promql[:100] + "..." if len(payload.promql) > 100 else payload.promql
    history_record = ExecutionHistory(
        user_id=user.id,
        item_type="query",
        item_name=item_name,
        promql=payload.promql,
        status=status
    )
    db.add(history_record)
    db.commit()
    
    return {
        "status": status,
        "message": message,
        "raw_data": data.get("data", {}).get("result", []),
        "violations": violations,
        "total_points": total_points,
        "success_count": success_count,
        "failed_count": failed_count
    }

@app.post("/api/profiles/execute", response_model=ProfileExecutionResult, tags=["Execution"])
def run_profile(payload: ExecuteProfileRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    profile = db.query(Profile).filter(Profile.id == payload.profile_id).first()
    if not profile:
        raise HTTPException(404, "Профиль не найден")
    
    total_queries = len(profile.queries)
    success_count = 0
    failed_count = 0
    failed_details = []
    success_details = []
    
    for query in profile.queries:
        try:
            ds = db.query(DataSource).filter(DataSource.id == query.datasource_id).first()
            if not ds:
                continue
            
            response = httpx.post(
                f"{ds.url}/api/v1/query_range",
                params={
                    "query": query.promql,
                    "start": int(payload.start_time.timestamp()),
                    "end": int(payload.end_time.timestamp()),
                    "step": payload.step
                },
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            
            query_violations = []
            query_failed = 0
            total_points = 0
            
            for series in data.get("data", {}).get("result", []):
                for timestamp, value_str in series.get("values", []):
                    total_points += 1
                    value = float(value_str)
                    if (query.condition_min is not None and value < query.condition_min) or \
                       (query.condition_max is not None and value > query.condition_max):
                        query_violations.append({"timestamp": int(timestamp), "value": value})
                        query_failed += 1
            
            if query_failed > 0:
                failed_count += 1
                failed_details.append({
                    "query_id": query.id,
                    "query_name": query.name,
                    "promql": query.promql,
                    "description": query.description,
                    "condition_min": query.condition_min,
                    "condition_max": query.condition_max,
                    "datasource_id": query.datasource_id,
                    "step": query.step,
                    "violations_count": query_failed,
                    "total_points": total_points,
                    "violations": query_violations[:10]
                })
            else:
                success_count += 1
                success_details.append({
                    "query_id": query.id,
                    "query_name": query.name,
                    "promql": query.promql,
                    "description": query.description,
                    "condition_min": query.condition_min,
                    "condition_max": query.condition_max,
                    "datasource_id": query.datasource_id,
                    "step": query.step,
                    "total_points": total_points
                })
                
        except Exception as e:
            failed_count += 1
            failed_details.append({"query_id": query.id, "query_name": query.name, "error": str(e)})
    
    result_status = "success" if failed_count == 0 else "failed"
    
    result_payload = {
        "profile_id": profile.id,
        "profile_name": profile.name,
        "start_time": payload.start_time.isoformat(),
        "end_time": payload.end_time.isoformat(),
        "total_queries": total_queries,
        "success_count": success_count,
        "failed_count": failed_count,
        "failed_details": failed_details,
        "success_details": success_details
    }
    
    history_record = ExecutionHistory(
        user_id=user.id,
        item_type="profile",
        item_name=profile.name,
        promql=None,
        status=result_status
    )
    db.add(history_record)
    
    run = ProfileRun(
        profile_id=profile.id,
        user_id=user.id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        result_json=json.dumps(result_payload)
    )
    db.add(run)
    db.commit()
    
    return result_payload

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")
