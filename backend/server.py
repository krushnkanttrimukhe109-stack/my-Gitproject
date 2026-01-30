from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
import bcrypt
import jwt
from emergentintegrations.llm.chat import LlmChat, UserMessage
import json
import base64
from PIL import Image
import io

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

JWT_SECRET = os.environ.get('JWT_SECRET', 'default_secret_key')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_HOURS = 24 * 7

app = FastAPI()
api_router = APIRouter(prefix="/api")
security = HTTPBearer()

class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: EmailStr
    name: str
    password_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class UserRegister(BaseModel):
    email: EmailStr
    name: str
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    token: str
    user: dict

class CropAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    crop_name: str
    growth_stage: str
    symptoms: str
    soil_moisture: Optional[int] = None
    temperature: Optional[float] = None
    humidity: Optional[int] = None
    image_data: Optional[str] = None
    diagnosis: str
    confidence_score: int
    immediate_action: str
    sustainable_treatment: str
    resource_efficiency_tip: str
    risk_level: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class CropAnalysisRequest(BaseModel):
    crop_name: str
    growth_stage: str
    symptoms: str
    soil_moisture: Optional[int] = None
    temperature: Optional[float] = None
    humidity: Optional[int] = None

class CropAnalysisResponse(BaseModel):
    id: str
    crop_name: str
    growth_stage: str
    diagnosis: str
    confidence_score: int
    immediate_action: str
    sustainable_treatment: str
    resource_efficiency_tip: str
    risk_level: str
    created_at: datetime

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_token(user_id: str, email: str) -> str:
    payload = {
        'user_id': user_id,
        'email': email,
        'exp': datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get('user_id')
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user = await db.users.find_one({'id': user_id}, {'_id': 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

@api_router.post("/auth/register", response_model=TokenResponse)
async def register(data: UserRegister):
    existing_user = await db.users.find_one({'email': data.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user = User(
        email=data.email,
        name=data.name,
        password_hash=hash_password(data.password)
    )
    
    user_dict = user.model_dump()
    user_dict['created_at'] = user_dict['created_at'].isoformat()
    await db.users.insert_one(user_dict)
    
    token = create_token(user.id, user.email)
    return TokenResponse(
        token=token,
        user={'id': user.id, 'email': user.email, 'name': user.name}
    )

@api_router.post("/auth/login", response_model=TokenResponse)
async def login(data: UserLogin):
    user = await db.users.find_one({'email': data.email}, {'_id': 0})
    if not user or not verify_password(data.password, user['password_hash']):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    token = create_token(user['id'], user['email'])
    return TokenResponse(
        token=token,
        user={'id': user['id'], 'email': user['email'], 'name': user['name']}
    )

@api_router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        'id': current_user['id'],
        'email': current_user['email'],
        'name': current_user['name']
    }

async def analyze_crop_with_ai(request_data: dict, image_base64: Optional[str] = None) -> dict:
    system_message = """You are EcoCrop AI, a sustainable agriculture expert. Analyze crop health data and provide eco-friendly farming advice.

You MUST respond with ONLY valid JSON in this exact format:
{
  "diagnosis": "Brief diagnosis (e.g., Early Blight, Water Stress)",
  "confidence_score": 85,
  "immediate_action": "Urgent step needed",
  "sustainable_treatment": "Detailed organic/eco-friendly solution",
  "resource_efficiency_tip": "Water/energy saving advice",
  "risk_level": "Low or Medium or High"
}

Prioritize:
- Organic pest control over synthetic pesticides
- Water-efficient irrigation techniques
- Soil health through composting and crop rotation
- Minimize chemical runoff"""

    user_text = f"""Analyze this crop:
Crop: {request_data.get('crop_name')}
Growth Stage: {request_data.get('growth_stage')}
Symptoms: {request_data.get('symptoms')}
"""
    
    if request_data.get('soil_moisture'):
        user_text += f"\nSoil Moisture: {request_data.get('soil_moisture')}%"
    if request_data.get('temperature'):
        user_text += f"\nTemperature: {request_data.get('temperature')}°C"
    if request_data.get('humidity'):
        user_text += f"\nHumidity: {request_data.get('humidity')}%"
    
    if image_base64:
        user_text += "\n\nNote: Image of crop symptoms provided for visual analysis."
    
    user_text += "\n\nProvide analysis in JSON format only."
    
    chat = LlmChat(
        api_key=os.environ.get('EMERGENT_LLM_KEY'),
        session_id=f"crop_analysis_{uuid.uuid4()}",
        system_message=system_message
    ).with_model("gemini", "gemini-3-flash-preview")
    
    user_message = UserMessage(text=user_text)
    response = await chat.send_message(user_message)
    
    try:
        response_text = response.strip()
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        if response_text.endswith('```'):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        result = json.loads(response_text)
        
        if result.get('confidence_score'):
            result['confidence_score'] = int(result['confidence_score'])
        
        return result
    except json.JSONDecodeError:
        return {
            'diagnosis': 'Analysis completed',
            'confidence_score': 75,
            'immediate_action': 'Monitor crop closely',
            'sustainable_treatment': response[:200],
            'resource_efficiency_tip': 'Implement drip irrigation to conserve water',
            'risk_level': 'Medium'
        }

@api_router.post("/analysis", response_model=CropAnalysisResponse)
async def create_analysis(
    crop_name: str = Form(...),
    growth_stage: str = Form(...),
    symptoms: str = Form(...),
    soil_moisture: Optional[int] = Form(None),
    temperature: Optional[float] = Form(None),
    humidity: Optional[int] = Form(None),
    image: Optional[UploadFile] = File(None),
    current_user: dict = Depends(get_current_user)
):
    request_data = {
        'crop_name': crop_name,
        'growth_stage': growth_stage,
        'symptoms': symptoms,
        'soil_moisture': soil_moisture,
        'temperature': temperature,
        'humidity': humidity
    }
    
    image_base64 = None
    if image:
        image_bytes = await image.read()
        img = Image.open(io.BytesIO(image_bytes))
        img.thumbnail((800, 800))
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG")
        image_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    ai_result = await analyze_crop_with_ai(request_data, image_base64)
    
    analysis = CropAnalysis(
        user_id=current_user['id'],
        crop_name=crop_name,
        growth_stage=growth_stage,
        symptoms=symptoms,
        soil_moisture=soil_moisture,
        temperature=temperature,
        humidity=humidity,
        image_data=image_base64,
        diagnosis=ai_result.get('diagnosis', 'Unknown'),
        confidence_score=ai_result.get('confidence_score', 0),
        immediate_action=ai_result.get('immediate_action', ''),
        sustainable_treatment=ai_result.get('sustainable_treatment', ''),
        resource_efficiency_tip=ai_result.get('resource_efficiency_tip', ''),
        risk_level=ai_result.get('risk_level', 'Medium')
    )
    
    analysis_dict = analysis.model_dump()
    analysis_dict['created_at'] = analysis_dict['created_at'].isoformat()
    await db.analyses.insert_one(analysis_dict)
    
    return CropAnalysisResponse(
        id=analysis.id,
        crop_name=analysis.crop_name,
        growth_stage=analysis.growth_stage,
        diagnosis=analysis.diagnosis,
        confidence_score=analysis.confidence_score,
        immediate_action=analysis.immediate_action,
        sustainable_treatment=analysis.sustainable_treatment,
        resource_efficiency_tip=analysis.resource_efficiency_tip,
        risk_level=analysis.risk_level,
        created_at=analysis.created_at
    )

@api_router.get("/analysis/history", response_model=List[CropAnalysisResponse])
async def get_analysis_history(current_user: dict = Depends(get_current_user)):
    analyses = await db.analyses.find(
        {'user_id': current_user['id']},
        {'_id': 0}
    ).sort('created_at', -1).to_list(100)
    
    for analysis in analyses:
        if isinstance(analysis['created_at'], str):
            analysis['created_at'] = datetime.fromisoformat(analysis['created_at'])
    
    return [
        CropAnalysisResponse(
            id=a['id'],
            crop_name=a['crop_name'],
            growth_stage=a['growth_stage'],
            diagnosis=a['diagnosis'],
            confidence_score=a['confidence_score'],
            immediate_action=a['immediate_action'],
            sustainable_treatment=a['sustainable_treatment'],
            resource_efficiency_tip=a['resource_efficiency_tip'],
            risk_level=a['risk_level'],
            created_at=a['created_at']
        )
        for a in analyses
    ]

@api_router.get("/analysis/{analysis_id}")
async def get_analysis_detail(
    analysis_id: str,
    current_user: dict = Depends(get_current_user)
):
    analysis = await db.analyses.find_one(
        {'id': analysis_id, 'user_id': current_user['id']},
        {'_id': 0}
    )
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    if isinstance(analysis['created_at'], str):
        analysis['created_at'] = datetime.fromisoformat(analysis['created_at'])
    
    return analysis

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()