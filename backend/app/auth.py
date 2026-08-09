from passlib.context import CryptContext
from jose import jwt
from app.config import JWT_SECRET
from datetime import datetime, timedelta, timezone

ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password):
    hashed_password = pwd_context.hash(password)
    return hashed_password

def verify_password(password,hashed_password):
    verify = pwd_context.verify(password,hashed_password)
    return verify

def create_access_token(email):
    expire = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    payload = {
        "sub" : email,
        "exp" : expire
    }
    token = jwt.encode(payload,JWT_SECRET,algorithm=ALGORITHM)
    return token

def decode_access_token(token):
    payload = jwt.decode(token,JWT_SECRET,algorithms=[ALGORITHM])
    payload_email = payload["sub"]
    return payload_email